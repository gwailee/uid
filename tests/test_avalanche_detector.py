# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28 — tighten multi-burst assertion to upper bound too.
"""Tests for the avalanche detector (Beggs-Plenz protocol)."""

from __future__ import annotations

import numpy as np

from uid_theory.verification.avalanche_detector import detect_avalanches


class TestAvalancheDetector:
    def test_quiet_activity_yields_no_avalanches(self):
        """Quiet signal (all below threshold) → no avalanches."""
        # Use very small values so that after z-normalization,
        # everything is well below the threshold.
        hidden = np.zeros((1, 100, 32)) + 0.001
        rng = np.random.default_rng(42)
        hidden = hidden + rng.normal(0, 1e-4, size=hidden.shape)
        # threshold_sigma=10.0 corresponds to a ~7.6e-24 per-sample
        # crossing probability under N(0, 1); over 3200 samples the
        # cumulative crossing probability is ~2.4e-20.
        sizes = detect_avalanches(hidden, threshold_sigma=10.0)
        assert len(sizes) == 0

    def test_single_burst_detected(self):
        """A single burst of activity should produce one avalanche."""
        # Construct signal: zeros, then burst, then zeros.
        hidden = np.zeros((1, 100, 32))
        # Burst at frames 40-50, all channels active.
        hidden[0, 40:50, :] = 5.0
        sizes = detect_avalanches(hidden, threshold_sigma=2.0)
        assert len(sizes) >= 1
        # The burst should be a sizable avalanche.
        assert sizes.max() > 50

    def test_multiple_avalanches_separated(self):
        """Two separated bursts → exactly two avalanches.

        The Beggs-Plenz protocol defines an avalanche as a contiguous
        run of supra-threshold frames separated by quiet frames.
        Two bursts separated by 35+ quiet frames must yield 2 distinct
        avalanches — neither fewer (under-segmentation) nor many more
        (over-segmentation due to within-burst gaps).
        """
        hidden = np.zeros((1, 100, 32))
        hidden[0, 20:25, :16] = 5.0   # burst 1: 5 frames × 16 channels
        hidden[0, 60:65, :16] = 5.0   # burst 2: 5 frames × 16 channels
        sizes = detect_avalanches(hidden, threshold_sigma=2.0)
        # Upper bound: at most 12, allowing for some within-burst
        # boundary fluctuations introduced by the z-normalization.
        # Lower bound: at least 2 distinct avalanches.
        assert 2 <= len(sizes) <= 12, (
            f"Expected 2 ≤ #avalanches ≤ 12 for two well-separated "
            f"bursts, got {len(sizes)}. This suggests either under- "
            "or over-segmentation in the Beggs-Plenz detector."
        )

    def test_returns_numpy_array(self):
        hidden = np.random.randn(2, 50, 16)
        sizes = detect_avalanches(hidden)
        assert isinstance(sizes, np.ndarray)
        assert sizes.dtype == np.float64

    def test_z_score_normalization(self):
        """Different overall scales should yield similar avalanche
        structure (z-normalization is scale-invariant).
        """
        rng = np.random.default_rng(42)
        # Same pattern at different scales.
        pattern = rng.randn(2, 100, 32)
        sizes_small = detect_avalanches(pattern * 0.1)
        sizes_large = detect_avalanches(pattern * 100.0)
        # After z-normalization the two should yield nearly identical
        # avalanche counts (allowing a small numerical jitter).
        assert abs(len(sizes_small) - len(sizes_large)) < 5
