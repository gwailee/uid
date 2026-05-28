# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * Fix dropout side-effects in disable-noise tests (must use dropout=0
#     to make outputs strictly deterministic when noise is disabled).
#   * Add v2.1 regression tests: set_energy_monitoring, noise_type
#     selection, use_et_symmetric, fluctuation_dissipation_consistency,
#     and zero-extra-parameter vortex param counting.
"""
Tests for the CID layer.

Covers:
  - Basic forward / shape / component toggling.
  - v2.0 fix: set_noise_injection() runtime switch (prevents circular
    measurement of emergent critical exponents).
  - v2.1 fixes (Theory §8.5 / §14.2):
      * ET symmetric dual-term Hopfield attention.
      * Zero-extra-parameter vortex via FFN antisymmetric projection.
      * Default OrnsteinUhlenbeckNoise; FFT fallback selectable.
      * set_energy_monitoring() for Lyapunov verification.
      * fluctuation_dissipation_consistency() diagnostic.
"""

from __future__ import annotations

import pytest
import torch

from uid_theory.cid.cid_layer import CIDBlock, CIDLayer
from uid_theory.cid.colored_noise import (
    FastColoredNoise,
    OrnsteinUhlenbeckNoise,
)


# ======================================================================
# Basic forward / construction
# ======================================================================


class TestCIDLayerBasic:
    def test_forward_shape(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        x = torch.randn(2, 16, 64)
        y, info = layer(x)
        assert y.shape == x.shape
        assert isinstance(info, dict)

    def test_all_components_present(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_vortex=True, use_memory=True, use_colored_noise=True,
        )
        assert layer.vortex is not None
        assert layer.memory is not None
        assert layer.noise is not None

    def test_components_can_be_disabled(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_vortex=False, use_memory=False, use_colored_noise=False,
        )
        assert layer.vortex is None
        assert layer.memory is None
        assert layer.noise is None


# ======================================================================
# v2.0 fix: set_noise_injection runtime switch
# ======================================================================


class TestDisableNoiseInjection:
    """CRITICAL tests for the v2.0 fix.

    These verify that ``set_noise_injection(False)`` actually disables
    noise injection at runtime — preventing the circular logic in
    critical-exponent measurements.

    NOTE: All deterministic tests below MUST use ``dropout=0`` to
    eliminate the residual stochasticity introduced by the FFN
    dropout layer (which would otherwise mask the noise-injection
    switch).
    """

    def test_set_noise_injection_api_exists(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        assert hasattr(layer, "set_noise_injection")
        layer.set_noise_injection(False)
        assert layer._inject_noise is False
        layer.set_noise_injection(True)
        assert layer._inject_noise is True

    def test_noise_injected_when_enabled(self):
        """With injection ON in train mode, outputs should differ across
        calls with different random seeds.
        """
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_colored_noise=True,
            dropout=0.0,  # isolate the effect of noise injection
        )
        layer.set_noise_injection(True)
        layer.train()
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        # Different random states → different outputs.
        assert not torch.allclose(y1, y2, atol=1e-6), (
            "Noise is enabled but outputs are identical"
        )

    def test_noise_disabled_when_requested(self):
        """With injection OFF, outputs should be deterministic.

        We must set ``dropout=0`` to eliminate FFN dropout stochasticity,
        otherwise this test would fail for reasons unrelated to noise
        injection.
        """
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_colored_noise=True,
            dropout=0.0,  # CRITICAL: rule out FFN dropout
        )
        layer.set_noise_injection(False)
        layer.train()  # Even in train mode, injection should be OFF.
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        # Without noise (and without dropout), outputs must be identical.
        assert torch.allclose(y1, y2, atol=1e-6), (
            "Noise is disabled but outputs differ across random seeds"
        )

    def test_noise_disabled_in_eval_mode(self):
        """Eval mode should also disable noise, even if ``_inject_noise``
        is True. Eval mode also disables FFN dropout automatically,
        so dropout level doesn't matter here.
        """
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_colored_noise=True,
        )
        layer.set_noise_injection(True)
        layer.eval()  # Eval mode → dropout & noise both off.
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        assert torch.allclose(y1, y2, atol=1e-6), (
            "Noise should be off in eval mode"
        )


