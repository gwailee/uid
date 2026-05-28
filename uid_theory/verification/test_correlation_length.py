# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Regression tests for measure_correlation_length() (Theory §11.1).

Covers:
  §A — KSG and histogram MI estimators on known ground truth:
       independent Gaussians give MI ≈ 0; correlated Gaussians give
       MI matching the analytic formula.

  §B — _xi_for_channel known-shape ground truth:
       * White Gaussian noise → xi = 1
       * OU process with timescale tau → xi ≈ tau
       * Brownian motion → xi clipped at k_max (slow decay)

  §C — measure_correlation_length end-to-end:
       * Argument validation (shape, hyperparams, empty input).
       * Median aggregation across (layer, channel).
       * seq_len_too_short flag fires when k_max is hit.
       * Threshold override changes xi monotonically.

  §D — aggregate_correlation_length:
       * Aggregates per-sequence medians correctly.
       * Carries forward the warning when any sequence was clipped.

  §E — Fractional Brownian motion ground truth:
       * For fBm with Hurst exponent H, xi grows as a known function
         of T (precisely: xi increases with H at fixed T, and grows
         with T at fixed H ≥ 0.5). We verify the qualitative trend
         on synthetic fBm.

  §F — Robustness:
       * Constant signal → xi = 1, no crash.
       * Heavy-tailed signal → MI estimate stays finite.
       * Very short sequence raises the documented ValueError.

Run with::

    pytest tests/test_correlation_length.py -v
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from uid_theory.verification.correlation_length import (
    CorrelationLengthResult,
    _mi_histogram,
    _mi_ksg,
    _xi_for_channel,
    aggregate_correlation_length,
    measure_correlation_length,
)


# ======================================================================
# Synthetic-signal helpers
# ======================================================================


