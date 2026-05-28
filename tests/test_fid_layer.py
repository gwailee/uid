# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Unit tests for uid_theory/fid/fid_layer.py (v2.1).

Covers every issue raised in the fid/ review:

  §A — v2.1 toggle propagation:
       * FIDLayer must forward use_et_symmetric, noise_type, noise_tau,
         noise_beta, use_berry, hamiltonian_mode, lindblad_mode,
         quantum_noise_mode AND quantum_noise_tau /
         quantum_noise_init_temperature THREE LEVELS DEEP
         (FID -> QID -> CID).

  §B — info dict is JSON-safe (LOSS_PREFIX separation):
       * info entries returned to the caller must all be JSON-
         serialisable scalars.
       * extract_loss_tensors() must surface the autograd-bearing
         curvature loss while leaving info clean.

  §C — Theory §6.1 / §6.2 prediction surrogates:
       * compute_anisotropy_eta in [0, 1] with the predicted extreme-
         case behaviour (≈0 for isotropic, ≈1 for one-dominant-eig).
       * compute_ricci_scalar_surrogate returns finite values for
         well-conditioned PSD matrices.
       * compute_legacy_anisotropy preserved for back-compat.

  §D — Top-level switch API parity with CIDLayer / QIDLayer:
       * set_noise_injection, set_energy_monitoring, set_temperature
         all three levels through to the right destinations.

  §E — FisherMetric calibration & robustness:
       * MIN_SEQ_LEN guard raises on seq_len < 2.
       * Rank-deficient warning fires for seq_len < hidden_size.
       * jitter override works (0.0 returns raw cov; PSD preserved
         under default).
       * compute_true_fisher_diagonal returns a non-empty 1-D
         non-negative tensor on a tiny UIDModel.

  §F — Forward smoke + backward:
       * forward + backward yields finite grads on all live params.
       * curvature_weight > 0 actually adds a non-zero loss term.

Run with::

    pytest tests/test_fid_layer.py -v
