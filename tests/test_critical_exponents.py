# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""Tests for critical-exponent measurement utilities."""

from __future__ import annotations

import numpy as np
import pytest

from uid_theory.verification.critical_exponents import (
    estimate_hurst_dfa,
    measure_hurst_exponent,
    measure_power_spectrum,
)


class TestHurstDFA:
    def test_white_noise_yields_05(self):
        """White noise should yield H ≈ 0.5."""
        rng = np.random.default_rng(42)
        # Need long enough signal
        signal = rng.standard_normal(4096)
        h = estimate_hurst_dfa(signal)
        assert 0.4 < h < 0.6, f"Expected H≈0.5 for white noise, got {h}"

    def test_brownian_motion_yields_high_h(self):
        """Brownian motion (cumulative sum of white noise) should yield H ≈ 1.5 → DFA: 1.5."""
        rng = np.random.default_rng(42)
        increments = rng.standard_normal(4096)
        bm = np.cumsum(increments)
        h = estimate_hurst_dfa(bm)
        # Brownian motion: DFA H ≈ 1.5
        assert h > 1.0, f"Expected H>1.0 for Brownian motion, got {h}"

    def test_too_short_returns_nan(self):
        signal = np.random.randn(10)
        h = estimate_hurst_dfa(signal)
        assert np.isnan(h)


class TestMeasureHurst:
    def test_returns_hurst_result(self):
        """Should return a populated HurstResult."""
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((4, 2048, 32))
        result = measure_hurst_exponent(hidden, n_channels_per_series=8)
        assert np.isfinite(result.hurst_mean)
        assert result.n_series > 0
        # White noise → H ≈ 0.5
        assert 0.3 < result.hurst_mean < 0.7


class TestMeasurePowerSpectrum:
    def test_white_noise_yields_flat_spectrum(self):
        """White noise → β ≈ 0 (flat spectrum)."""
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((4, 2048, 32))
        result = measure_power_spectrum(hidden, n_channels_per_series=8)
        assert np.isfinite(result.beta_mean)
        # White noise: β ≈ 0
        assert abs(result.beta_mean) < 0.3, \
            f"Expected β≈0 for white noise, got {result.beta_mean}"

    def test_returns_spectrum_result(self):
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((2, 1024, 16))
        result = measure_power_spectrum(hidden, n_channels_per_series=4)
        assert result.n_series > 0
        assert np.isfinite(result.r_squared_mean)