# ======================================================================
# v2.1 fix: §14.2 zero-extra-parameter vortex
# ======================================================================


class TestVortexZeroExtraParams:
    """Regression tests for the §14.2 "extra params = 0" hard rule."""

    def test_vortex_owns_only_one_scalar(self):
        """``VortexField`` instance must own exactly 1 scalar parameter
        (log_temp_diff), since the curl matrix J = (W - W^T)/2 is
        built on the fly from a non-owning reference to FFN weights.
        """
        layer = CIDLayer(
            hidden_size=128, num_heads=4,
            use_vortex=True, use_memory=False, use_colored_noise=False,
            dropout=0.0,
        )
        vortex_params = list(layer.vortex.parameters(recurse=True))
        assert len(vortex_params) == 1, (
            f"VortexField owns {len(vortex_params)} parameters, expected 1"
        )
        assert vortex_params[0].numel() == 1, (
            f"VortexField owns a parameter with {vortex_params[0].numel()} "
            "elements, expected exactly 1 scalar log_temp_diff"
        )

    def test_vortex_actually_contributes(self):
        """Toggling ``use_vortex`` must produce numerically different
        forward outputs — otherwise the term is a silent no-op.
        """
        torch.manual_seed(0)
        h = 64
        layer_with = CIDLayer(
            hidden_size=h, num_heads=4,
            use_vortex=True, use_memory=False, use_colored_noise=False,
            dropout=0.0,
        )
        # Inflate vortex weight so its contribution is unambiguous.
        with torch.no_grad():
            layer_with.log_w_vortex.fill_(2.0)
            layer_with.vortex.log_temp_diff.fill_(2.0)
        layer_without = CIDLayer(
            hidden_size=h, num_heads=4,
            use_vortex=False, use_memory=False, use_colored_noise=False,
            dropout=0.0,
        )
        # Make the two layers share weights for the parts they both have,
        # so that ONLY the vortex term differs.
        layer_without.load_state_dict(
            {
                k: v for k, v in layer_with.state_dict().items()
                if k in layer_without.state_dict()
            },
            strict=False,
        )
        layer_with.eval()
        layer_without.eval()
        x = torch.randn(2, 16, h)
        y_with, _ = layer_with(x)
        y_without, _ = layer_without(x)
        diff = (y_with - y_without).abs().mean().item()
        assert diff > 1.0e-4, (
            f"Toggling vortex changed output by only {diff:.2e}; "
            "the vortex term may be silently degenerate."
        )


# ======================================================================
# v2.1 fix: §14.2 default OU noise, FFT selectable
# ======================================================================


class TestNoiseTypeSelection:
    def test_default_noise_is_ou(self):
        """v2.1 default colored noise must be OrnsteinUhlenbeckNoise."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4, use_colored_noise=True,
        )
        assert isinstance(layer.noise, OrnsteinUhlenbeckNoise), (
            f"Default noise type is {type(layer.noise).__name__}, "
            "expected OrnsteinUhlenbeckNoise per Theory §14.2."
        )

    def test_noise_type_fft_selectable(self):
        """``noise_type='fft'`` must still work for legacy comparison."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_colored_noise=True,
            noise_type="fft",
            noise_beta=1.0,
        )
        assert isinstance(layer.noise, FastColoredNoise)

    def test_noise_type_invalid_raises(self):
        with pytest.raises(ValueError, match="unknown noise_type"):
            CIDLayer(
                hidden_size=64, num_heads=4,
                use_colored_noise=True,
                noise_type="purple",
            )


# ======================================================================
# v2.1 fix: §8.5 ET symmetric attention switch
# ======================================================================


