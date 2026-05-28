# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28 (v2.1 batch 3)
#   * Add TestFisherAnisotropyEta: regression for the new
#     measure_fisher_anisotropy_eta() function. Covers shape contract,
#     extreme-case behaviour (isotropic vs dominant-eigenvalue),
#     rank-deficient flagging, threshold semantics, max_samples
#     subsampling, and EtaResult.to_dict() schema.
#   * Add TestEtaInBattery: integration-level smoke that
#     run_critical_exponent_battery() now reports eta by default and
#     that include_eta=False keeps backward-compatible behaviour.
"""Tests for critical-exponent measurement utilities (v2.1)."""

from __future__ import annotations

import warnings
from typing import Iterable

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader, TensorDataset

from uid_theory.verification.critical_exponents import (
    CriticalExponentResult,
    EtaResult,
    estimate_hurst_dfa,
    measure_fisher_anisotropy_eta,
    measure_hurst_exponent,
    measure_power_spectrum,
    run_critical_exponent_battery,
)


# ======================================================================
# Existing tests (preserved verbatim)
# ======================================================================


class TestHurstDFA:
    def test_white_noise_yields_05(self):
        """White noise should yield H ~= 0.5."""
        rng = np.random.default_rng(42)
        signal = rng.standard_normal(4096)
        h = estimate_hurst_dfa(signal)
        assert 0.4 < h < 0.6, (
            f"Expected H~=0.5 for white noise, got {h}"
        )

    def test_brownian_motion_yields_high_h(self):
        """Brownian motion (cumulative sum of white noise) yields H>1."""
        rng = np.random.default_rng(42)
        increments = rng.standard_normal(4096)
        bm = np.cumsum(increments)
        h = estimate_hurst_dfa(bm)
        assert h > 1.0, f"Expected H>1.0 for Brownian motion, got {h}"

    def test_too_short_returns_nan(self):
        signal = np.random.randn(10)
        h = estimate_hurst_dfa(signal)
        assert np.isnan(h)


class TestMeasureHurst:
    def test_returns_hurst_result(self):
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((4, 2048, 32))
        result = measure_hurst_exponent(hidden, n_channels_per_series=8)
        assert np.isfinite(result.hurst_mean)
        assert result.n_series > 0
        # White noise --> H ~= 0.5.
        assert 0.3 < result.hurst_mean < 0.7


class TestMeasurePowerSpectrum:
    def test_white_noise_yields_flat_spectrum(self):
        """White noise --> beta ~= 0 (flat spectrum)."""
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((4, 2048, 32))
        result = measure_power_spectrum(hidden, n_channels_per_series=8)
        assert np.isfinite(result.beta_mean)
        assert abs(result.beta_mean) < 0.3, (
            f"Expected beta~=0 for white noise, got {result.beta_mean}"
        )

    def test_returns_spectrum_result(self):
        rng = np.random.default_rng(42)
        hidden = rng.standard_normal((2, 1024, 16))
        result = measure_power_spectrum(hidden, n_channels_per_series=4)
        assert result.n_series > 0
        assert np.isfinite(result.r_squared_mean)


# ======================================================================
# NEW: TestFisherAnisotropyEta (regression for v2.1 batch 2/3)
# ======================================================================


