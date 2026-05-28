# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-28
"""Unit tests for ET Lyapunov monotonicity and vortex zero-extra-params.

ET 能量函数 Lyapunov 单调下降 + 旋度零额外参数 单元测试。

These tests directly verify the two main fixes mandated by the theory:
  1. §8.5 — ``HopfieldAttention`` with ``use_et_symmetric=True`` must
     produce an ET energy that is monotonically NON-INCREASING when
     applied recursively to a fixed input (under sufficiently small
     learning rate / step size). The standard branch carries no such
     guarantee.
  2. §14.2 — ``VortexField`` must introduce EXACTLY ONE extra learnable
     scalar parameter per layer (no extra H*H matrix).

Run with::

    pytest tests/test_et_lyapunov.py -v
"""

from __future__ import annotations

import math

import pytest
import torch
import torch.nn as nn

from cid.cid_layer import CIDBlock, CIDLayer
from cid.hopfield_potential import HopfieldAttention
from cid.vortex_field import VortexField


# ======================================================================
# §8.5 — ET energy monotonic descent
# ======================================================================


def _energy_descent_trace(
    attn: HopfieldAttention,
    x0: torch.Tensor,
    n_steps: int = 20,
    step_size: float = 0.1,
) -> list[float]:
    """Apply attention recursively and record energy at each step.

    递归施加 attention，记录每步的 ET 能量值。
    """
    x = x0.clone()
    energies: list[float] = []
    for _ in range(n_steps):
        e = attn.compute_energy(x).item()
        energies.append(e)
        with torch.no_grad():
            update = attn(x)
            # Small Euler step in the direction of -dE/dg.
            x = x + step_size * update
    energies.append(attn.compute_energy(x).item())
    return energies


def test_et_energy_decreases_monotonically():
    """ET symmetric attention must give monotonic energy descent."""
    torch.manual_seed(0)
    attn = HopfieldAttention(
        hidden_size=64, num_heads=4, use_et_symmetric=True
    )
    x0 = torch.randn(2, 8, 64)
    trace = _energy_descent_trace(attn, x0, n_steps=15, step_size=0.05)
    # Energy must be NON-INCREASING up to small numerical noise.
    # 能量必须单调不增（允许极小数值噪声）。
    tol = 1.0e-3 * max(abs(trace[0]), 1.0)
    for i in range(len(trace) - 1):
        assert trace[i + 1] <= trace[i] + tol, (
            f"ET energy increased at step {i}: "
            f"{trace[i]:.6f} -> {trace[i+1]:.6f}"
        )


def test_standard_attention_has_no_monotonic_guarantee():
    """Standard attention does NOT enjoy ET's monotonic descent property.

    This is a *sanity* test: we do not assert energy increases (it might
    by luck decrease too), but we confirm the symmetric branch differs
    quantitatively from the standard branch.
    """
    torch.manual_seed(0)
    h = 64
    attn_et = HopfieldAttention(
        hidden_size=h, num_heads=4, use_et_symmetric=True
    )
    attn_std = HopfieldAttention(
        hidden_size=h, num_heads=4, use_et_symmetric=False
    )
    # Copy ET weights into standard branch for a fair comparison.
    attn_std.k_proj.load_state_dict(attn_et.k_proj.state_dict())
    attn_std.q_proj.load_state_dict(attn_et.q_proj.state_dict())
    # v_proj is randomly initialised in std; doesn't matter for the
    # difference test.
    x = torch.randn(2, 8, h)
    out_et = attn_et(x)
    out_std = attn_std(x)
    diff = (out_et - out_std).abs().mean().item()
    assert diff > 1.0e-4, (
        f"ET and standard outputs are unexpectedly identical "
        f"(mean abs diff = {diff:.2e}); ET symmetric term may be missing."
    )


# ======================================================================
# §14.2 — VortexField zero-extra-parameter
# ======================================================================


