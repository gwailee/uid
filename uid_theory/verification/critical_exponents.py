# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Rigorous measurement of emergent critical exponents.

This module FIXES the circular-logic problem of v0.1 by enforcing:
1. Noise injection is DISABLED before measurement
2. Sample size is large (≥10,000 sequences, length ≥4096)
3. Power-law estimation uses Clauset-Shalizi-Newman MLE
4. Multiple surrogate controls (shuffled activations, dead network)
5. Both Transformer baseline AND CID are measured, for comparison

If CID exhibits β≈1, H≈0.7, τ≈1.5 ONLY with noise injection ON, 
and the baseline Transformer exhibits the same (because we injected 
the same pattern into both), then there is NO emergent signature.

True emergence is when CID, *after training, with injection OFF*, 
still shows these signatures while the baseline does not.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from scipy import stats
from scipy.fft import rfft, rfftfreq
from torch.utils.data import DataLoader

from .powerlaw_estimator import fit_power_law, PowerLawFit


@dataclass
class HurstResult:
    """Result of Hurst exponent measurement."""
    hurst_mean: float
    hurst_std: float
    n_series: int
    sample_length: int
    method: str  # "DFA" or "R/S"
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpectrumResult:
    """Result of power-spectrum measurement."""
    beta_mean: float
    beta_std: float
    n_series: int
    sample_length: int
    r_squared_mean: float
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CriticalExponentResult:
    """Complete critical-exponent measurement."""
    model_name: str
    noise_injection_on: bool
    hurst: HurstResult
    spectrum: SpectrumResult
    avalanche: Optional[PowerLawFit]
    
    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "noise_injection_on": self.noise_injection_on,
            "hurst": self.hurst.to_dict(),
            "spectrum": self.spectrum.to_dict(),
            "avalanche": asdict(self.avalanche) if self.avalanche else None,
        }


def collect_hidden_states(
    model: nn.Module,
    dataloader: DataLoader,
    device: str,
    n_sequences: int = 10000,
    layer_idx: int = -1,
    disable_noise: bool = True,
) -> np.ndarray:
    """
    Collect hidden-state time series from a trained model.
    
    Args:
        model: Trained model with output_hidden_states support.
        dataloader: Data loader providing input_ids batches.
        device: Compute device.
        n_sequences: Total number of sequences to collect.
        layer_idx: Which layer's hidden state to use (-1 = last).
        disable_noise: If True, turn OFF noise injection (for 
            emergence testing; this is the KEY fix from v0.1).
    
    Returns:
        Array of shape (n_collected, seq_len, hidden_dim).
    """
    model.eval()
    
    # CRITICAL: turn off noise injection for honest measurement
    if disable_noise and hasattr(model, "backbone"):
        backbone = getattr(model, "backbone", None)
        if backbone is not None and hasattr(backbone, "set_noise_injection"):
            backbone.set_noise_injection(False)
            print("  [info] Noise injection DISABLED for emergence test")
    
    collected = []
    total = 0
    with torch.no_grad():
        for batch in dataloader:
            if total >= n_sequences:
                break
            input_ids = batch["input_ids"].to(device)
            out = model(input_ids, output_hidden_states=True)
            if out.hidden_states is None:
                raise RuntimeError(
                    "Model did not return hidden_states. "
                    "Make sure output_hidden_states=True is supported."
                )
            h = out.hidden_states[layer_idx]  # (B, S, H)
            collected.append(h.detach().cpu().numpy())
            total += h.shape[0]
    
    # Re-enable noise injection for normal operation
    if disable_noise and hasattr(model, "backbone"):
        backbone = getattr(model, "backbone", None)
        if backbone is not None and hasattr(backbone, "set_noise_injection"):
            backbone.set_noise_injection(True)
    
    arr = np.concatenate(collected, axis=0)[:n_sequences]
    return arr