def _white_noise(seq_len: int, hidden: int, *, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((seq_len, hidden)).astype(np.float64)


def _ou_process(
    seq_len: int, hidden: int, tau: float, *, seed: int = 0,
) -> np.ndarray:
    """Simulate an OU process with correlation time tau, unit variance.

    Discrete update:  x[t+1] = decay * x[t] + sqrt(1 - decay^2) * eps,
    where decay = exp(-1/tau).
    """
    rng = np.random.default_rng(seed)
    decay = math.exp(-1.0 / tau)
    kick_scale = math.sqrt(max(1.0 - decay * decay, 0.0))
    state = rng.standard_normal((hidden,))
    out = np.empty((seq_len, hidden))
    for t in range(seq_len):
        kick = rng.standard_normal((hidden,))
        state = decay * state + kick_scale * kick
        out[t] = state
    return out


def _brownian_motion(
    seq_len: int, hidden: int, *, seed: int = 0,
) -> np.ndarray:
    """Standard Brownian motion: cumulative sum of Gaussian increments."""
    rng = np.random.default_rng(seed)
    increments = rng.standard_normal((seq_len, hidden))
    return np.cumsum(increments, axis=0)


def _fbm_via_circulant(
    seq_len: int, hidden: int, hurst: float, *, seed: int = 0,
) -> np.ndarray:
    """Simulate fractional Brownian motion via the Davies-Harte
    circulant embedding.

    Reference:
        Davies, R. B. and Harte, D. S. (1987).
        "Tests for Hurst effect." Biometrika 74, 95-101.

    The implementation here is a faithful but compact version that
    suffices for tests; it is NOT optimised for very long sequences.
    """
    if not (0.0 < hurst < 1.0):
        raise ValueError(f"hurst must be in (0, 1); got {hurst}")
    rng = np.random.default_rng(seed)
    n = seq_len
    # Autocovariance of fGn (fractional Gaussian noise).
    k = np.arange(n)
    g = 0.5 * (
        np.abs(k - 1) ** (2 * hurst)
        - 2 * np.abs(k) ** (2 * hurst)
        + np.abs(k + 1) ** (2 * hurst)
    )
    # Build the circulant first row r of length 2n.
    r = np.concatenate([g, [0.0], g[1:][::-1]])
    # Eigenvalues of the circulant matrix via FFT.
    lam = np.fft.fft(r).real
    # Some eigenvalues may be slightly negative due to truncation; clip.
    lam = np.clip(lam, 0.0, None)

    out = np.empty((n, hidden))
    for j in range(hidden):
        # Generate complex normal Z and modulate by sqrt(lam).
        z = rng.standard_normal(2 * n) + 1j * rng.standard_normal(2 * n)
        w = np.fft.ifft(np.sqrt(lam) * z) * np.sqrt(2 * n)
        # Take real and imaginary parts as two independent fGn samples;
        # we only keep the real part here.
        fgn = w[:n].real
        # Cumulative sum gives fBm.
        out[:, j] = np.cumsum(fgn)
    return out


# ======================================================================
# §A — MI estimators on known ground truth
# ======================================================================


class TestMIEstimators:
    def test_ksg_independent_gaussians_near_zero(self):
        rng = np.random.default_rng(0)
        x = rng.standard_normal(2000)
        y = rng.standard_normal(2000)
        mi = _mi_ksg(x, y, k=4)
        # KSG can return slightly negative finite-sample bias.
        assert abs(mi) < 0.05, f"Independent Gaussians: MI = {mi}"

    def test_ksg_correlated_gaussians_match_formula(self):
        """For (X, Y) jointly Gaussian with correlation rho, the
        analytic MI is -0.5 * log(1 - rho^2)."""
        rng = np.random.default_rng(0)
        rho = 0.7
        n = 4000
        z = rng.standard_normal(n)
        x = z
        y = rho * z + math.sqrt(1.0 - rho ** 2) * rng.standard_normal(n)
        mi_true = -0.5 * math.log(1.0 - rho ** 2)
        mi_est = _mi_ksg(x, y, k=4)
        assert abs(mi_est - mi_true) < 0.10, (
            f"KSG MI = {mi_est:.3f}, true = {mi_true:.3f}"
        )

    def test_histogram_independent_near_zero(self):
        rng = np.random.default_rng(0)
        x = rng.standard_normal(2000)
        y = rng.standard_normal(2000)
        mi = _mi_histogram(x, y, n_bins=12)
        # Histogram MI is non-negative by construction; allow a small
        # plug-in bias.
        assert 0.0 <= mi < 0.15, f"Histogram MI = {mi}"

    def test_histogram_correlated_positive(self):
        rng = np.random.default_rng(0)
        z = rng.standard_normal(3000)
        x = z
        y = 0.8 * z + 0.6 * rng.standard_normal(3000)
        mi = _mi_histogram(x, y, n_bins=16)
        assert mi > 0.10, f"Strongly correlated MI is too small: {mi}"


# ======================================================================
# §B — _xi_for_channel ground truth
# ======================================================================


class TestPerChannelXi:
    def test_white_noise_gives_xi_one(self):
        """White Gaussian noise has no time correlation; xi must be 1."""
        rng = np.random.default_rng(0)
        sig = rng.standard_normal(2000)
        xi, clipped = _xi_for_channel(
            sig, threshold_fraction=1.0 / math.e,
            mi_estimator="ksg", ksg_k=4, n_bins=16, k_max=200,
        )
        assert xi == 1, f"White noise gave xi = {xi}, expected 1"
        assert clipped is False

    def test_ou_process_xi_close_to_tau(self):
        """OU process with timescale tau should give xi ~= tau under
        the 1/e threshold (this is exactly how tau is defined for OU).
        """
        for tau in (5.0, 15.0, 30.0):
            sig = _ou_process(seq_len=4000, hidden=1, tau=tau, seed=42)[:, 0]
            xi, clipped = _xi_for_channel(
                sig, threshold_fraction=1.0 / math.e,
                mi_estimator="ksg", ksg_k=4, n_bins=16, k_max=400,
            )
            # MI for OU drops below 1/e at lag k where the
            # autocorrelation drops below 1/e — but MI for Gaussian
            # with rho = exp(-k/tau) is -0.5 * log(1 - rho^2). The
            # crossover is not exactly at k = tau but is monotonically
            # close. We allow generous tolerance.
            assert 0.5 * tau <= xi <= 2.5 * tau, (
                f"OU xi = {xi}, expected approx tau = {tau}"
            )
            assert clipped is False

    def test_brownian_motion_gets_clipped(self):
        """Brownian motion has 1/f^2 spectrum (very long memory);
        within a finite k_max, xi search hits the upper bound."""
        sig = _brownian_motion(seq_len=600, hidden=1, seed=0)[:, 0]
        xi, clipped = _xi_for_channel(
            sig, threshold_fraction=1.0 / math.e,
            mi_estimator="ksg", ksg_k=4, n_bins=16, k_max=120,
        )
        assert clipped is True, (
            "Brownian motion within finite k_max should hit the "
            "search upper bound"
        )
        assert xi == 120

    def test_constant_signal_gives_xi_one(self):
        """Constant signal: zero variance, MI is degenerate; we
        return xi=1 to avoid downstream NaN."""
        sig = np.full(500, 3.14)
        xi, clipped = _xi_for_channel(
            sig, threshold_fraction=1.0 / math.e,
            mi_estimator="ksg", ksg_k=4, n_bins=16, k_max=50,
        )
        assert xi == 1
        # We do not assert on `clipped`; the implementation may flag
        # this case either way.


# ======================================================================
# §C — measure_correlation_length end-to-end
# ======================================================================


class TestMeasureXiEndToEnd:
    def test_returns_dataclass(self):
        layers = [_white_noise(800, 32, seed=i) for i in range(3)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=8,
        )
        assert isinstance(res, CorrelationLengthResult)
        assert res.n_layers == 3
        assert res.n_channels_per_layer == 8
        assert res.seq_len == 800

    def test_white_noise_xi_close_to_one(self):
        """Across all (layer, channel) pairs of white noise, the
        median xi must equal 1."""
        layers = [_white_noise(1000, 32, seed=i) for i in range(4)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=8, mi_estimator="ksg",
        )
        assert res.xi_median == 1.0
        assert res.seq_len_too_short is False
        assert res.n_clipped == 0

    def test_ou_process_xi_recovers_tau(self):
        tau = 12.0
        layers = [
            _ou_process(2000, 16, tau=tau, seed=i) for i in range(3)
        ]
        res = measure_correlation_length(
            layers, n_channels_per_layer=8,
        )
        # Median xi should be in a generous window around tau.
        assert 0.5 * tau <= res.xi_median <= 2.5 * tau, (
            f"OU xi_median = {res.xi_median}, expected around {tau}"
        )

    def test_clipped_flag_fires_with_small_k_max(self):
        """When k_max is too small for the OU memory, results should
        flag seq_len_too_short."""
        tau = 30.0
        layers = [_ou_process(500, 4, tau=tau, seed=0)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=4,
            k_max=5,  # deliberately too small
        )
        # MI may decay below 1/e quickly enough to NOT clip in some
        # channels; we only require AT LEAST one clip.
        assert res.n_clipped >= 1
        assert res.seq_len_too_short is True
        assert any("k_max" in note for note in res.notes)

    def test_threshold_override_monotone(self):
        """Smaller threshold = stricter requirement = larger xi.
        Larger threshold = lenient = smaller xi."""
        tau = 10.0
        layers = [_ou_process(2000, 8, tau=tau, seed=42)]
        res_strict = measure_correlation_length(
            layers, n_channels_per_layer=4, threshold=0.1,
        )
        res_lenient = measure_correlation_length(
            layers, n_channels_per_layer=4, threshold=0.5,
        )
        assert res_strict.xi_median >= res_lenient.xi_median, (
            f"strict xi = {res_strict.xi_median}, "
            f"lenient xi = {res_lenient.xi_median}"
        )

    def test_histogram_estimator_runs(self):
        layers = [_white_noise(1000, 16, seed=0)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=4,
            mi_estimator="histogram", n_bins=12,
        )
        assert res.xi_median == 1.0
        assert res.mi_estimator == "histogram"

    # ----- Argument validation ---------------------------------------

    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="empty"):
            measure_correlation_length([])

    def test_non_2d_layer_raises(self):
        bad = [np.zeros((100,))]
        with pytest.raises(ValueError, match="2-D array"):
            measure_correlation_length(bad)

    def test_inconsistent_seq_lens_raises(self):
        layers = [
            np.zeros((100, 16)),
            np.zeros((200, 16)),  # different seq_len
        ]
        with pytest.raises(ValueError, match="same seq_len"):
            measure_correlation_length(layers)

    def test_seq_len_too_short_raises(self):
        layers = [np.zeros((10, 16))]
        with pytest.raises(ValueError, match="seq_len must be"):
            measure_correlation_length(layers)

    def test_unknown_estimator_raises(self):
        layers = [_white_noise(500, 8, seed=0)]
        with pytest.raises(ValueError, match="mi_estimator"):
            measure_correlation_length(
                layers, mi_estimator="my_estimator",
            )

    def test_invalid_threshold_raises(self):
        layers = [_white_noise(500, 8, seed=0)]
        with pytest.raises(ValueError, match="threshold"):
            measure_correlation_length(layers, threshold=1.5)
        with pytest.raises(ValueError, match="threshold"):
            measure_correlation_length(layers, threshold=0.0)


