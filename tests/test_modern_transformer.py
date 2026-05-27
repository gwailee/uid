# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""Tests for the modern Transformer baseline."""

from __future__ import annotations

import pytest
import torch

from model.modern_transformer import (
    ModernTransformerLM,
    RMSNorm,
    SwiGLU,
    apply_rope,
    precompute_rope_freqs,
)


class TestRMSNorm:
    def test_output_shape(self):
        norm = RMSNorm(dim=64)
        x = torch.randn(2, 10, 64)
        y = norm(x)
        assert y.shape == x.shape

    def test_rms_is_one(self):
        """After RMSNorm with weight=1, RMS should be ≈1."""
        norm = RMSNorm(dim=64, eps=1e-6)
        norm.weight.data.fill_(1.0)
        x = torch.randn(2, 10, 64) * 5.0  # large scale
        y = norm(x)
        rms = torch.sqrt(y.pow(2).mean(-1))
        assert torch.allclose(rms, torch.ones_like(rms), atol=1e-3)


class TestRoPE:
    def test_precompute_shape(self):
        cos, sin = precompute_rope_freqs(head_dim=64, max_seq_len=128)
        assert cos.shape == (128, 32)  # head_dim // 2
        assert sin.shape == (128, 32)

    def test_apply_rope_preserves_shape(self):
        cos, sin = precompute_rope_freqs(head_dim=64, max_seq_len=128)
        x = torch.randn(2, 4, 16, 64)  # (B, H, S, D)
        y = apply_rope(x, cos, sin)
        assert y.shape == x.shape

    def test_rope_preserves_norm(self):
        """RoPE is a rotation; norm of vectors should be preserved."""
        cos, sin = precompute_rope_freqs(head_dim=64, max_seq_len=128)
        x = torch.randn(2, 4, 16, 64)
        y = apply_rope(x, cos, sin)
        norm_x = x.norm(dim=-1)
        norm_y = y.norm(dim=-1)
        assert torch.allclose(norm_x, norm_y, atol=1e-4)


class TestSwiGLU:
    def test_output_shape(self):
        ffn = SwiGLU(hidden_size=64)
        x = torch.randn(2, 10, 64)
        y = ffn(x)
        assert y.shape == x.shape


class TestModernTransformerLM:
    @pytest.fixture
    def model(self):
        return ModernTransformerLM(
            vocab_size=256,
            hidden_size=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
        )

    def test_forward_shape(self, model):
        x = torch.randint(0, 256, (2, 16))
        out = model(x)
        assert out.logits.shape == (2, 16, 256)

    def test_loss_computation(self, model):
        x = torch.randint(0, 256, (2, 16))
        labels = x.clone()
        out = model(x, labels=labels)
        assert out.loss is not None
        assert out.loss.dim() == 0
        assert torch.isfinite(out.loss)

    def test_output_hidden_states(self, model):
        x = torch.randint(0, 256, (2, 16))
        out = model(x, output_hidden_states=True)
        assert out.hidden_states is not None
        assert len(out.hidden_states) == 2  # num_layers
        for h in out.hidden_states:
            assert h.shape == (2, 16, 64)

    def test_non_embedding_param_count(self, model):
        """non_embedding_params should exclude tied embedding weights."""
        n_total = sum(p.numel() for p in model.parameters())
        n_non_emb = model.count_non_embedding_params()
        emb_params = model.tok_emb.weight.numel()
        # lm_head shares with tok_emb (tied), so only subtract once
        assert n_non_emb == n_total - emb_params

    def test_backward_pass(self, model):
        """Gradients should flow through all parameters."""
        x = torch.randint(0, 256, (2, 16))
        labels = x.clone()
        out = model(x, labels=labels)
        out.loss.backward()
        for name, p in model.named_parameters():
            assert p.grad is not None, f"No gradient for {name}"
            assert torch.isfinite(p.grad).all(), \
                f"Non-finite gradient for {name}"

    def test_causal_mask_is_applied(self, model):
        """Future tokens should not affect past predictions."""
        model.eval()
        x = torch.randint(0, 256, (1, 16))
        with torch.no_grad():
            out1 = model(x).logits
            # Modify the last token
            x2 = x.clone()
            x2[0, -1] = (x2[0, -1] + 1) % 256
            out2 = model(x2).logits
        # Predictions at earlier positions should be unchanged
        assert torch.allclose(out1[0, :-1], out2[0, :-1], atol=1e-5), \
            "Causal mask violated: changing last token affected earlier tokens"