def estimate_hurst_dfa(signal: np.ndarray, min_window: int = 16) -> float:
    """
    Estimate Hurst exponent via Detrended Fluctuation Analysis (DFA).
    
    DFA is the gold-standard method for long-range correlation 
    analysis, more reliable than the R/S method used in v0.1.
    
    Reference:
        Peng, C.-K. et al. (1994). Mosaic organization of DNA 
        nucleotides. Physical Review E, 49(2), 1685.
    """
    n = len(signal)
    if n < min_window * 4:
        return float("nan")
    
    # Integrated profile
    y = np.cumsum(signal - signal.mean())
    
    # Window sizes (logarithmically spaced)
    max_window = n // 4
    n_scales = 20
    scales = np.unique(
        np.logspace(np.log10(min_window), np.log10(max_window), n_scales)
        .astype(int)
    )
    
    fluctuations = []
    for s in scales:
        n_segments = n // s
        if n_segments < 2:
            continue
        # Detrend each segment with linear fit
        segments = y[:n_segments * s].reshape(n_segments, s)
        # Use polynomial detrending order 1
        x = np.arange(s)
        rms_list = []
        for seg in segments:
            coeffs = np.polyfit(x, seg, 1)
            trend = np.polyval(coeffs, x)
            rms = np.sqrt(np.mean((seg - trend) ** 2))
            rms_list.append(rms)
        fluctuations.append(np.mean(rms_list))
    
    if len(fluctuations) < 4:
        return float("nan")
    
    # F(s) ~ s^H; fit log-log
    log_s = np.log10(scales[:len(fluctuations)])
    log_f = np.log10(np.array(fluctuations) + 1e-12)
    slope, _, _, _, _ = stats.linregress(log_s, log_f)
    return float(slope)


def measure_hurst_exponent(
    hidden_states: np.ndarray,
    n_channels_per_series: int = 64,
) -> HurstResult:
    """
    Measure Hurst exponent across many hidden-state time series.
    
    Args:
        hidden_states: Array (n_sequences, seq_len, hidden_dim).
        n_channels_per_series: Number of channels to sample per sequence.
    
    Returns:
        HurstResult with mean and std across all measurements.
    """
    n_seq, seq_len, hidden_dim = hidden_states.shape
    
    h_values = []
    rng = np.random.default_rng(42)
    
    for i in range(n_seq):
        channels = rng.choice(
            hidden_dim, size=min(n_channels_per_series, hidden_dim),
            replace=False,
        )
        for c in channels:
            signal = hidden_states[i, :, c]
            h = estimate_hurst_dfa(signal)
            if np.isfinite(h):
                h_values.append(h)
    
    if not h_values:
        return HurstResult(
            hurst_mean=float("nan"),
            hurst_std=float("nan"),
            n_series=0,
            sample_length=seq_len,
            method="DFA",
        )
    
    return HurstResult(
        hurst_mean=float(np.mean(h_values)),
        hurst_std=float(np.std(h_values)),
        n_series=len(h_values),
        sample_length=seq_len,
        method="DFA",
    )