class TestETSymmetricSwitch:
    def test_default_uses_et_symmetric(self):
        """Default attention must be ET-symmetric per Theory §8.5."""
        layer = CIDLayer(hidden_size=64, num_heads=4)
        assert layer.attn.use_et_symmetric is True

    def test_can_disable_et_for_ablation(self):
        """For ablation we must be able to fall back to standard attn."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4, use_et_symmetric=False,
        )
        assert layer.attn.use_et_symmetric is False

    def test_et_and_standard_differ_quantitatively(self):
        """ET and standard branches must produce numerically different
        outputs given identical key/query projections — otherwise the
        ET symmetric term is missing.
        """
        torch.manual_seed(0)
        h = 64
        layer_et = CIDLayer(
            hidden_size=h, num_heads=4,
            use_vortex=False, use_memory=False, use_colored_noise=False,
            dropout=0.0,
            use_et_symmetric=True,
        )
        layer_std = CIDLayer(
            hidden_size=h, num_heads=4,
            use_vortex=False, use_memory=False, use_colored_noise=False,
            dropout=0.0,
            use_et_symmetric=False,
        )
        # Share the attention's K and Q projections.
        layer_std.attn.k_proj.load_state_dict(
            layer_et.attn.k_proj.state_dict()
        )
        layer_std.attn.q_proj.load_state_dict(
            layer_et.attn.q_proj.state_dict()
        )
        # Standard branch additionally uses v_proj / o_proj; tie o_proj
        # to make the comparison strictly about term-1 vs term-1+term-2.
        layer_std.attn.o_proj.load_state_dict(
            layer_et.attn.o_proj.state_dict()
        )
        # Make norm and FFN identical too.
        layer_std.norm1.load_state_dict(layer_et.norm1.state_dict())
        layer_std.norm2.load_state_dict(layer_et.norm2.state_dict())
        layer_std.ffn.load_state_dict(layer_et.ffn.state_dict())
        layer_et.eval()
        layer_std.eval()
        x = torch.randn(2, 16, h)
        y_et, _ = layer_et(x)
        y_std, _ = layer_std(x)
        diff = (y_et - y_std).abs().mean().item()
        assert diff > 1.0e-4, (
            f"ET and standard attention outputs differ by only "
            f"{diff:.2e}; the ET symmetric second term may be missing."
        )


# ======================================================================
# v2.1 fix: ET energy monitoring (§8.5 Lyapunov verification)
# ======================================================================


class TestEnergyMonitoring:
    def test_monitor_api_exists(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        assert hasattr(layer, "set_energy_monitoring")
        layer.set_energy_monitoring(True)
        assert layer._monitor_energy is True
        layer.set_energy_monitoring(False)
        assert layer._monitor_energy is False

    def test_energy_appears_in_info_when_enabled(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        layer.set_energy_monitoring(True)
        x = torch.randn(2, 16, 64)
        _, info = layer(x)
        assert "et_energy" in info
        assert isinstance(info["et_energy"], float)

    def test_no_energy_when_disabled(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        layer.set_energy_monitoring(False)
        x = torch.randn(2, 16, 64)
        _, info = layer(x)
        assert "et_energy" not in info


# ======================================================================
# v2.1 fix: fluctuation-dissipation consistency diagnostic
# ======================================================================


class TestFDTConsistency:
    def test_returns_dict(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_memory=True, use_colored_noise=True,
            noise_type="ou",
        )
        report = layer.fluctuation_dissipation_consistency()
        assert isinstance(report, dict)

    def test_ou_mode_marker(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_memory=True, use_colored_noise=True,
            noise_type="ou",
        )
        report = layer.fluctuation_dissipation_consistency()
        # OU mode: noise_mode == 0.0
        assert report.get("noise_mode") == 0.0
        assert report.get("fdt_ok") == 1.0

    def test_fft_mode_compares_alpha_beta(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_memory=True, use_colored_noise=True,
            noise_type="fft",
            mem_alpha=0.3,
            noise_beta=0.3,  # match alpha to satisfy FDT
        )
        report = layer.fluctuation_dissipation_consistency()
        assert report.get("noise_mode") == 1.0
        assert report.get("fdt_ok") == 1.0
        assert report.get("fdt_residual") < 0.1

    def test_fft_mode_flags_mismatch(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_memory=True, use_colored_noise=True,
            noise_type="fft",
            mem_alpha=0.3,
            noise_beta=1.5,  # very different from alpha
        )
        report = layer.fluctuation_dissipation_consistency()
        assert report.get("fdt_ok") == 0.0

    def test_empty_when_components_disabled(self):
        layer = CIDLayer(
            hidden_size=64, num_heads=4,
            use_memory=False, use_colored_noise=False,
        )
        report = layer.fluctuation_dissipation_consistency()
        assert report == {}


# ======================================================================
# CIDBlock-level tests
# ======================================================================


class TestCIDBlock:
    def test_propagates_noise_injection_to_layers(self):
        """set_noise_injection on block should propagate to all layers."""
        block = CIDBlock(
            num_layers=3, hidden_size=64, num_heads=4,
            use_colored_noise=True,
        )
        block.set_noise_injection(False)
        for layer in block.layers:
            assert layer._inject_noise is False

        block.set_noise_injection(True)
        for layer in block.layers:
            assert layer._inject_noise is True

    def test_propagates_energy_monitoring_to_layers(self):
        block = CIDBlock(num_layers=3, hidden_size=64, num_heads=4)
        block.set_energy_monitoring(True)
        for layer in block.layers:
            assert layer._monitor_energy is True
        block.set_energy_monitoring(False)
        for layer in block.layers:
            assert layer._monitor_energy is False

    def test_fdt_report_per_layer(self):
        block = CIDBlock(
            num_layers=3, hidden_size=64, num_heads=4,
            use_memory=True, use_colored_noise=True, noise_type="ou",
        )
        reports = block.fluctuation_dissipation_consistency()
        assert isinstance(reports, list)
        assert len(reports) == 3
        for r in reports:
            assert r.get("noise_mode") == 0.0

    def test_returns_hidden_states_when_requested(self):
        block = CIDBlock(
            num_layers=2, hidden_size=64, num_heads=4,
        )
        x = torch.randn(2, 16, 64)
        y, hidden, info = block(x, return_hidden_states=True)
        assert y.shape == x.shape
        assert hidden is not None
        assert len(hidden) == 2
        for h in hidden:
            assert h.shape == (2, 16, 64)


# ======================================================================
# Extras parameter budget (overall regression)
# ======================================================================


class TestCIDLayerParameterBudget:
    """§14.2 promises CID adds only a handful of scalar parameters
    over a baseline Transformer block. This regression test pins down
    the exact extras to catch unintended parameter inflation.
    """

    def test_extras_are_exactly_six_scalars(self):
        h = 128
        layer = CIDLayer(
            hidden_size=h, num_heads=4,
            use_vortex=True, use_memory=True, use_colored_noise=True,
            noise_type="ou",
        )
        # Count the CID-specific extras only.
        # Expected:
        #   - 1 vortex log_temp_diff
        #   - 1 OU log_sigma
        #   - 4 log weight scalars (grad, vortex, mem, noise_scale)
        extras_scalars = (
            sum(p.numel() for p in layer.vortex.parameters())
            + sum(p.numel() for p in layer.noise.parameters())
            + layer.log_w_grad.numel()
            + layer.log_w_vortex.numel()
            + layer.log_w_mem.numel()
            + layer.noise_scale.numel()
        )
        assert extras_scalars == 6, (
            f"CID extras = {extras_scalars} scalars; expected exactly 6.\n"
            "Breakdown should be:\n"
            "  vortex.log_temp_diff (1) + OU.log_sigma (1) + "
            "log_w_grad (1) + log_w_vortex (1) + log_w_mem (1) + "
            "noise_scale (1) = 6.\n"
            "If this fails, CID may have accidentally introduced an "
            "extra parameter matrix in violation of §14.2."
        )
