# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
Tests for the CID layer, with special focus on the v2.0 fix:
the disable_noise_injection mode.
"""

from __future__ import annotations

import torch

from uid_theory.cid.cid_layer import CIDBlock, CIDLayer


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


class TestDisableNoiseInjection:
    """
    CRITICAL TESTS for the v2.0 fix.
    
    These verify that set_noise_injection(False) actually disables 
    noise injection at runtime — preventing the circular logic in 
    critical-exponent measurements.
    """

    def test_set_noise_injection_api_exists(self):
        layer = CIDLayer(hidden_size=64, num_heads=4)
        assert hasattr(layer, "set_noise_injection")
        layer.set_noise_injection(False)
        assert layer._inject_noise is False
        layer.set_noise_injection(True)
        assert layer._inject_noise is True

    def test_noise_injected_when_enabled(self):
        """With injection ON in train mode, outputs should differ across calls."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4, use_colored_noise=True,
        )
        layer.set_noise_injection(True)
        layer.train()
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        # Different random states → different outputs
        assert not torch.allclose(y1, y2, atol=1e-6), \
            "Noise is enabled but outputs are identical"

    def test_noise_disabled_when_requested(self):
        """With injection OFF, outputs should be deterministic."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4, use_colored_noise=True,
        )
        layer.set_noise_injection(False)
        layer.train()  # Even in train mode, injection should be OFF
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        # Without noise, outputs should be identical
        assert torch.allclose(y1, y2, atol=1e-6), \
            "Noise is disabled but outputs differ across random seeds"

    def test_noise_disabled_in_eval_mode(self):
        """Eval mode should also disable noise, even if _inject_noise is True."""
        layer = CIDLayer(
            hidden_size=64, num_heads=4, use_colored_noise=True,
        )
        layer.set_noise_injection(True)
        layer.eval()  # Eval mode
        x = torch.randn(2, 16, 64)
        torch.manual_seed(1)
        y1, _ = layer(x)
        torch.manual_seed(2)
        y2, _ = layer(x)
        assert torch.allclose(y1, y2, atol=1e-6), \
            "Noise should be off in eval mode"


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