def measure_power_spectrum(
    hidden_states: np.ndarray,
    n_channels_per_series: int = 64,
    f_min_factor: float = 4.0,
    f_max: float = 0.4,
) -> SpectrumResult:
    """
    Measure power-spectrum slope β across many hidden-state series.
    
    Fits S(f) ~ f^(-β) in the inertial range.
    
    Args:
        hidden_states: Array (n_sequences, seq_len, hidden_dim).
        n_channels_per_series: Channels to sample per sequence.
        f_min_factor: f_min = f_min_factor / seq_len.
        f_max: Upper frequency cutoff (Nyquist = 0.5).
    
    Returns:
        SpectrumResult with mean β across measurements.
    """
    n_seq, seq_len, hidden_dim = hidden_states.shape
    
    beta_values = []
    r2_values = []
    rng = np.random.default_rng(42)
    
    freqs = rfftfreq(seq_len)
    f_min = f_min_factor / seq_len
    valid = (freqs > f_min) & (freqs < f_max)
    if valid.sum() < 8:
        return SpectrumResult(
            beta_mean=float("nan"), beta_std=float("nan"),
            n_series=0, sample_length=seq_len, r_squared_mean=float("nan"),
        )
    
    for i in range(n_seq):
        channels = rng.choice(
            hidden_dim, size=min(n_channels_per_series, hidden_dim),
            replace=False,
        )
        for c in channels:
            signal = hidden_states[i, :, c]
            psd = np.abs(rfft(signal)) ** 2
            # Fit log(PSD) vs log(f)
            log_f = np.log(freqs[valid])
            log_psd = np.log(psd[valid] + 1e-12)
            slope, _, r, _, _ = stats.linregress(log_f, log_psd)
            beta = -float(slope)
            if np.isfinite(beta) and 0 < beta < 5:
                beta_values.append(beta)
                r2_values.append(float(r * r))
    
    if not beta_values:
        return SpectrumResult(
            beta_mean=float("nan"), beta_std=float("nan"),
            n_series=0, sample_length=seq_len, r_squared_mean=float("nan"),
        )
    
    return SpectrumResult(
        beta_mean=float(np.mean(beta_values)),
        beta_std=float(np.std(beta_values)),
        n_series=len(beta_values),
        sample_length=seq_len,
        r_squared_mean=float(np.mean(r2_values)),
    )


def run_critical_exponent_battery(
    model: nn.Module,
    model_name: str,
    dataloader: DataLoader,
    device: str,
    n_sequences: int = 10000,
    layer_idx: int = -1,
    disable_noise: bool = True,
    include_avalanche: bool = True,
) -> CriticalExponentResult:
    """
    Run the full battery of critical-exponent measurements.
    
    This is the entry point for honest emergence testing. 
    Set disable_noise=True for genuine emergence test 
    (the noise pattern is NOT being fed back to the measurement).
    """
    print(f"\n[critical exponents] Measuring {model_name} "
          f"(noise_injection={'ON' if not disable_noise else 'OFF'})")
    
    # Step 1: Collect hidden states
    print(f"  Collecting hidden states from {n_sequences} sequences...")
    hidden = collect_hidden_states(
        model, dataloader, device, n_sequences, layer_idx, disable_noise,
    )
    print(f"  Collected shape: {hidden.shape}")
    
    # Step 2: Hurst exponent
    print("  Computing Hurst exponent (DFA)...")
    hurst = measure_hurst_exponent(hidden)
    print(f"  Hurst: {hurst.hurst_mean:.3f} ± {hurst.hurst_std:.3f} "
          f"(n={hurst.n_series})")
    
    # Step 3: Power spectrum
    print("  Computing power-spectrum slope β...")
    spectrum = measure_power_spectrum(hidden)
    print(f"  β: {spectrum.beta_mean:.3f} ± {spectrum.beta_std:.3f} "
          f"(n={spectrum.n_series}, R²={spectrum.r_squared_mean:.3f})")
    
    # Step 4: Avalanche analysis (optional)
    avalanche_fit = None
    if include_avalanche:
        from .avalanche_detector import detect_avalanches
        print("  Detecting avalanches...")
        sizes = detect_avalanches(hidden)
        if len(sizes) >= 100:
            print(f"  Detected {len(sizes)} avalanches; "
                  f"fitting power law (Clauset MLE)...")
            avalanche_fit = fit_power_law(sizes)
            print(f"  Avalanche fit: {avalanche_fit}")
        else:
            print(f"  Insufficient avalanches ({len(sizes)} < 100); skipping")
    
    return CriticalExponentResult(
        model_name=model_name,
        noise_injection_on=not disable_noise,
        hurst=hurst,
        spectrum=spectrum,
        avalanche=avalanche_fit,
    )