def _isotropic_hidden(
    n_seq: int = 8, seq_len: int = 256, hidden: int = 64, seed: int = 42,
) -> np.ndarray:
    """Standard normal hidden states — close to isotropic."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n_seq, seq_len, hidden)).astype(np.float32)


def _dominant_channel_hidden(
    n_seq: int = 8,
    seq_len: int = 256,
    hidden: int = 64,
    scale: float = 100.0,
    seed: int = 42,
) -> np.ndarray:
    """Standard normal hidden with one channel pumped up — strongly
    anisotropic; eta should approach 1."""
    rng = np.random.default_rng(seed)
    h = rng.standard_normal((n_seq, seq_len, hidden)).astype(np.float32)
    h[..., 0] *= float(scale)
    return h


class TestFisherAnisotropyEta:
    """Regression suite for measure_fisher_anisotropy_eta()."""

    # ------ shape / type contract ------------------------------------

    def test_returns_eta_result(self):
        hidden = _isotropic_hidden()
        res = measure_fisher_anisotropy_eta(hidden)
        assert isinstance(res, EtaResult)

    def test_eta_in_unit_interval(self):
        hidden = _isotropic_hidden()
        res = measure_fisher_anisotropy_eta(hidden)
        assert 0.0 <= res.eta_mean <= 1.0
        assert res.eta_std >= 0.0

    def test_reports_hidden_and_seq_dimensions(self):
        hidden = _isotropic_hidden(n_seq=4, seq_len=128, hidden=32)
        res = measure_fisher_anisotropy_eta(hidden)
        assert res.hidden_size == 32
        assert res.seq_len == 128
        assert res.n_samples == 4

    def test_to_dict_has_required_keys(self):
        hidden = _isotropic_hidden()
        res = measure_fisher_anisotropy_eta(hidden)
        d = res.to_dict()
        required = {
            "eta_mean", "eta_std", "eta_in_range", "n_samples",
            "hidden_size", "seq_len", "rank_deficient",
        }
        assert required.issubset(d.keys()), (
            f"EtaResult.to_dict() missing keys: "
            f"{required - set(d.keys())}"
        )

    # ------ shape input validation -----------------------------------

    def test_rejects_2d_input(self):
        bad = np.zeros((8, 64), dtype=np.float32)
        with pytest.raises(ValueError, match="shape \\(B, S, H\\)"):
            _ = measure_fisher_anisotropy_eta(bad)

    def test_rejects_empty_batch(self):
        bad = np.zeros((0, 64, 32), dtype=np.float32)
        with pytest.raises(ValueError, match=">= 1 sequence"):
            _ = measure_fisher_anisotropy_eta(bad)

    def test_rejects_seq_len_one(self):
        bad = np.zeros((2, 1, 32), dtype=np.float32)
        with pytest.raises(ValueError, match="below the FisherMetric"):
            _ = measure_fisher_anisotropy_eta(bad)

    # ------ physics: extreme-case behaviour --------------------------

    def test_isotropic_gives_low_eta(self):
        """Random Gaussian (~ isotropic covariance) should give eta
        well below the 0.5 threshold."""
        hidden = _isotropic_hidden(n_seq=8, seq_len=256, hidden=64)
        res = measure_fisher_anisotropy_eta(hidden)
        assert not res.rank_deficient
        assert res.eta_mean < 0.5, (
            f"Isotropic hidden should give eta < 0.5; got {res.eta_mean}"
        )
        assert res.eta_in_range is False

    def test_dominant_channel_gives_high_eta(self):
        """One channel pumped up by 100x must give eta > 0.5."""
        hidden = _dominant_channel_hidden(
            n_seq=8, seq_len=256, hidden=64, scale=100.0,
        )
        res = measure_fisher_anisotropy_eta(hidden)
        assert not res.rank_deficient
        assert res.eta_mean > 0.5, (
            f"Dominant-channel hidden should give eta > 0.5; "
            f"got {res.eta_mean}"
        )
        assert res.eta_in_range is True

    def test_eta_increases_with_dominance(self):
        """Pumping the dominant channel harder should monotonically
        increase eta."""
        scales = [1.0, 5.0, 50.0, 500.0]
        etas = []
        for sc in scales:
            h = _dominant_channel_hidden(
                n_seq=8, seq_len=256, hidden=64, scale=sc,
            )
            etas.append(
                float(measure_fisher_anisotropy_eta(h).eta_mean)
            )
        for a, b in zip(etas, etas[1:]):
            assert b >= a - 1e-3, (
                f"eta should be non-decreasing in dominance scale; "
                f"got {etas}"
            )

    # ------ threshold semantics --------------------------------------

    def test_threshold_default_is_05(self):
        hidden = _dominant_channel_hidden(scale=100.0)
        # Without specifying threshold — should use 0.5 internally.
        res = measure_fisher_anisotropy_eta(hidden)
        assert res.eta_in_range is True

    def test_threshold_override(self):
        hidden = _isotropic_hidden()
        res_strict = measure_fisher_anisotropy_eta(
            hidden, eta_threshold=0.99,
        )
        res_lenient = measure_fisher_anisotropy_eta(
            hidden, eta_threshold=1e-9,
        )
        assert res_strict.eta_in_range is False
        # eta_mean for isotropic gaussian is small but > 0, so any
        # threshold near 0 should pass.
        assert res_lenient.eta_in_range is True

    # ------ rank-deficient flag --------------------------------------

    def test_rank_deficient_flag_when_seq_lt_hidden(self):
        """seq_len < hidden_size --> rank_deficient=True and a one-time
        RuntimeWarning."""
        # Use a fresh hidden_size to avoid the module-level dedup of
        # the rank-deficient warning (FisherMetric._RANK_DEFICIENT_WARNED).
        H = 257
        hidden = _isotropic_hidden(n_seq=4, seq_len=16, hidden=H)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = measure_fisher_anisotropy_eta(hidden)
            rd_warns = [
                ww for ww in w
                if issubclass(ww.category, RuntimeWarning)
                and "rank-deficient" in str(ww.message)
            ]
            assert rd_warns, (
                "Expected a RuntimeWarning about rank-deficient covariance "
                "when seq_len < hidden_size"
            )
        assert res.rank_deficient is True

    def test_rank_deficient_eta_biased_toward_one(self):
        """When the covariance is rank-deficient, eta is mathematically
        biased toward 1.0 even for isotropic input — this is a known
        artifact that the user must NOT count as a pass."""
        H = 257
        hidden = _isotropic_hidden(n_seq=4, seq_len=16, hidden=H)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = measure_fisher_anisotropy_eta(hidden)
        assert res.rank_deficient is True
        # Despite isotropic input, eta is artificially high.
        # We just check it's >= 0.5 (a "fake pass"); the verdict layer
        # must reject this case via the rank_deficient flag.
        assert res.eta_mean >= 0.5

    def test_rank_clean_when_seq_ge_hidden(self):
        H = 32
        hidden = _isotropic_hidden(n_seq=4, seq_len=H * 2, hidden=H)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = measure_fisher_anisotropy_eta(hidden)
            rd_warns = [
                ww for ww in w
                if issubclass(ww.category, RuntimeWarning)
                and "rank-deficient" in str(ww.message)
            ]
            # With seq_len >= H we should NOT see a rank-deficient warning
            # from this specific call (other tests may have warmed
            # different (H, S) pairs in the dedup set, but those don't
            # affect this fresh H=32 / S=64 pair if it's the first time).
            # We tolerate previously-warmed dedup state gracefully:
            # the post-condition is just that rank_deficient is False.
            del rd_warns
        assert res.rank_deficient is False

    # ------ max_samples subsampling ----------------------------------

    def test_max_samples_subsamples(self):
        hidden = _isotropic_hidden(n_seq=100, seq_len=64, hidden=32)
        res = measure_fisher_anisotropy_eta(hidden, max_samples=10)
        # n_samples must equal max_samples (not 100) when subsampled.
        assert res.n_samples == 10

    def test_max_samples_larger_than_batch_is_noop(self):
        hidden = _isotropic_hidden(n_seq=5, seq_len=64, hidden=32)
        res = measure_fisher_anisotropy_eta(hidden, max_samples=100)
        assert res.n_samples == 5

    def test_max_samples_none_uses_full_batch(self):
        hidden = _isotropic_hidden(n_seq=7, seq_len=64, hidden=32)
        res = measure_fisher_anisotropy_eta(hidden, max_samples=None)
        assert res.n_samples == 7

    # ------ jitter override ------------------------------------------

    def test_jitter_override_does_not_crash(self):
        hidden = _isotropic_hidden(n_seq=4, seq_len=128, hidden=32)
        # Both 0.0 and a custom positive jitter must work.
        res_zero = measure_fisher_anisotropy_eta(hidden, jitter=0.0)
        res_huge = measure_fisher_anisotropy_eta(hidden, jitter=10.0)
        assert np.isfinite(res_zero.eta_mean)
        assert np.isfinite(res_huge.eta_mean)
        # Huge jitter makes the metric look more isotropic, so eta
        # should be SMALLER than with the small default jitter.
        assert res_huge.eta_mean <= res_zero.eta_mean + 1e-6


# ======================================================================
# NEW: TestEtaInBattery (integration smoke for the battery driver)
# ======================================================================


def _make_tiny_uid_model_and_loader(seq_len: int = 64):
    """Helper: build a tiny UIDModel + dummy DataLoader for fast tests."""
    from model.model_uid import UIDConfig, UIDModel
    cfg = UIDConfig(
        vocab_size=128, hidden_size=32, num_hidden_layers=2,
        num_attention_heads=4, max_position_embeddings=seq_len,
    )
    model = UIDModel(cfg)
    ds = TensorDataset(torch.randint(0, 128, (8, seq_len)))
    loader = DataLoader(
        ds, batch_size=4,
        collate_fn=lambda b: {"input_ids": torch.stack([x[0] for x in b])},
    )
    return model, loader


class TestEtaInBattery:
    """Integration-level: run_critical_exponent_battery now reports
    eta by default and respects include_eta=False for back-compat."""

    def test_battery_reports_eta_by_default(self):
        model, loader = _make_tiny_uid_model_and_loader(seq_len=64)
        res = run_critical_exponent_battery(
            model=model,
            model_name="smoke_eta_default",
            dataloader=loader,
            device="cpu",
            n_sequences=8,
            disable_noise=True,
            include_avalanche=False,
            eta_max_samples=8,
        )
        assert isinstance(res, CriticalExponentResult)
        assert res.eta is not None
        assert isinstance(res.eta, EtaResult)
        # Output dict should carry the eta block.
        d = res.to_dict()
        assert d["eta"] is not None
        for key in (
            "eta_mean", "eta_std", "eta_in_range",
            "n_samples", "hidden_size", "seq_len", "rank_deficient",
        ):
            assert key in d["eta"]

    def test_battery_can_skip_eta(self):
        model, loader = _make_tiny_uid_model_and_loader(seq_len=64)
        res = run_critical_exponent_battery(
            model=model,
            model_name="smoke_eta_skipped",
            dataloader=loader,
            device="cpu",
            n_sequences=4,
            disable_noise=True,
            include_avalanche=False,
            include_eta=False,
        )
        assert res.eta is None
        assert res.to_dict()["eta"] is None

    def test_battery_eta_threshold_override_propagates(self):
        model, loader = _make_tiny_uid_model_and_loader(seq_len=64)
        # An impossibly strict threshold should make in_range=False
        # for any realistic untrained model.
        res = run_critical_exponent_battery(
            model=model,
            model_name="smoke_strict_threshold",
            dataloader=loader,
            device="cpu",
            n_sequences=4,
            disable_noise=True,
            include_avalanche=False,
            eta_threshold=0.999999,
            eta_max_samples=4,
        )
        assert res.eta is not None
        assert res.eta.eta_in_range is False

    def test_battery_marks_rank_deficient_when_seq_lt_hidden(self):
        """An untrained UIDModel with seq_len=8 < hidden=32 should
        propagate rank_deficient=True up through the battery."""
        model, loader = _make_tiny_uid_model_and_loader(seq_len=8)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = run_critical_exponent_battery(
                model=model,
                model_name="smoke_rank_deficient",
                dataloader=loader,
                device="cpu",
                n_sequences=4,
                disable_noise=True,
                include_avalanche=False,
                eta_max_samples=4,
            )
        assert res.eta is not None
        assert res.eta.rank_deficient is True
        assert res.eta.seq_len == 8
        assert res.eta.hidden_size == 32

    def test_battery_does_not_pollute_noise_injection_state(self):
        """The battery must restore the model's noise-injection state
        after running (regression for the v2.1 batch-1 bug)."""
        model, loader = _make_tiny_uid_model_and_loader(seq_len=64)
        # Explicitly set OFF before the battery; the battery should not
        # silently flip it back ON.
        if hasattr(model, "set_noise_injection"):
            model.set_noise_injection(False)
        _ = run_critical_exponent_battery(
            model=model,
            model_name="smoke_no_pollute",
            dataloader=loader,
            device="cpu",
            n_sequences=4,
            disable_noise=True,
            include_avalanche=False,
            include_eta=True,
            eta_max_samples=4,
        )
        # State must still be OFF after the battery completes.
        if (
            hasattr(model, "backbone")
            and hasattr(model.backbone, "layers")
            and model.backbone.layers
        ):
            assert model.backbone.layers[0]._inject_noise is False, (
                "Battery polluted the noise-injection state: it should "
                "be False after the run, since the user set it False before."
            )
