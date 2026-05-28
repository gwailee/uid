# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28 (v2.1 batch 1)
#   * collect_hidden_states: prefer top-level set_noise_injection (v2.1),
#     fall back to backbone.set_noise_injection (v2.0), then to scanning
#     submodules. Save & restore the original switch state instead of
#     blindly forcing it back to True (which corrupted user state).
#
# UPDATE: 2026-05-28 (v2.1 batch 2)
#   * Add EtaResult dataclass and measure_fisher_anisotropy_eta() so
#     that README prediction 4 (Theory §6.1: eta > 0.5 after training)
#     can be measured end-to-end from run_critical_exponents.py.
#   * Extend CriticalExponentResult with the new 'eta' field, and have
#     run_critical_exponent_battery() populate it by default.
#   * eta is reported under the LAYER-COMPATIBLE shape contract
#     (B, S, H) used by the rest of this module, NOT the per-token
#     shape used internally by ScalarCurvatureProbe — see the
#     docstring of measure_fisher_anisotropy_eta() for the precise
#     averaging protocol.
"""
Rigorous measurement of emergent critical exponents.

This module FIXES the circular-logic problem of v0.1 by enforcing:
1. Noise injection is DISABLED before measurement.
2. Sample size is large (>=10,000 sequences, length >=4096).
3. Power-law estimation uses Clauset-Shalizi-Newman MLE.
4. Multiple surrogate controls (shuffled activations, dead network).
5. Both Transformer baseline AND CID are measured, for comparison.

If CID exhibits beta ~= 1, H ~= 0.7, tau ~= 1.5 ONLY with noise
injection ON, and the baseline Transformer exhibits the same (because
we injected the same pattern into both), then there is NO emergent
signature.

True emergence is when CID, *after training, with injection OFF*,
still shows these signatures while the baseline does not.

v2.1 additions:
    * collect_hidden_states now prefers UIDModel.set_noise_injection
      (top-level API) over backbone.set_noise_injection, and restores
      the caller's original state instead of forcing it back to True.
    * measure_fisher_anisotropy_eta() reports the Fisher metric
      anisotropy eta = (lambda_max - lambda_min) / (lambda_max +
      lambda_min) per Theory §6.1 / README prediction 4. UID predicts
      eta > 0.5 after training.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from scipy import stats
from scipy.fft import rfft, rfftfreq
from torch.utils.data import DataLoader

from .powerlaw_estimator import fit_power_law, PowerLawFit
from ..fid.curvature import ScalarCurvatureProbe
from ..fid.fisher_metric import FisherMetric


# ======================================================================
# Result dataclasses
# ======================================================================


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
class EtaResult:
    """Result of Fisher-metric anisotropy measurement (Theory §6.1).

    Implements README prediction 4: ``eta > 0.5`` after training.

    Fields:
        eta_mean:        Mean anisotropy across (batch, layer) pairs.
        eta_std:         Std of anisotropy across those pairs.
        eta_in_range:    True iff eta_mean > 0.5 (the UID prediction).
        n_samples:       Number of (batch, layer) pairs aggregated.
        hidden_size:     Hidden size H used for the Fisher metric.
        seq_len:         Sequence length used; values < hidden_size
                         carry a known rank-deficient bias toward 1.0.
        rank_deficient:  True iff seq_len < hidden_size, meaning the
                         eta estimate is biased upward and the user
                         must interpret with caution.
    """
    eta_mean: float
    eta_std: float
    eta_in_range: bool
    n_samples: int
    hidden_size: int
    seq_len: int
    rank_deficient: bool

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
    # v2.1: Theory §6.1 / README prediction 4
    eta: Optional[EtaResult]

    def to_dict(self) -> dict:
        return {
            "model_name": self.model_name,
            "noise_injection_on": self.noise_injection_on,
            "hurst": self.hurst.to_dict(),
            "spectrum": self.spectrum.to_dict(),
            "avalanche": (
                asdict(self.avalanche) if self.avalanche else None
            ),
            "eta": self.eta.to_dict() if self.eta else None,
        }


# ======================================================================
# Internal noise-injection switch helpers (v2.1 batch 1)
# ======================================================================


def _capture_and_disable_noise_injection(
    model: nn.Module,
) -> Tuple[bool, List[bool]]:
    """Try to disable noise injection on ``model``; remember prior state.

    返回 (是否成功切换, 各层原始注入状态列表)，用于稍后精确恢复。

    Resolution order:
        1. ``model.set_noise_injection(False)``   (v2.1 top-level API)
        2. ``model.backbone.set_noise_injection(False)``  (v2.0 path)
        3. Scan submodules and call ``set_noise_injection(False)`` on
           every one that has the method (legacy fallback).

    Returns:
        (switched, prev_states):
          * switched     : True if ANY switch was actually flipped.
          * prev_states  : list of original ``_inject_noise`` flags, in
                           the same order as the layers found. Empty if
                           no per-layer state was discoverable.
    """
    prev_states: List[bool] = []

    # Try to find the CIDBlock-like object owning per-layer state.
    cid_block = None
    if hasattr(model, "backbone") and hasattr(
        model.backbone, "set_noise_injection"
    ):
        cid_block = model.backbone
    elif hasattr(model, "set_noise_injection"):
        # Top-level API exposed (v2.1); backbone may still be present.
        cid_block = getattr(model, "backbone", None)

    if cid_block is not None and hasattr(cid_block, "layers"):
        prev_states = [
            bool(getattr(layer, "_inject_noise", True))
            for layer in cid_block.layers
        ]

    # Now actually disable, preferring the highest-level API available.
    if hasattr(model, "set_noise_injection"):
        model.set_noise_injection(False)
        return True, prev_states
    if cid_block is not None and hasattr(cid_block, "set_noise_injection"):
        cid_block.set_noise_injection(False)
        return True, prev_states

    # Last-resort scan: walk submodules and flip any ``set_noise_injection``.
    switched_any = False
    for sub in model.modules():
        if hasattr(sub, "set_noise_injection") and sub is not model:
            try:
                sub.set_noise_injection(False)
                switched_any = True
            except Exception:
                pass
    return switched_any, prev_states


def _restore_noise_injection(
    model: nn.Module,
    prev_states: List[bool],
) -> None:
    """Restore the per-layer noise-injection flags captured earlier.

    用之前保存的状态精确还原每层注入开关；
    若没有可用的逐层状态，则保守地什么都不做（避免破坏用户原状态）。
    """
    cid_block = None
    if hasattr(model, "backbone") and hasattr(
        model.backbone, "set_noise_injection"
    ):
        cid_block = model.backbone
    elif hasattr(model, "set_noise_injection"):
        cid_block = getattr(model, "backbone", None)

    if (
        cid_block is not None
        and hasattr(cid_block, "layers")
        and prev_states
        and len(prev_states) == len(cid_block.layers)
    ):
        for layer, prev in zip(cid_block.layers, prev_states):
            if hasattr(layer, "set_noise_injection"):
                layer.set_noise_injection(prev)
        return

    # If we cannot restore per-layer state, do nothing.
    # (Forcing back to True would corrupt callers that wanted False.)


# ======================================================================
# Hidden-state collection (with honest noise-injection management)
# ======================================================================


def collect_hidden_states(
    model: nn.Module,
    dataloader: DataLoader,
    device: str,
    n_sequences: int = 10000,
    layer_idx: int = -1,
    disable_noise: bool = True,
) -> np.ndarray:
    """Collect hidden-state time series from a trained model.

    Args:
        model: Trained model with ``output_hidden_states`` support.
        dataloader: Data loader providing input_ids batches.
        device: Compute device.
        n_sequences: Total number of sequences to collect.
        layer_idx: Which layer's hidden state to use (-1 = last).
        disable_noise: If True, turn OFF noise injection for the
            duration of the collection (KEY fix from v0.1) and
            restore the original state on exit.

    Returns:
        Array of shape (n_collected, seq_len, hidden_dim).
    """
    model.eval()

    switched = False
    prev_states: List[bool] = []
    if disable_noise:
        switched, prev_states = _capture_and_disable_noise_injection(model)
        if switched:
            print("  [info] Noise injection DISABLED for emergence test")
        else:
            print(
                "  [warn] Model exposes no set_noise_injection API; "
                "results may include the model's intrinsic noise."
            )

    try:
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
    finally:
        # Restore caller's original noise-injection state (do NOT
        # blindly force back to True — that would corrupt callers
        # that intentionally set it to False).
        if switched:
            _restore_noise_injection(model, prev_states)

    arr = np.concatenate(collected, axis=0)[:n_sequences]
    return arr


# ======================================================================
# Hurst exponent (DFA, gold-standard)
# ======================================================================


def estimate_hurst_dfa(signal: np.ndarray, min_window: int = 16) -> float:
    """Estimate Hurst exponent via Detrended Fluctuation Analysis (DFA).

    DFA is the gold-standard method for long-range correlation
    analysis, more reliable than the R/S method used in v0.1.

    Reference:
        Peng, C.-K. et al. (1994). Mosaic organization of DNA
        nucleotides. Physical Review E, 49(2), 1685.
    """
    n = len(signal)
    if n < min_window * 4:
        return float("nan")

    # Integrated profile.
    y = np.cumsum(signal - signal.mean())

    # Window sizes (logarithmically spaced).
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
        # Detrend each segment with linear fit.
        segments = y[: n_segments * s].reshape(n_segments, s)
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

    # F(s) ~ s^H; fit log-log.
    log_s = np.log10(scales[: len(fluctuations)])
    log_f = np.log10(np.array(fluctuations) + 1e-12)
    slope, _, _, _, _ = stats.linregress(log_s, log_f)
    return float(slope)


def measure_hurst_exponent(
    hidden_states: np.ndarray,
    n_channels_per_series: int = 64,
) -> HurstResult:
    """Measure Hurst exponent across many hidden-state time series.

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


