# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
CID layer: Euler-Maruyama discretization of the CID master equation.

CID 主层：CID 主方程的 Euler-Maruyama 离散化实现。

KEY CHANGE in v2.0:
    Added `disable_injection` mode that turns off colored noise 
    injection at inference time. This is CRITICAL for honest 
    measurement of emergent critical exponents — without this 
    mode, any measurement of 1/f spectra would be circular 
    (we'd just be measuring what we injected).
    
    Usage:
        # During training: noise injection ON
        model.train()
        # During emergence measurement: noise injection OFF
        model.eval()
        model.set_noise_injection(False)
        # ... measure spectra, Hurst, avalanches ...
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn

from .colored_noise import FastColoredNoise
from .hopfield_potential import HopfieldAttention
from .memory_kernel import MemoryKernel
from .vortex_field import VortexField


class CIDLayer(nn.Module):
    """A single CID step with disable_injection support."""

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        use_vortex: bool = True,
        use_memory: bool = True,
        use_colored_noise: bool = True,
        noise_beta: float = 1.0,
        mem_alpha: float = 0.3,
        memory_length: int = 64,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.use_vortex: bool = bool(use_vortex)
        self.use_memory: bool = bool(use_memory)
        self.use_colored_noise: bool = bool(use_colored_noise)
        # CRITICAL: separate flag for runtime control of noise injection
        self._inject_noise: bool = True

        self.norm1: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.norm2: nn.LayerNorm = nn.LayerNorm(hidden_size)

        self.attn: HopfieldAttention = HopfieldAttention(
            hidden_size, num_heads
        )
        self.vortex: Optional[VortexField] = (
            VortexField(hidden_size) if use_vortex else None
        )
        self.memory: Optional[MemoryKernel] = (
            MemoryKernel(hidden_size, memory_length, mem_alpha)
            if use_memory else None
        )
        self.noise: Optional[FastColoredNoise] = (
            FastColoredNoise(noise_beta, hidden_size)
            if use_colored_noise else None
        )

        self.ffn: nn.Sequential = nn.Sequential(
            nn.Linear(hidden_size, 4 * hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_size, hidden_size),
            nn.Dropout(dropout),
        )

        self.log_w_grad: nn.Parameter = nn.Parameter(torch.tensor(0.0))
        self.log_w_vortex: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        self.log_w_mem: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        self.noise_scale: nn.Parameter = nn.Parameter(torch.tensor(0.01))

    def set_noise_injection(self, enabled: bool) -> None:
        """
        Enable or disable colored-noise injection.
        
        CRITICAL: For honest measurement of emergent critical 
        exponents (1/f spectra, Hurst, avalanches), this MUST be 
        set to False during measurement. Otherwise, any "emergent" 
        signature would be circular — simply echoing the injected 
        noise pattern.
        """
        self._inject_noise = bool(enabled)

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        info: Dict[str, float] = {}
        h = self.norm1(x)

        # 1. Associative-memory drift
        grad_term = torch.exp(self.log_w_grad) * self.attn(
            h, causal_mask=causal_mask
        )

        # 2. Vortex (curl)
        vortex_term = torch.zeros_like(h)
        if self.vortex is not None:
            v, vinfo = self.vortex(h)
            vortex_term = torch.exp(self.log_w_vortex) * v
            info.update({f"vortex_{k}": val for k, val in vinfo.items()})

        # 3. Sub-Ohmic memory damping
        mem_term = torch.zeros_like(h)
        if self.memory is not None:
            mem_term = -torch.exp(self.log_w_mem) * self.memory(h)

        # 4. Colored fluctuation
        # Three conditions ALL must hold to actually inject:
        #   - configured to have noise (use_colored_noise)
        #   - caller requested it (add_noise)
        #   - model-level switch is on (_inject_noise) ← NEW in v2.0
        #   - training mode
        noise_term = torch.zeros_like(h)
        should_inject = (
            self.noise is not None
            and add_noise
            and self._inject_noise
            and self.training
        )
        if should_inject:
            xi = self.noise(h.shape[0], h.shape[1], h.device, h.dtype)
            noise_term = self.noise_scale * xi

        # Euler-Maruyama
        x = x + grad_term + vortex_term + mem_term + noise_term
        x = x + self.ffn(self.norm2(x))
        return x, info


class CIDBlock(nn.Module):
    """Stack of CID layers with disable_injection propagation."""

    def __init__(self, num_layers: int = 8, **layer_kwargs) -> None:
        super().__init__()
        if num_layers <= 0:
            raise ValueError(f"num_layers must be positive, got {num_layers}")
        self.layers: nn.ModuleList = nn.ModuleList(
            [CIDLayer(**layer_kwargs) for _ in range(num_layers)]
        )

    def set_noise_injection(self, enabled: bool) -> None:
        """Propagate noise-injection switch to all layers."""
        for layer in self.layers:
            layer.set_noise_injection(enabled)

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
        return_hidden_states: bool = False,
    ) -> Tuple[torch.Tensor, Optional[List[torch.Tensor]], Dict[str, Dict]]:
        hidden_states: Optional[List[torch.Tensor]] = (
            [] if return_hidden_states else None
        )
        info: Dict[str, Dict] = {}
        for i, layer in enumerate(self.layers):
            x, layer_info = layer(
                x, causal_mask=causal_mask, add_noise=add_noise
            )
            info[f"layer_{i}"] = layer_info
            if hidden_states is not None:
                hidden_states.append(x)
        return x, hidden_states, info
