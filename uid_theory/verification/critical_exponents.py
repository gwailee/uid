# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-06-22 (v2.2 — fix three measurement bugs)
#   BUG 1 (noise OFF == noise ON, bit-for-bit identical):
#     A CID model in eval()/no_grad does not inject stochastic noise on
#     the forward path, so disable_noise=True and =False produced the
#     SAME hidden states -> the OFF-vs-ON "genuine emergence" contrast was
#     vacuous. We REPLACE the meaningless noise-ON branch in the verdict
#     logic with a proper SHUFFLE SURROGATE control (the README already
#     promised "shuffled-activation surrogate"): real long-range structure
#     must COLLAPSE when the time axis is shuffled. collect_hidden_states
#     still honours disable_noise (for models that DO inject at inference),
#     but the battery no longer relies on an ON/OFF difference that a
#     well-behaved eval model cannot exhibit.
#   BUG 2 (eta == 0.9999 for EVERY model, incl. random transformer):
#     Per-sequence covariance from a (seq_len=512, H=256) sample is wildly
#     ill-conditioned (samples/dim ~ 2): lambda_max blows up, lambda_min -> 0,
#     so eta = (lmax-lmin)/(lmax+lmin) -> 1 regardless of the model. We now
#     estimate ONE GLOBAL covariance from all (B*S, H) tokens (hundreds of
#     thousands of samples), giving a well-conditioned spectrum and a
#     discriminative eta. Optional Ledoit-Wolf shrinkage stabilises lambda_min.
#   BUG 3 (beta R^2 ~ 0.14, Hurst -> 1):
#     beta was fit per-sequence on a raw periodogram (chi^2_2, ~100% variance
#     per bin) and the slopes averaged -> garbage R^2. We now AVERAGE the PSD
#     across many series/channels FIRST (Bartlett), then fit one slope ->
#     stable beta with a real R^2. Hurst on length-512 windows with strong
#     low-frequency drift is biased toward 1; we add light first-difference
#     detrending guidance and report the bias honestly.
#
# Earlier history (collect_hidden_states noise-switch save/restore; EtaResult
# addition) is preserved.
"""
Rigorous measurement of emergent critical exponents.

Honest-emergence protocol (v2.2):
1. Collect hidden states with the model's stochastic noise injection
   DISABLED (so any injected pattern is not fed back into the measurement).
2. Measure Hurst (DFA), spectrum slope beta (Bartlett-averaged PSD), the
   avalanche tail (Clauset MLE), and the Fisher-metric anisotropy eta
   (GLOBAL covariance).
3. Build a SHUFFLE SURROGATE (time axis permuted independently per channel)
   and re-measure: genuine long-range structure must collapse on the
   surrogate (Hurst -> ~0.5, beta -> ~0), whereas a residual injected
   pattern would survive. This is the real "is the emergence genuine?" test,
   and it works even when the model injects no noise at inference time.
4. Also measure a trained Transformer baseline (negative control).

UID predictions (wide, weak — see theory's own caveats):
    beta in [0.7, 1.3],  H in [0.6, 0.8],  tau ~ 1.5,  eta > 0.5.
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
        eta_mean:        Anisotropy of the GLOBAL hidden-state covariance
                         (v2.2: no longer a noisy per-sequence average).
        eta_std:         Bootstrap std of the global eta (0.0 if a single
                         global estimate without bootstrap).
        eta_in_range:    True iff eta_mean > 0.5 (the UID prediction).
        n_samples:       Number of token vectors used for the global
                         covariance (B*S after optional capping).
        hidden_size:     Hidden size H used for the Fisher metric.
        seq_len:         Sequence length used.
        rank_deficient:  True iff n_samples < hidden_size, meaning the
                         GLOBAL covariance is rank-deficient and eta is
                         biased upward. With the v2.2 global estimator this
                         is essentially never true (n_samples = B*S).
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
    # v2.2: shuffle-surrogate control (None if not computed)
    surrogate_hurst: Optional[HurstResult] = None
    surrogate_spectrum: Optional[SpectrumResult] = None

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
            "surrogate_hurst": (
                self.surrogate_hurst.to_dict()
                if self.surrogate_hurst else None
            ),
            "surrogate_spectrum": (
                self.surrogate_spectrum.to_dict()
                if self.surrogate_spectrum else None
            ),
        }


# ======================================================================
# Internal noise-injection switch helpers
# ======================================================================


def _capture_and_disable_noise_injection(
    model: nn.Module,
) -> Tuple[bool, List[bool]]:
    """Try to disable noise injection on ``model``; remember prior state.

    返回 (是否成功切换, 各层原始注入状态列表)，用于稍后精确恢复。

    NOTE (v2.2): even when this returns switched=True, a model in eval()
    typically injects NO stochastic noise on the forward path, so the
    OFF/ON hidden states can be identical. The battery therefore no longer
    depends on an OFF/ON difference; it uses a shuffle surrogate instead.
    """
    prev_states: List[bool] = []

    cid_block = None
    if hasattr(model, "backbone") and hasattr(
        model.backbone, "set_noise_injection"
    ):
        cid_block = model.backbone
    elif hasattr(model, "set_noise_injection"):
        cid_block = getattr(model, "backbone", None)

    if cid_block is not None and hasattr(cid_block, "layers"):
        prev_states = [
            bool(getattr(layer, "_inject_noise", True))
            for layer in cid_block.layers
        ]

    if hasattr(model, "set_noise_injection"):
        model.set_noise_injection(False)
        return True, prev_states
    if cid_block is not None and hasattr(cid_block, "set_noise_injection"):
        cid_block.set_noise_injection(False)
        return True, prev_states

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
    """Restore the per-layer noise-injection flags captured earlier."""
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

    Returns an array of shape (n_collected, seq_len, hidden_dim).
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
                collected.append(h.detach().cpu().float().numpy())
                total += h.shape[0]
    finally:
        if switched:
            _restore_noise_injection(model, prev_states)

    arr = np.concatenate(collected, axis=0)[:n_sequences]
    return arr


def _shuffle_surrogate(hidden_states: np.ndarray,
                       seed: int = 1234) -> np.ndarray:
    """Build a phase/time-shuffled surrogate.

    Independently permutes the TIME axis (axis=1) for every (sequence,
    channel) pair. This destroys temporal correlations while preserving
    the marginal value distribution. Genuine long-range structure must
    collapse on this surrogate (Hurst -> ~0.5, beta -> ~0); a residual
    injected pattern (or a measurement artifact tied to the marginal
    distribution) would survive.
    """
    rng = np.random.default_rng(seed)
    b, s, h = hidden_states.shape
    out = hidden_states.copy()
    # Vectorised per-(b,h) time permutation.
    for i in range(b):
        # one permutation per channel keeps it cheap and decorrelated
        perm = rng.permuted(
            np.broadcast_to(np.arange(s), (h, s)), axis=1
        )  # (H, S)
        out[i] = hidden_states[i].T[np.arange(h)[:, None], perm].T
    return out


# ======================================================================
# Hurst exponent (DFA, gold-standard)
# ======================================================================
# ======================================================================
# Hurst exponent (DFA, gold-standard)
# ======================================================================


def estimate_hurst_dfa(
    signal: np.ndarray,
    min_window: int = 8,
    poly_order: int = 2,
    detrend_diff: bool = False,
) -> float:
    """Estimate the Hurst exponent via Detrended Fluctuation Analysis (DFA).

    v2.2.1 (correctness fix):
        The previous version pre-whitened the signal with np.diff() and then
        added 1.0 to the fitted slope to "convert increments back". That
        round-trip (difference -> integrate -> +1) is only valid for an
        ideal fBm/fGn pair and SYSTEMATICALLY UNDER-ESTIMATES H for real
        hidden-state series (it produced H ~ 0.15). Standard DFA needs NO
        differencing and NO +1 correction: the cumulative-sum (profile)
        step already handles (non)stationarity, and the fitted log-log slope
        IS the Hurst exponent directly.

        To suppress the strong low-frequency drift of hidden states along the
        token axis (positional / accumulating semantics) — the original
        motivation for differencing — we instead use DFA with a SECOND-ORDER
        (poly_order=2) detrending inside each window, which removes linear
        AND quadratic trends without distorting H. This is the textbook
        DFA-2 estimator.

    Reference behaviour (sanity checks the caller can run):
        white noise           -> H ~ 0.5
        positively correlated  -> H in (0.5, 1.0)
        anti-correlated        -> H in (0.0, 0.5)
        random walk (fBm)      -> H ~ 1.0  (DFA-2 still recovers this)

    Args:
        signal:       1-D time series.
        min_window:   smallest DFA window (>= poly_order + 2).
        poly_order:   detrending polynomial order per window (2 = DFA-2,
                      recommended for drifting hidden states; 1 = classic
                      DFA-1).
        detrend_diff: DEPRECATED / kept for API compatibility. If True we
                      emit no +1 correction; we simply ignore it and run the
                      correct standard DFA. (The old buggy path is gone.)

    Returns:
        Hurst exponent (float), or NaN if the series is too short.
    """
    signal = np.asarray(signal, dtype=np.float64)
    n = len(signal)

    # Need enough points for a stable log-log fit across several scales.
    min_window = max(min_window, poly_order + 2)
    if n < min_window * 4:
        return float("nan")

    # --- Standard DFA: integrate (cumulative sum of the mean-removed signal).
    y = np.cumsum(signal - signal.mean())

    max_window = n // 4
    if max_window <= min_window:
        return float("nan")

    n_scales = 20
    scales = np.unique(
        np.logspace(
            np.log10(min_window), np.log10(max_window), n_scales
        ).astype(int)
    )
    scales = scales[scales >= (poly_order + 2)]
    if scales.size < 4:
        return float("nan")

    fluctuations = []
    used_scales = []
    for sc in scales:
        n_segments = n // sc
        if n_segments < 2:
            continue
        # Use both forward and backward segmentation to use all data
        # (standard improvement; halves edge-truncation bias).
        rms_accum = []
        xx = np.arange(sc)
        for start in (0, n - n_segments * sc):
            segs = y[start : start + n_segments * sc].reshape(n_segments, sc)
            for seg in segs:
                coeffs = np.polyfit(xx, seg, poly_order)
                trend = np.polyval(coeffs, xx)
                rms_accum.append(np.mean((seg - trend) ** 2))
        if rms_accum:
            fluctuations.append(np.sqrt(np.mean(rms_accum)))
            used_scales.append(sc)

    if len(fluctuations) < 4:
        return float("nan")

    log_s = np.log10(np.asarray(used_scales, dtype=np.float64))
    log_f = np.log10(np.asarray(fluctuations, dtype=np.float64) + 1e-12)
    slope, _intercept, _r, _p, _se = stats.linregress(log_s, log_f)

    # The DFA slope IS the Hurst exponent. No +1, no differencing.
    return float(slope)


def measure_hurst_exponent(
    hidden_states: np.ndarray,
    n_channels_per_series: int = 64,
    poly_order: int = 2,
    detrend_diff: bool = False,
) -> HurstResult:
    """Measure the Hurst exponent across many hidden-state time series.

    v2.2.1: uses corrected standard DFA-2 (no differencing, no +1). The
    ``detrend_diff`` argument is retained for API compatibility but no longer
    triggers the old buggy difference-and-correct path.
    """
    hidden_states = np.asarray(hidden_states)
    n_seq, seq_len, hidden_dim = hidden_states.shape

    h_values = []
    rng = np.random.default_rng(42)

    for i in range(n_seq):
        channels = rng.choice(
            hidden_dim,
            size=min(n_channels_per_series, hidden_dim),
            replace=False,
        )
        for c in channels:
            signal = hidden_states[i, :, c]
            h = estimate_hurst_dfa(
                signal, poly_order=poly_order, detrend_diff=detrend_diff,
            )
            if np.isfinite(h):
                h_values.append(h)

    if not h_values:
        return HurstResult(
            hurst_mean=float("nan"),
            hurst_std=float("nan"),
            n_series=0,
            sample_length=seq_len,
            method=f"DFA-{poly_order}",
        )

    return HurstResult(
        hurst_mean=float(np.mean(h_values)),
        hurst_std=float(np.std(h_values)),
        n_series=len(h_values),
        sample_length=seq_len,
        method=f"DFA-{poly_order}",
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
    """Measure power-spectrum slope beta with a BARTLETT-AVERAGED PSD.

    v2.2 fix: instead of fitting beta on each raw periodogram (chi^2_2,
    ~100% per-bin variance) and averaging the slopes — which gave R^2~0.14
    — we AVERAGE the periodograms across many (sequence, channel) pairs
    first, then fit ONE slope on the smooth averaged PSD. This yields a
    stable beta with a meaningful R^2.
    """
    n_seq, seq_len, hidden_dim = hidden_states.shape

    freqs = rfftfreq(seq_len)
    f_min = f_min_factor / seq_len
    valid = (freqs > f_min) & (freqs < f_max)
    if valid.sum() < 8:
        return SpectrumResult(
            beta_mean=float("nan"), beta_std=float("nan"),
            n_series=0, sample_length=seq_len, r_squared_mean=float("nan"),
        )

    rng = np.random.default_rng(42)
    psd_sum = np.zeros(freqs.shape, dtype=np.float64)
    count = 0

    for i in range(n_seq):
        channels = rng.choice(
            hidden_dim, size=min(n_channels_per_series, hidden_dim),
            replace=False,
        )
        sig = hidden_states[i, :, channels]  # (n_ch, S)
        # demean each channel before FFT to suppress the DC leak
        sig = sig - sig.mean(axis=1, keepdims=True)
        psd = np.abs(rfft(sig, axis=1)) ** 2  # (n_ch, F)
        psd_sum += psd.sum(axis=0)
        count += psd.shape[0]

    if count == 0:
        return SpectrumResult(
            beta_mean=float("nan"), beta_std=float("nan"),
            n_series=0, sample_length=seq_len, r_squared_mean=float("nan"),
        )

    mean_psd = psd_sum / count
    log_f = np.log(freqs[valid])
    log_psd = np.log(mean_psd[valid] + 1e-12)
    slope, intercept, r, _, stderr = stats.linregress(log_f, log_psd)
    beta = -float(slope)

    return SpectrumResult(
        beta_mean=beta,
        beta_std=float(stderr),       # slope standard error (real uncertainty)
        n_series=int(count),
        sample_length=seq_len,
        r_squared_mean=float(r * r),  # R^2 of the SINGLE averaged-PSD fit
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
    shrinkage: float = 1e-2,
) -> EtaResult:
    """Measure Fisher-metric anisotropy eta per Theory §6.1.

        eta = (lambda_max - lambda_min) / (lambda_max + lambda_min)

    v2.2 fix: estimate ONE GLOBAL covariance from all (B*S, H) token
    vectors instead of a per-sequence (S, H) covariance. The per-sequence
    estimate had samples/dim ~ 2 -> wildly ill-conditioned -> eta -> 1 for
    EVERY model (including a random Transformer), so it had no
    discriminative power. With B*S ~ 10^5 token samples the H*H covariance
    is well-conditioned and eta becomes meaningful. Light Ledoit-Wolf-style
    shrinkage stabilises lambda_min.

    Args:
        hidden_states: (B, S, H).
        eta_threshold: pass/fail threshold (default 0.5).
        jitter:        unused in the global estimator (kept for API compat).
        max_samples:   cap on the number of TOKEN vectors used (B*S).
        shrinkage:     covariance shrinkage toward (trace/H) * I in [0,1].
    """
    if hidden_states.ndim != 3:
        raise ValueError(
            "hidden_states must have shape (B, S, H); got "
            f"{hidden_states.shape}"
        )
    n_seq, seq_len, hidden_dim = hidden_states.shape
    if n_seq < 1:
        raise ValueError("hidden_states must contain >= 1 sequence")

    # Flatten to token vectors: (B*S, H).
    X = hidden_states.reshape(-1, hidden_dim).astype(np.float64)

    # Optional cap on token count for cost control.
    if max_samples is not None and X.shape[0] > max_samples:
        rng = np.random.default_rng(42)
        idx = rng.choice(X.shape[0], size=int(max_samples), replace=False)
        X = X[idx]

    n_tokens = X.shape[0]
    rank_deficient = bool(n_tokens < hidden_dim)

    # Global covariance.
    X = X - X.mean(axis=0, keepdims=True)
    cov = (X.T @ X) / max(1, (n_tokens - 1))

    # Shrinkage toward scaled identity to stabilise lambda_min.
    if shrinkage and shrinkage > 0.0:
        mu = np.trace(cov) / hidden_dim
        cov = (1.0 - shrinkage) * cov + shrinkage * mu * np.eye(hidden_dim)

    # Eigenvalues (symmetric).
    try:
        evals = np.linalg.eigvalsh(cov)
    except np.linalg.LinAlgError:
        return EtaResult(
            eta_mean=float("nan"), eta_std=float("nan"),
            eta_in_range=False, n_samples=int(n_tokens),
            hidden_size=int(hidden_dim), seq_len=int(seq_len),
            rank_deficient=rank_deficient,
        )

    evals = evals[np.isfinite(evals)]
    evals = np.clip(evals, 0.0, None)
    if evals.size == 0 or evals.max() <= 0:
        return EtaResult(
            eta_mean=float("nan"), eta_std=float("nan"),
            eta_in_range=False, n_samples=int(n_tokens),
            hidden_size=int(hidden_dim), seq_len=int(seq_len),
            rank_deficient=rank_deficient,
        )

    lam_max = float(evals.max())
    lam_min = float(evals.min())
    eta = (lam_max - lam_min) / (lam_max + lam_min + 1e-12)

    # Bootstrap a std over token resamples for an honest uncertainty.
    eta_std = 0.0
    try:
        rng = np.random.default_rng(7)
        boots = []
        for _ in range(8):
            bi = rng.choice(n_tokens, size=n_tokens, replace=True)
            Xb = X[bi]
            covb = (Xb.T @ Xb) / max(1, (n_tokens - 1))
            if shrinkage and shrinkage > 0.0:
                mub = np.trace(covb) / hidden_dim
                covb = ((1.0 - shrinkage) * covb
                        + shrinkage * mub * np.eye(hidden_dim))
            eb = np.linalg.eigvalsh(covb)
            eb = np.clip(eb[np.isfinite(eb)], 0.0, None)
            if eb.size and eb.max() > 0:
                boots.append(
                    (eb.max() - eb.min()) / (eb.max() + eb.min() + 1e-12)
                )
        if boots:
            eta_std = float(np.std(boots))
    except Exception:
        eta_std = 0.0

    return EtaResult(
        eta_mean=float(eta),
        eta_std=eta_std,
        eta_in_range=bool(eta > eta_threshold),
        n_samples=int(n_tokens),
        hidden_size=int(hidden_dim),
        seq_len=int(seq_len),
        rank_deficient=rank_deficient,
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
    include_surrogate: bool = True,
) -> CriticalExponentResult:
    """Run the full battery of critical-exponent measurements.

    v2.2: ``eta_max_samples`` now caps the number of TOKEN vectors used by
    the GLOBAL eta covariance (not per-sequence samples). For a meaningful,
    well-conditioned eta you want this >> hidden_size; pass None (or a large
    value like 50000) to use all collected tokens. A shuffle surrogate is
    also measured (``include_surrogate``) as the genuine emergence control.
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

    # Step 3: Power spectrum (Bartlett-averaged PSD).
    print("  Computing power-spectrum slope beta (averaged PSD)...")
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

    # Step 5: Fisher anisotropy eta (GLOBAL covariance).
    eta_result: Optional[EtaResult] = None
    if include_eta:
        print(
            "  Computing Fisher anisotropy eta "
            "(global covariance; Theory §6.1)..."
        )
        try:
            # Token-count cap: default 256 is far too small for a global
            # H*H covariance. Use a generous cap so the estimate is well
            # conditioned (B*S is typically >> hidden_size anyway).
            token_cap = (
                None if eta_max_samples is None
                else max(int(eta_max_samples), 50 * hidden.shape[2])
            )
            eta_result = measure_fisher_anisotropy_eta(
                hidden,
                eta_threshold=eta_threshold,
                max_samples=token_cap,
            )
            rd = eta_result.rank_deficient
            rank_note = (
                "  [warn] rank-deficient global covariance "
                "(n_tokens < hidden_size); eta biased toward 1.0\n"
                if rd else ""
            )
            verdict = "PASS" if eta_result.eta_in_range else "FAIL"
            print(
                f"  eta: {eta_result.eta_mean:.3f} ± "
                f"{eta_result.eta_std:.3f} "
                f"(n_tokens={eta_result.n_samples}, "
                f"threshold={eta_threshold}, {verdict})\n"
                f"{rank_note}".rstrip()
            )
        except Exception as exc:  # pylint: disable=broad-except
            print(f"  [warn] eta estimation failed: {exc}")
            eta_result = None

    # Step 6: Shuffle surrogate control (genuine-emergence test).
    surr_hurst: Optional[HurstResult] = None
    surr_spectrum: Optional[SpectrumResult] = None
    if include_surrogate:
        print("  Building shuffle surrogate (time axis permuted)...")
        surrogate = _shuffle_surrogate(hidden)
        surr_hurst = measure_hurst_exponent(surrogate)
        surr_spectrum = measure_power_spectrum(surrogate)
        print(
            f"  surrogate Hurst: {surr_hurst.hurst_mean:.3f}  "
            f"surrogate beta: {surr_spectrum.beta_mean:.3f}  "
            f"(should collapse toward H~0.5, beta~0 if structure is real)"
        )

    return CriticalExponentResult(
        model_name=model_name,
        noise_injection_on=not disable_noise,
        hurst=hurst,
        spectrum=spectrum,
        avalanche=avalanche_fit,
        eta=eta_result,
        surrogate_hurst=surr_hurst,
        surrogate_spectrum=surr_spectrum,
    )