# ======================================================================
# §D — Aggregation across multiple sequences
# ======================================================================


class TestAggregation:
    def test_aggregate_medians(self):
        """The aggregate xi_median should be the median of per-
        sequence medians."""
        results = []
        # Three artificial results with known medians.
        for med in (5.0, 10.0, 20.0):
            r = CorrelationLengthResult(
                xi_median=med,
                xi_mean=med,
                xi_std=0.0,
                xi_per_layer=[med],
                xi_per_channel=[med],
                n_layers=1,
                n_channels_per_layer=1,
                seq_len=100,
                threshold=1.0 / math.e,
                mi_estimator="ksg",
                ksg_k=4,
                seq_len_too_short=False,
                n_clipped=0,
            )
            results.append(r)
        agg = aggregate_correlation_length(results)
        assert agg.xi_median == 10.0  # median of [5, 10, 20]

    def test_aggregate_carries_clip_warning(self):
        rs = [
            CorrelationLengthResult(
                xi_median=5.0, xi_mean=5.0, xi_std=0.0,
                xi_per_layer=[], xi_per_channel=[5.0],
                n_layers=1, n_channels_per_layer=1, seq_len=100,
                threshold=1.0 / math.e, mi_estimator="ksg", ksg_k=4,
                seq_len_too_short=False, n_clipped=0,
            ),
            CorrelationLengthResult(
                xi_median=8.0, xi_mean=8.0, xi_std=0.0,
                xi_per_layer=[], xi_per_channel=[8.0],
                n_layers=1, n_channels_per_layer=1, seq_len=100,
                threshold=1.0 / math.e, mi_estimator="ksg", ksg_k=4,
                seq_len_too_short=True, n_clipped=2,
            ),
        ]
        agg = aggregate_correlation_length(rs)
        assert agg.seq_len_too_short is True
        assert agg.n_clipped == 2

    def test_aggregate_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            aggregate_correlation_length([])

    def test_aggregate_warns_on_mixed_estimators(self):
        rs = [
            CorrelationLengthResult(
                xi_median=5.0, xi_mean=5.0, xi_std=0.0,
                xi_per_layer=[], xi_per_channel=[5.0],
                n_layers=1, n_channels_per_layer=1, seq_len=100,
                threshold=1.0 / math.e, mi_estimator="ksg", ksg_k=4,
                seq_len_too_short=False, n_clipped=0,
            ),
            CorrelationLengthResult(
                xi_median=5.0, xi_mean=5.0, xi_std=0.0,
                xi_per_layer=[], xi_per_channel=[5.0],
                n_layers=1, n_channels_per_layer=1, seq_len=100,
                threshold=1.0 / math.e,
                mi_estimator="histogram",  # different
                ksg_k=4,
                seq_len_too_short=False, n_clipped=0,
            ),
        ]
        agg = aggregate_correlation_length(rs)
        assert any("different" in note for note in agg.notes)