def test_vortex_introduces_exactly_one_scalar_parameter():
    """VortexField must add EXACTLY one learnable scalar per instance.

    §14.2: curl is built from the antisymmetric part of an existing
    weight matrix; the only new parameter is the temperature-difference
    scalar.
    """
    h = 128
    # Provide an external FFN-like weight.
    ffn0 = nn.Linear(h, 4 * h, bias=False)
    vortex = VortexField(hidden_size=h, weight_ref=ffn0.weight)
    own_params = [p for p in vortex.parameters(recurse=True)]
    assert len(own_params) == 1, (
        f"VortexField owns {len(own_params)} parameters, expected 1"
    )
    assert own_params[0].numel() == 1, (
        f"VortexField owns a parameter with {own_params[0].numel()} "
        "elements, expected 1 (scalar log_temp_diff)"
    )


def test_vortex_antisymmetric_residual_is_zero():
    """The internally built J must satisfy J + J^T == 0."""
    h = 64
    ffn0 = nn.Linear(h, 4 * h, bias=False)
    vortex = VortexField(hidden_size=h, weight_ref=ffn0.weight)
    x = torch.randn(2, 5, h)
    _, info = vortex(x)
    assert info["antisym_residual"] < 1.0e-5, (
        f"J is not antisymmetric: residual = {info['antisym_residual']}"
    )


def test_vortex_zero_when_weight_ref_missing():
    """Without weight_ref, VortexField must degrade to zero curl."""
    h = 32
    with pytest.warns(RuntimeWarning):
        vortex = VortexField(hidden_size=h, weight_ref=None)
    x = torch.randn(2, 5, h)
    v, info = vortex(x)
    assert torch.allclose(v, torch.zeros_like(v))
    assert info["vortex_active"] == 0.0


# ======================================================================
# CIDLayer integration smoke-tests
# ======================================================================


def test_cidlayer_param_count_is_close_to_baseline():
    """CIDLayer should add only a few scalar parameters over a plain
    Transformer-style block (attention + FFN + 2 LayerNorms).
    """
    h, n = 128, 4
    layer = CIDLayer(
        hidden_size=h, num_heads=n,
        use_vortex=True, use_memory=True, use_colored_noise=True,
        noise_type="ou",
    )
    # Count parameters belonging to the CID-specific extras.
    # 关注 CID 引入的额外参数（旋度 + OU 噪声 + 4 个 log 权重标量）。
    extras = (
        sum(p.numel() for p in layer.vortex.parameters())
        + sum(p.numel() for p in layer.noise.parameters())
        + layer.log_w_grad.numel()
        + layer.log_w_vortex.numel()
        + layer.log_w_mem.numel()
        + layer.noise_scale.numel()
    )
    # Expected: 1 (vortex log_temp_diff)
    #         + 1 (OU log_sigma)
    #         + 4 (log_w_grad, log_w_vortex, log_w_mem, noise_scale)
    #         = 6 scalars.
    # Plus MemoryKernel which owns H*memory_length kernel weights.
    assert extras == 6, (
        f"CID extras = {extras} scalars; expected exactly 6 "
        "(vortex log_temp_diff + OU log_sigma + 4 weight scalars)"
    )


def test_cidlayer_forward_runs():
    """Smoke test: CIDLayer forward must execute without error."""
    torch.manual_seed(0)
    layer = CIDLayer(hidden_size=64, num_heads=4)
    x = torch.randn(2, 16, 64)
    y, info = layer(x)
    assert y.shape == x.shape
    assert isinstance(info, dict)


def test_cidblock_propagates_switches():
    """set_noise_injection / set_energy_monitoring must propagate."""
    block = CIDBlock(num_layers=3, hidden_size=32, num_heads=2)
    block.set_noise_injection(False)
    block.set_energy_monitoring(True)
    for layer in block.layers:
        assert layer._inject_noise is False
        assert layer._monitor_energy is True


def test_et_energy_appears_when_monitoring_enabled():
    """When monitoring is on, info dict must contain 'et_energy'."""
    torch.manual_seed(0)
    layer = CIDLayer(hidden_size=64, num_heads=4)
    layer.set_energy_monitoring(True)
    x = torch.randn(2, 8, 64)
    _, info = layer(x)
    assert "et_energy" in info
    assert isinstance(info["et_energy"], float)