"""

from __future__ import annotations

import json
import warnings
from typing import Any, Dict

import pytest
import torch
import torch.nn as nn

from uid_theory.cid.colored_noise import (
    FastColoredNoise,
    OrnsteinUhlenbeckNoise,
)
from uid_theory.fid.curvature import ScalarCurvatureProbe
from uid_theory.fid.fid_layer import (
    LOSS_PREFIX,
    FIDLayer,
    extract_loss_tensors,
)
from uid_theory.fid.fisher_metric import FisherMetric
from uid_theory.qid.qid_layer import QIDLayer


# ----------------------------------------------------------------------
# Tiny config for fast CPU tests.
# ----------------------------------------------------------------------
TINY_H = 64
TINY_HEADS = 4
TINY_B = 2
TINY_S = 32  # >= TINY_H is preferred to avoid the rank-deficient warning


@pytest.fixture(autouse=True)
def _deterministic_seeds():
    torch.manual_seed(0)


def _make_layer(**overrides) -> FIDLayer:
    """Build a TINY FIDLayer with sensible defaults."""
    kwargs = dict(
        hidden_size=TINY_H,
        num_heads=TINY_HEADS,
        dropout=0.0,                # keep things deterministic
        curvature_weight=0.0,       # no autograd in info by default
        quantum_noise_mode="fft",   # fast deterministic noise
    )
    kwargs.update(overrides)
    return FIDLayer(**kwargs)


# ======================================================================
# §A — v2.1 toggle propagation (three levels deep)
# ======================================================================


class TestV21TogglePropagation:
    """The v2.1 keys must reach the deepest CIDLayer through FID -> QID."""

    # ------ §8.5 ET symmetric ----------------------------------------

    def test_default_et_symmetric_true_at_cid_base(self):
        layer = _make_layer()
        assert layer.qid.cid_base.attn.use_et_symmetric is True, (
            "FID default did NOT propagate use_et_symmetric=True all "
            "the way down to the CID attention module."
        )

    def test_explicit_no_et_symmetric_propagates_three_levels(self):
        layer = _make_layer(use_et_symmetric=False)
        # FID -> QID
        assert hasattr(layer, "qid")
        # QID -> CID base
        assert layer.qid.cid_base.attn.use_et_symmetric is False, (
            "use_et_symmetric=False failed to propagate "
            "FID -> QID -> CID."
        )

    # ------ §14.2 OU/FFT noise ----------------------------------------

    def test_cid_side_noise_type_recorded_at_cid_base(self):
        layer = _make_layer(noise_type="fft", noise_beta=0.42)
        # CIDLayer remembers the requested noise_type even when its own
        # noise module is disabled (because QID injects its own).
        assert layer.qid.cid_base.noise_type == "fft"

    def test_quantum_noise_mode_default_is_ou(self):
        """v2.1 FID default for the QID quantum noise should be OU,
        aligned with the v2.1 CID-side default."""
        layer = FIDLayer(
            hidden_size=TINY_H,
            num_heads=TINY_HEADS,
            dropout=0.0,
        )
        assert layer.qid.quantum_noise_mode == "ou", (
            "FID v2.1 default for quantum_noise_mode should be 'ou' "
            "to mirror the v2.1 CID colored-noise default."
        )

    def test_quantum_noise_fft_mode_selectable(self):
        layer = _make_layer(quantum_noise_mode="fft")
        # QuantumColoredNoise stores its mode as a string attribute.
        assert layer.qid.quantum_noise.mode == "fft"

    def test_quantum_noise_init_temperature_propagates(self):
        layer = _make_layer(quantum_noise_init_temperature=7.5)
        assert layer.qid.quantum_noise.get_temperature() == pytest.approx(
            7.5, rel=1e-5
        )

    # ------ QID-level toggles -----------------------------------------

    def test_hamiltonian_mode_propagates(self):
        layer = _make_layer(hamiltonian_mode="dedicated")
        assert layer.qid.hamiltonian_mode == "dedicated"

    def test_lindblad_mode_propagates(self):
        layer = _make_layer(lindblad_mode="shared", num_lindblad_channels=3)
        assert layer.qid.lindblad_mode == "shared"
        assert layer.qid.num_lindblad_channels == 3

    def test_use_berry_propagates(self):
        layer_with = _make_layer(use_berry=True)
        layer_without = _make_layer(use_berry=False)
        assert layer_with.qid.berry is not None
        assert layer_without.qid.berry is None


# ======================================================================
# §B — info dict is JSON-safe; loss tensors via extract_loss_tensors()
# ======================================================================


def _is_json_safe(obj: Any) -> bool:
    """True iff json.dumps(obj) succeeds with default encoder."""
    try:
        json.dumps(obj)
    except (TypeError, ValueError):
        return False
    return True


class TestInfoIsJsonSafe:
    def test_info_json_safe_with_curvature_weight_zero(self):
        layer = _make_layer(curvature_weight=0.0)
        layer.train()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        assert _is_json_safe(info), (
            "info dict not JSON-safe with curvature_weight=0; "
            f"offending entries: { {k: type(v).__name__ for k, v in info.items() if not _is_json_safe(v)} }"
        )

    def test_info_json_safe_after_extracting_loss(self):
        """Even when curvature_weight > 0, info must become JSON-safe
        after extract_loss_tensors() has been called."""
        layer = _make_layer(curvature_weight=0.1)
        layer.train()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        # Before extraction: a loss tensor must be present.
        loss_keys = [k for k in info if k.startswith(LOSS_PREFIX)]
        assert loss_keys, (
            "When curvature_weight > 0, info should carry at least one "
            f"key with the LOSS_PREFIX ({LOSS_PREFIX!r}); got "
            f"{list(info.keys())}"
        )
        # After extraction: info must be entirely JSON-safe.
        losses = extract_loss_tensors(info)
        assert losses, "extract_loss_tensors returned an empty dict"
        assert _is_json_safe(info), (
            "info dict still NOT JSON-safe after extracting loss tensors"
        )

    def test_extract_loss_tensors_strips_prefix(self):
        layer = _make_layer(curvature_weight=0.1)
        layer.train()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        losses = extract_loss_tensors(info)
        # All returned keys must NOT carry the LOSS_PREFIX anymore.
        for k in losses:
            assert not k.startswith(LOSS_PREFIX), (
                f"extract_loss_tensors did not strip {LOSS_PREFIX!r} "
                f"from key {k!r}"
            )
        # Specifically, the 'curvature' key must be present.
        assert "curvature" in losses

    def test_curvature_loss_tensor_requires_grad(self):
        layer = _make_layer(curvature_weight=0.5)
        layer.train()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        losses = extract_loss_tensors(info)
        loss_t = losses["curvature"]
        assert isinstance(loss_t, torch.Tensor)
        assert loss_t.requires_grad, (
            "Extracted curvature loss tensor should require grad so "
            "that host model.backward() flows through it."
        )

    def test_curvature_loss_zero_when_weight_zero(self):
        layer = _make_layer(curvature_weight=0.0)
        layer.train()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        # No LOSS_PREFIX key should be present.
        assert not any(k.startswith(LOSS_PREFIX) for k in info), (
            "With curvature_weight=0, info must not carry any loss "
            "tensor under the LOSS_PREFIX key."
        )


# ======================================================================
# §C — Theory §6.1 / §6.2 prediction surrogates
# ======================================================================


class TestEtaSurrogate:
    def test_eta_in_unit_interval(self):
        probe = ScalarCurvatureProbe(hidden_size=TINY_H)
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        eta = probe.anisotropy_eta(x)
        assert eta.shape == (TINY_B,)
        assert torch.all(eta >= 0.0)
        assert torch.all(eta <= 1.0)

    def test_eta_is_zero_for_isotropic_metric(self):
        iso = torch.eye(TINY_H).unsqueeze(0)  # (1, H, H)
        eta = ScalarCurvatureProbe.compute_anisotropy_eta(iso)
        assert eta.item() == pytest.approx(0.0, abs=1e-6), (
            f"Perfectly isotropic metric should give eta == 0, got {eta.item()}"
        )

    def test_eta_close_to_one_for_dominant_eigenvalue(self):
        # One huge eigenvalue, the rest tiny: eta should approach 1.
        diag_vals = torch.tensor([1.0e6] + [1.0e-6] * (TINY_H - 1))
        aniso = torch.diag(diag_vals).unsqueeze(0)
        eta = ScalarCurvatureProbe.compute_anisotropy_eta(aniso)
        assert eta.item() > 0.99, (
            f"Strongly anisotropic metric should give eta ≈ 1, got "
            f"{eta.item():.6f}"
        )

    def test_eta_increases_with_anisotropy(self):
        """eta should monotonically increase as anisotropy grows."""
        ratios = [1.0, 10.0, 1000.0, 1.0e6]
        etas = []
        for r in ratios:
            diag_vals = torch.tensor([r] + [1.0] * (TINY_H - 1))
            m = torch.diag(diag_vals).unsqueeze(0)
            etas.append(
                ScalarCurvatureProbe.compute_anisotropy_eta(m).item()
            )
        # Must be non-decreasing.
        for a, b in zip(etas, etas[1:]):
            assert b >= a - 1.0e-6, f"eta not monotonic: {etas}"


class TestRicciScalarSurrogate:
    def test_ricci_finite_on_psd_metric(self):
        probe = ScalarCurvatureProbe(hidden_size=TINY_H)
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        ricci = probe.ricci_scalar_surrogate(x)
        assert ricci.shape == (TINY_B,)
        assert torch.isfinite(ricci).all(), (
            f"Ricci surrogate should be finite on PSD metrics, got "
            f"{ricci.tolist()}"
        )

    def test_ricci_nan_on_non_psd_metric(self):
        """If somehow a metric has non-positive det (shouldn't happen
        with jitter > 0, but we want the guard active), Ricci should
        report NaN rather than silently returning bogus values."""
        # Construct a clearly singular (non-PSD) "metric".
        bad = torch.zeros(1, TINY_H, TINY_H)
        # Add a tiny negative on the diagonal to make sign < 0.
        bad[..., 0, 0] = -1.0e-3
        ricci = ScalarCurvatureProbe.compute_ricci_scalar_surrogate(bad)
        assert torch.isnan(ricci).any(), (
            "Ricci surrogate must flag non-PSD metrics with NaN."
        )

    def test_ricci_scales_with_volume_element(self):
        """Doubling all eigenvalues should add H * log(2) to the
        log-det part of the surrogate."""
        eye = torch.eye(TINY_H).unsqueeze(0)
        r1 = ScalarCurvatureProbe.compute_ricci_scalar_surrogate(eye)
        r2 = ScalarCurvatureProbe.compute_ricci_scalar_surrogate(2.0 * eye)
        delta = r2 - r1
        expected = TINY_H * float(torch.log(torch.tensor(2.0)))
        assert delta.item() == pytest.approx(expected, rel=1e-4), (
            f"Expected delta = H log 2 = {expected:.4f}, got "
            f"{delta.item():.4f}"
        )


class TestLegacyAnisotropy:
    def test_legacy_zero_for_isotropic(self):
        iso = torch.eye(TINY_H).unsqueeze(0)
        a = ScalarCurvatureProbe.compute_legacy_anisotropy(iso)
        assert a.item() == pytest.approx(0.0, abs=1e-6)

    def test_legacy_positive_for_anisotropic(self):
        diag_vals = torch.tensor([100.0] + [1.0] * (TINY_H - 1))
        aniso = torch.diag(diag_vals).unsqueeze(0)
        a = ScalarCurvatureProbe.compute_legacy_anisotropy(aniso)
        assert a.item() > 0.0


class TestForwardDefaultMode:
    def test_forward_returns_eta_by_default(self):
        """Theory §6.1 prediction is on eta; the public forward() of the
        probe should return eta unless the user explicitly opts out."""
        probe = ScalarCurvatureProbe(hidden_size=TINY_H)
        assert probe.default_mode == "eta"
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        # forward() result must match explicit eta call.
        assert torch.allclose(
            probe(x), probe.anisotropy_eta(x), atol=1e-7,
        )

    def test_forward_supports_alternate_modes(self):
        for mode in ("eta", "ricci", "legacy"):
            probe = ScalarCurvatureProbe(
                hidden_size=TINY_H, default_mode=mode,
            )
            assert probe.default_mode == mode
            x = torch.randn(TINY_B, TINY_S, TINY_H)
            out = probe(x)
            assert out.shape == (TINY_B,)

    def test_invalid_default_mode_raises(self):
        with pytest.raises(ValueError, match="default_mode"):
            ScalarCurvatureProbe(
                hidden_size=TINY_H, default_mode="magic_mode",
            )


class TestFIDLayerReportsAllSurrogates:
    def test_info_carries_eta_ricci_and_legacy(self):
        layer = _make_layer()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        for key in (
            "fisher_anisotropy_eta",
            "ricci_scalar_surrogate",
            "anisotropy_legacy",
        ):
            assert key in info, (
                f"FID forward() must report {key!r} for downstream "
                "prediction-tracking, but the key is missing."
            )
            assert isinstance(info[key], float)

    def test_curvature_key_kept_for_back_compat(self):
        """Legacy result files reference info['curvature']; FID must
        keep that key alive, pointing to the legacy surrogate."""
        layer = _make_layer()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        assert "curvature" in info
        # Should equal the legacy surrogate by construction.
        assert info["curvature"] == pytest.approx(
            info["anisotropy_legacy"], rel=1e-5
        )


# ======================================================================
# §D — Top-level switch API parity
# ======================================================================


class TestTopLevelSwitches:
    def test_set_noise_injection_three_levels(self):
        layer = _make_layer()
        # Initially the QID flag should default to True.
        layer.set_noise_injection(True)
        assert layer.qid._inject_quantum_noise is True
        assert layer.qid.cid_base._inject_noise is True
        # Now disable and verify three levels deep.
        layer.set_noise_injection(False)
        assert layer.qid._inject_quantum_noise is False
        assert layer.qid.cid_base._inject_noise is False

    def test_set_energy_monitoring_three_levels(self):
        layer = _make_layer()
        layer.set_energy_monitoring(True)
        assert layer.qid.cid_base._monitor_energy is True
        # The flag should be visible in info upon forward.
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        _, info = layer(x)
        assert "et_energy" in info, (
            "Enabling energy monitoring at the FID level should make "
            "et_energy visible in the per-step info dict."
        )
        layer.set_energy_monitoring(False)
        assert layer.qid.cid_base._monitor_energy is False

    def test_set_temperature_reaches_quantum_noise(self):
        layer = _make_layer()
        layer.set_temperature(0.5)
        assert layer.qid.quantum_noise.get_temperature() == pytest.approx(
            0.5, rel=1e-5
        )
        layer.set_temperature(100.0)
        assert layer.qid.quantum_noise.get_temperature() == pytest.approx(
            100.0, rel=1e-5
        )


# ======================================================================
# §E — FisherMetric robustness & calibration
# ======================================================================


class TestFisherMetricRobustness:
    def test_rejects_seq_len_one(self):
        f = FisherMetric(hidden_size=TINY_H)
        x = torch.randn(TINY_B, 1, TINY_H)
        with pytest.raises(ValueError, match="seq_len must be >="):
            _ = f.compute(x)

    def test_rejects_bad_input_dim(self):
        f = FisherMetric(hidden_size=TINY_H)
        with pytest.raises(ValueError, match="shape"):
            _ = f.compute(torch.randn(2, 16))  # 2-D, missing batch

    def test_rejects_hidden_dim_mismatch(self):
        f = FisherMetric(hidden_size=TINY_H)
        with pytest.raises(ValueError, match="channel dim"):
            _ = f.compute(torch.randn(2, 16, TINY_H + 1))

    def test_rejects_negative_jitter(self):
        f = FisherMetric(hidden_size=TINY_H, jitter=1e-4)
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        with pytest.raises(ValueError, match="jitter must be non-negative"):
            _ = f.compute(x, jitter=-0.1)

    def test_rejects_negative_jitter_at_construction(self):
        with pytest.raises(ValueError, match="jitter must be non-negative"):
            _ = FisherMetric(hidden_size=TINY_H, jitter=-1.0)

    def test_jitter_override_zero_gives_raw_cov(self):
        f = FisherMetric(hidden_size=TINY_H, jitter=1.0)  # large default
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        m_jitter = f.compute(x)
        m_raw = f.compute(x, jitter=0.0)
        # The two should differ by exactly jitter * I per batch entry.
        diff = m_jitter - m_raw
        expected = torch.eye(TINY_H).expand(TINY_B, -1, -1)
        assert torch.allclose(diff, expected, atol=1e-5)

    def test_rank_deficient_warning_emitted_once(self):
        """When seq_len < hidden_size, a RuntimeWarning must fire
        AT LEAST once per (hidden_size, seq_len) pair."""
        # Use a fresh hidden_size that the module hasn't seen before
        # to avoid the module-level dedup interfering with this test.
        H = 256
        f = FisherMetric(hidden_size=H)
        x = torch.randn(2, 8, H)  # seq_len < H
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _ = f.compute(x)
            rank_warnings = [
                ww for ww in w
                if issubclass(ww.category, RuntimeWarning)
                and "rank-deficient" in str(ww.message)
            ]
            assert rank_warnings, (
                "Expected a RuntimeWarning about rank-deficient "
                "covariance when seq_len < hidden_size"
            )

    def test_compute_returns_psd(self):
        f = FisherMetric(hidden_size=TINY_H)
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        m = f.compute(x)
        # Symmetric.
        assert torch.allclose(
            m, m.transpose(-2, -1), atol=1e-5,
        )
        # Positive eigenvalues (jitter > 0 guarantees this).
        eigvals = torch.linalg.eigvalsh(m)
        assert (eigvals > 0).all(), (
            "Default-jitter Fisher metric must be strictly positive "
            f"definite; got eigvals min = {eigvals.min().item()}"
        )


class TestTrueFisherDiagonalCalibration:
    """The true-Fisher diagonal helper should run on tiny UIDModel."""

    def test_returns_nonempty_nonneg_1d_tensor(self):
        # Import lazily; the test should still pass if the user has
        # configured a different model_uid path.
        try:
            from model.model_uid import UIDConfig, UIDModel
        except ImportError:
            pytest.skip("model.model_uid not importable; skipping")

        cfg = UIDConfig(
            vocab_size=128,
            hidden_size=32,
            num_hidden_layers=2,
            num_attention_heads=4,
            max_position_embeddings=16,
        )
        model = UIDModel(cfg)
        batch = torch.randint(0, 128, (2, 8))
        diag = FisherMetric.compute_true_fisher_diagonal(model, batch)
        assert diag.ndim == 1
        assert diag.numel() > 0
        # Squared grads must be non-negative.
        assert torch.all(diag >= 0.0)
        # Should be finite.
        assert torch.isfinite(diag).all()

    def test_param_filter_narrows_output(self):
        try:
            from model.model_uid import UIDConfig, UIDModel
        except ImportError:
            pytest.skip("model.model_uid not importable; skipping")

        cfg = UIDConfig(
            vocab_size=128,
            hidden_size=32,
            num_hidden_layers=2,
            num_attention_heads=4,
            max_position_embeddings=16,
        )
        model = UIDModel(cfg)
        batch = torch.randint(0, 128, (2, 8))

        diag_full = FisherMetric.compute_true_fisher_diagonal(model, batch)
        diag_attn = FisherMetric.compute_true_fisher_diagonal(
            model, batch, param_filter=["attn"],
        )
        # Attention-only Fisher should be a strict subset (smaller).
        assert 0 < diag_attn.numel() < diag_full.numel()


# ======================================================================
# §F — Forward + backward smoke tests
# ======================================================================


class TestForwardBackward:
    def test_forward_shape_and_finite(self):
        layer = _make_layer()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        y, info = layer(x)
        assert y.shape == x.shape
        assert torch.isfinite(y).all()

    def test_backward_with_curvature_weight_produces_finite_grads(self):
        layer = _make_layer(curvature_weight=0.1)
        layer.train()
        x = torch.randn(
            TINY_B, TINY_S, TINY_H, requires_grad=True,
        )
        y, info = layer(x)
        losses = extract_loss_tensors(info)
        # Task loss + curvature loss.
        task_loss = y.pow(2).mean()
        total = task_loss + losses["curvature"]
        total.backward()
        for name, p in layer.named_parameters():
            if not p.requires_grad:
                continue
            if p.grad is None:
                # Some legacy params (e.g. unused Lindblad ops) may
                # not be wired up; that's acceptable.
                continue
            assert torch.isfinite(p.grad).all(), (
                f"Non-finite gradient on {name}"
            )

    def test_curvature_loss_actually_changes_total_grad(self):
        """The curvature loss should produce a NON-TRIVIAL gradient
        contribution; if it doesn't, the weight pipeline is broken."""
        layer = _make_layer(curvature_weight=10.0)
        layer.train()

        x = torch.randn(TINY_B, TINY_S, TINY_H)
        y, info = layer(x)
        losses = extract_loss_tensors(info)
        loss_with = y.pow(2).mean() + losses["curvature"]
        loss_with.backward(retain_graph=False)
        grad_with = {
            n: p.grad.detach().clone()
            for n, p in layer.named_parameters() if p.grad is not None
        }

        # Reset and compute again WITHOUT the curvature term.
        layer.zero_grad()
        y2, info2 = layer(x)
        _ = extract_loss_tensors(info2)  # discard curvature loss
        loss_without = y2.pow(2).mean()
        loss_without.backward()
        grad_without = {
            n: p.grad.detach().clone()
            for n, p in layer.named_parameters() if p.grad is not None
        }

        # At least one parameter's gradient must differ between the two
        # cases — otherwise the curvature path has zero effect.
        any_diff = False
        for name in grad_with:
            if name not in grad_without:
                continue
            if not torch.allclose(
                grad_with[name], grad_without[name], atol=1e-6,
            ):
                any_diff = True
                break
        assert any_diff, (
            "Adding the curvature loss did not change any parameter's "
            "gradient — the curvature_weight pipeline appears broken."
        )

    def test_eval_mode_does_not_inject_noise(self):
        """In eval mode, neither CID-side nor QID-side noise should
        fire — forward must be deterministic for fixed input."""
        layer = _make_layer()
        layer.set_noise_injection(True)
        layer.eval()  # eval disables BOTH noise AND dropout
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        assert torch.allclose(y1, y2, atol=1e-6), (
            "FID forward should be deterministic in eval mode "
            "regardless of the injection switch."
        )