# ======================================================================
# §E — Fractional Brownian motion ground truth
# ======================================================================


class TestFractionalBrownianMotion:
    """For fBm, xi grows with the Hurst exponent H. We verify the
    monotone trend rather than a precise value, because the exact xi
    of fBm under the 1/e MI threshold has no simple closed form."""

    @pytest.mark.parametrize("hurst,expected_band", [
        (0.3, (1, 50)),    # anti-persistent, short xi
        (0.5, (1, 80)),    # standard Brownian motion (degenerate fBm)
        (0.7, (5, 200)),   # persistent
        (0.9, (20, 500)),  # strongly persistent
    ])
    def test_fbm_xi_grows_with_hurst(self, hurst, expected_band):
        fbm = _fbm_via_circulant(
            seq_len=1500, hidden=4, hurst=hurst, seed=42,
        )
        res = measure_correlation_length(
            [fbm], n_channels_per_layer=4, k_max=300,
        )
        lo, hi = expected_band
        assert lo <= res.xi_median <= hi, (
            f"fBm xi for H={hurst} fell out of expected band "
            f"[{lo}, {hi}]: got xi = {res.xi_median}"
        )

    def test_fbm_monotone_in_hurst(self):
        """xi should be (weakly) monotonically increasing in H."""
        xis = []
        for hurst in (0.3, 0.5, 0.7, 0.9):
            fbm = _fbm_via_circulant(
                seq_len=1500, hidden=4, hurst=hurst, seed=7,
            )
            res = measure_correlation_length(
                [fbm], n_channels_per_layer=4, k_max=300,
            )
            xis.append(res.xi_median)
        # Each successive xi should not be much smaller than the one
        # before; allow a small tolerance for stochastic noise.
        for prev, curr in zip(xis, xis[1:]):
            assert curr >= prev * 0.6, (
                f"xi sequence not monotone enough: {xis}"
            )