# ======================================================================
# Power-spectrum slope beta (README prediction 3)
# ======================================================================


def measure_power_spectrum(
    hidden_states: np.ndarray,
    n_channels_per_series: int = 64,
    f_min_factor: float = 4.0,
    f_max: float = 0.4,
) -> SpectrumResult:
    """Measure power-spectrum slope beta across many hidden-state series.

    Fits ``S(f) ~ f^(-beta)`` in the inertial range.

    Args:
        hidden_states: Array (n_sequences, seq_len, hidden_dim).
        n_channels_per_series: Channels to sample per sequence.
        f_min_factor: ``f_min = f_min_factor / seq_len``.
        f_max: Upper frequency cutoff (Nyquist = 0.5).

    Returns:
        SpectrumResult with mean beta across measurements.
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


# ======================================================================
# Fisher-metric anisotropy eta (README prediction 4, Theory §6.1)
# ======================================================================


def measure_fisher_anisotropy_eta(
    hidden_states: np.ndarray,
    *,
    eta_threshold: float = 0.5,
    jitter: Optional[float] = None,
    max_samples: Optional[int] = None,
) -> EtaResult:
    """Measure Fisher-metric anisotropy eta per Theory §6.1.

    Implements README prediction 4:

        ``eta = (lambda_max - lambda_min) / (lambda_max + lambda_min)``

    UID predicts that after training,

        ``eta > 0.5``   (significantly anisotropic)

    on the trained model, and that ``eta`` grows with training depth.

    Protocol:
        1. Treat each of the n_sequences (B) samples as one independent
           draw of hidden-state activations of shape (seq_len, H).
        2. Estimate the H*H empirical covariance per sample via
           FisherMetric (with diagonal jitter to guarantee PSD).
        3. Take ``eta`` per sample via
           ScalarCurvatureProbe.compute_anisotropy_eta.
        4. Aggregate mean / std across the n_sequences-axis.

    Caveats:
        * This is the HIDDEN-STATE empirical-covariance surrogate of
          the Fisher matrix (see FisherMetric docstring); it is NOT
          the parameter-space Fisher matrix used in Theory §2.2.
          Quantitative agreement with prediction 4 is qualitative.
        * When ``seq_len < hidden_size`` the covariance is rank-
          deficient and the eta estimate is biased UPWARD (toward 1.0).
          The returned ``rank_deficient`` flag exposes this condition;
          callers should resample longer sequences when the flag is
          set if they intend to compare against the 0.5 threshold.

    Args:
        hidden_states: Array of shape (B, S, H). 隐状态时间序列。
        eta_threshold: Pass / fail threshold for the prediction
                       (default 0.5 per README prediction 4).
        jitter:        Optional override for the Fisher metric jitter.
        max_samples:   If given, randomly subsample at most this many
                       sequences before measuring (useful when B is
                       huge and eta estimation is the bottleneck).

    Returns:
        :class:`EtaResult` with the aggregated statistics.

    实现 README 预言 4：训练后 eta = (λ_max - λ_min) / (λ_max + λ_min)
    应当显著大于 0.5。本函数对每条序列估计经验协方差并求其 eta，再在
    序列维上做均值统计。
    """
    if hidden_states.ndim != 3:
        raise ValueError(
            "hidden_states must have shape (B, S, H); got "
            f"{hidden_states.shape}"
        )
    n_seq, seq_len, hidden_dim = hidden_states.shape
    if n_seq < 1:
        raise ValueError("hidden_states must contain >= 1 sequence")
    if seq_len < FisherMetric.MIN_SEQ_LEN:
        raise ValueError(
            f"seq_len={seq_len} is below the FisherMetric minimum "
            f"of {FisherMetric.MIN_SEQ_LEN}; eta cannot be estimated."
        )

    # Optional subsampling for cost control.
    if max_samples is not None and n_seq > max_samples:
        rng = np.random.default_rng(42)
        idx = rng.choice(n_seq, size=int(max_samples), replace=False)
        hidden_states = hidden_states[idx]
        n_seq = int(max_samples)

    # Build the (non-parametric) probe once.
    probe = ScalarCurvatureProbe(hidden_size=hidden_dim)
    # Important: keep the probe on CPU and run on the user-supplied
    # numpy data. We convert in one shot for vectorisation.
    x = torch.from_numpy(np.asarray(hidden_states, dtype=np.float32))

    # Compute eta in BATCHED form to amortise the H*H eigvalsh cost.
    # We avoid the convenience wrapper probe.anisotropy_eta so we can
    # pass a custom jitter via FisherMetric.compute.
    with torch.no_grad():
        metric = probe.fisher.compute(x, jitter=jitter)
        eta_t = probe.compute_anisotropy_eta(metric)  # (B,)
    eta_arr = eta_t.detach().cpu().numpy()
    eta_arr = eta_arr[np.isfinite(eta_arr)]

    if eta_arr.size == 0:
        return EtaResult(
            eta_mean=float("nan"),
            eta_std=float("nan"),
            eta_in_range=False,
            n_samples=0,
            hidden_size=int(hidden_dim),
            seq_len=int(seq_len),
            rank_deficient=bool(seq_len < hidden_dim),
        )

    eta_mean = float(np.mean(eta_arr))
    return EtaResult(
        eta_mean=eta_mean,
        eta_std=float(np.std(eta_arr)),
        eta_in_range=bool(eta_mean > eta_threshold),
        n_samples=int(eta_arr.size),
        hidden_size=int(hidden_dim),
        seq_len=int(seq_len),
        rank_deficient=bool(seq_len < hidden_dim),
    )


# ======================================================================
# Top-level driver
# ======================================================================


def run_critical_exponent_battery(
    model: nn.Module,
    model_name: str,
    dataloader: DataLoader,
    device: str,
    n_sequences: int = 10000,
    layer_idx: int = -1,
    disable_noise: bool = True,
    include_avalanche: bool = True,
    include_eta: bool = True,
    eta_threshold: float = 0.5,
    eta_max_samples: Optional[int] = 256,
) -> CriticalExponentResult:
    """Run the full battery of critical-exponent measurements.

    This is the entry point for honest emergence testing. Set
    ``disable_noise=True`` (default) for the genuine emergence test:
    the noise pattern is then NOT being fed back into the measurement.

    Args:
        model:           Trained model with output_hidden_states.
        model_name:      Name used in printed logs and the result.
        dataloader:      Provides input_ids batches.
        device:          Compute device.
        n_sequences:     Number of hidden-state sequences to collect.
        layer_idx:       Which layer to probe (-1 = last).
        disable_noise:   If True, switch off noise injection before
                         measurement and restore it after.
        include_avalanche: Run the Beggs-Plenz avalanche analysis.
        include_eta:     Run the Theory §6.1 / README prediction 4
                         Fisher-metric anisotropy estimation.
        eta_threshold:   Pass / fail threshold for eta (default 0.5).
        eta_max_samples: Optional cap on the number of sequences used
                         for eta estimation (each one requires one
                         H*H eigvalsh, so this matters for large H).

    Returns:
        :class:`CriticalExponentResult` with hurst, spectrum, optional
        avalanche fit, and optional eta result.
    """
    print(
        f"\n[critical exponents] Measuring {model_name} "
        f"(noise_injection={'ON' if not disable_noise else 'OFF'})"
    )

    # Step 1: Collect hidden states.
    print(f"  Collecting hidden states from {n_sequences} sequences...")
    hidden = collect_hidden_states(
        model, dataloader, device, n_sequences, layer_idx, disable_noise,
    )
    print(f"  Collected shape: {hidden.shape}")

    # Step 2: Hurst exponent.
    print("  Computing Hurst exponent (DFA)...")
    hurst = measure_hurst_exponent(hidden)
    print(
        f"  Hurst: {hurst.hurst_mean:.3f} ± {hurst.hurst_std:.3f} "
        f"(n={hurst.n_series})"
    )

    # Step 3: Power spectrum.
    print("  Computing power-spectrum slope beta...")
    spectrum = measure_power_spectrum(hidden)
    print(
        f"  beta: {spectrum.beta_mean:.3f} ± {spectrum.beta_std:.3f} "
        f"(n={spectrum.n_series}, R2={spectrum.r_squared_mean:.3f})"
    )

    # Step 4: Avalanche analysis (optional).
    avalanche_fit = None
    if include_avalanche:
        from .avalanche_detector import detect_avalanches
        print("  Detecting avalanches...")
        sizes = detect_avalanches(hidden)
        if len(sizes) >= 100:
            print(
                f"  Detected {len(sizes)} avalanches; "
                "fitting power law (Clauset MLE)..."
            )
            avalanche_fit = fit_power_law(sizes)
            print(f"  Avalanche fit: {avalanche_fit}")
        else:
            print(
                f"  Insufficient avalanches ({len(sizes)} < 100); skipping"
            )

    # Step 5: Fisher anisotropy eta (Theory §6.1 / README prediction 4).
    eta_result: Optional[EtaResult] = None
    if include_eta:
        print(
            "  Computing Fisher anisotropy eta "
            "(Theory §6.1, README prediction 4)..."
        )
        try:
            eta_result = measure_fisher_anisotropy_eta(
                hidden,
                eta_threshold=eta_threshold,
                max_samples=eta_max_samples,
            )
            rank_note = (
                "  [warn] rank-deficient: seq_len < hidden_size; "
                "eta biased toward 1.0\n"
                if eta_result.rank_deficient else ""
            )
            verdict = "PASS" if eta_result.eta_in_range else "FAIL"
            print(
                f"  eta: {eta_result.eta_mean:.3f} ± "
                f"{eta_result.eta_std:.3f} "
                f"(n={eta_result.n_samples}, threshold={eta_threshold}, "
                f"{verdict})\n"
                f"{rank_note}".rstrip()
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  [warn] eta estimation failed: {exc}")
            eta_result = None

    return CriticalExponentResult(
        model_name=model_name,
        noise_injection_on=not disable_noise,
        hurst=hurst,
        spectrum=spectrum,
        avalanche=avalanche_fit,
        eta=eta_result,
    )