# ======================================================================
# §G — count_extras() diagnostic
# ======================================================================


class TestCountExtras:
    def test_count_extras_returns_total_key(self):
        layer = _make_layer()
        extras = layer.count_extras()
        assert "total" in extras
        assert "fid_extras" in extras
        # fid_extras should be 0 in the current implementation.
        assert extras["fid_extras"] == 0
        # total must equal the sum of all non-total keys.
        non_total_sum = sum(v for k, v in extras.items() if k != "total")
        assert extras["total"] == non_total_sum

    def test_count_extras_includes_qid_components(self):
        layer = _make_layer()
        extras = layer.count_extras()
        # We expect the QID extras to be forwarded as qid_* keys.
        qid_keys = [k for k in extras if k.startswith("qid_")]
        assert len(qid_keys) > 0, (
            "FIDLayer.count_extras() should forward QID extras under "
            "qid_* keys for parameter-budget regression testing."
        )


# ======================================================================
# §H — Round-trip (state_dict save / load)
# ======================================================================


class TestStateDictRoundTrip:
    def test_state_dict_roundtrip_preserves_v21_keys(self):
        layer_orig = _make_layer(
            use_et_symmetric=False,
            quantum_noise_mode="fft",
            curvature_weight=0.1,
        )
        sd = layer_orig.state_dict()

        layer_new = _make_layer(
            use_et_symmetric=False,
            quantum_noise_mode="fft",
            curvature_weight=0.1,
        )
        missing, unexpected = layer_new.load_state_dict(sd, strict=False)
        unexplained_missing = [
            k for k in missing
            if "tok_emb" not in k and "lm_head" not in k
        ]
        assert not unexplained_missing, (
            f"Unexplained missing keys after round-trip: "
            f"{unexplained_missing}"
        )
        # Architectural flag preservation: both layers built the same
        # way must have the same ET flag.
        assert (
            layer_new.qid.cid_base.attn.use_et_symmetric
            == layer_orig.qid.cid_base.attn.use_et_symmetric
            is False
        )

    def test_forward_after_roundtrip_matches(self):
        torch.manual_seed(7)
        layer_orig = _make_layer(use_berry=True)
        layer_orig.eval()
        x = torch.randn(TINY_B, TINY_S, TINY_H)
        y_orig, _ = layer_orig(x)

        sd = layer_orig.state_dict()
        torch.manual_seed(7)
        layer_new = _make_layer(use_berry=True)
        layer_new.load_state_dict(sd, strict=False)
        layer_new.eval()
        y_new, _ = layer_new(x)

        assert torch.allclose(y_orig, y_new, atol=1e-5), (
            "State-dict round-trip did not preserve forward outputs "
            "(max diff = "
            f"{(y_orig - y_new).abs().max().item():.2e})."
        )