# ======================================================================
# §F — Robustness
# ======================================================================


class TestRobustness:
    def test_constant_layer_does_not_crash(self):
        """One layer of constant signal must not crash measurement."""
        good = _white_noise(800, 16, seed=0)
        const = np.full((800, 16), 7.0)
        res = measure_correlation_length(
            [good, const], n_channels_per_layer=4,
        )
        # Constant layer's xis are all 1, good layer's xis are all 1
        # too (white noise); model-wide median is 1.
        assert res.xi_median == 1.0
        # And no NaNs / infs.
        assert all(math.isfinite(x) for x in res.xi_per_channel)

    def test_heavy_tailed_signal_finite_xi(self):
        """Cauchy-distributed signal still gives a finite xi."""
        rng = np.random.default_rng(0)
        cauchy = rng.standard_cauchy(size=(1000, 8))
        # Clip extreme outliers so KDTree distance computations stay
        # finite without changing the time-correlation structure.
        cauchy = np.clip(cauchy, -100.0, 100.0)
        res = measure_correlation_length(
            [cauchy], n_channels_per_layer=4,
        )
        assert math.isfinite(res.xi_median)
        # White-Cauchy noise at lag>=1 has independent samples, so
        # xi should still be very small.
        assert res.xi_median <= 5

    def test_one_channel_per_layer_runs(self):
        layers = [_white_noise(800, 1, seed=0) for _ in range(3)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=1,
        )
        assert res.xi_median == 1.0

    def test_to_dict_round_trip(self):
        layers = [_white_noise(500, 8, seed=0)]
        res = measure_correlation_length(
            layers, n_channels_per_layer=4,
        )
        d = res.to_dict()
        # Must contain every dataclass field.
        for key in (
            "xi_median", "xi_mean", "xi_std",
            "xi_per_layer", "xi_per_channel",
            "n_layers", "n_channels_per_layer", "seq_len",
            "threshold", "mi_estimator", "ksg_k",
            "seq_len_too_short", "n_clipped", "notes",
        ):
            assert key in d, f"to_dict missing {key}"
