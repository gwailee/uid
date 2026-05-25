# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
#
# This file is part of the UID Theory reference implementation.
#
# DUAL LICENSE:
#   - PolyForm Noncommercial License 1.0.0  (academic / personal use)
#     see LICENSE-NONCOMMERCIAL in the project root
#   - Commercial License from Suzhou Jodell Robotics Co., Ltd.
#     (required for any commercial / for-profit / production use)
#     see LICENSE-COMMERCIAL in the project root
#
# For commercial licensing inquiries, contact: lig@jodell.cn
# 本文件采用双许可证发布；商业使用须先获得苏州机器人有限公司书面授权，
# 商业授权联系: lig@jodell.cn

"""CID block: a discrete Euler-Maruyama step of the CID master equation.

CID 主层：CID 主方程的 Euler-Maruyama 离散化实现。

The CID master equation reads
    ``dphi/dt = -grad U(phi) + v(phi)
              - integral_0^t gamma(t-s) dphi/ds ds + xi(t)``,
i.e. associative-memory drift, vortex (curl) from two-bath imbalance,
sub-Ohmic memory damping, and colored fluctuation.  Each ``CIDLayer``
realises one discrete step, plus a standard FFN sub-block.

CID 主方程包含四项：联想记忆漂移、双热浴旋度、色阻尼记忆核、色噪声。
``CIDLayer`` 实现该方程的一步离散，并附加标准 FFN 子块。
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
    """A single CID step.

    单个 CID 块；可单独消融每一项物理贡献。

    Attributes:
        use_vortex:        Toggle vortex term. 是否启用旋度项。
        use_memory:        Toggle memory-kernel term. 是否启用记忆核项。
        use_colored_noise: Toggle colored-noise term. 是否启用色噪声项。
    """

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
        """Build a CID layer.

        Args:
            hidden_size:        Feature dimension. 隐藏维度。
            num_heads:          Number of attention heads. 注意力头数。
            use_vortex:         Enable vortex field. 启用旋度场。
            use_memory:         Enable sub-Ohmic memory kernel.
                                启用亚欧姆记忆核。
            use_colored_noise:  Enable colored stochastic forcing.
                                启用色噪声驱动。
            noise_beta:         Slope of colored-noise PSD. 色噪声谱斜率。
            mem_alpha:          Sub-Ohmic exponent. 亚欧姆指数。
            memory_length:      Receptive field of memory kernel.
                                记忆核感受野长度。
            dropout:            FFN dropout probability. FFN dropout。
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.use_vortex: bool = bool(use_vortex)
        self.use_memory: bool = bool(use_memory)
        self.use_colored_noise: bool = bool(use_colored_noise)

        self.norm1: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.norm2: nn.LayerNorm = nn.LayerNorm(hidden_size)

        # -- physical sub-modules / 各物理子模块 --
        self.attn: HopfieldAttention = HopfieldAttention(
            hidden_size, num_heads
        )
        self.vortex: Optional[VortexField] = (
            VortexField(hidden_size) if use_vortex else None
        )
        self.memory: Optional[MemoryKernel] = (
            MemoryKernel(hidden_size, memory_length, mem_alpha)
            if use_memory
            else None
        )
        self.noise: Optional[FastColoredNoise] = (
            FastColoredNoise(noise_beta, hidden_size)
            if use_colored_noise
            else None
        )

        # -- FFN / 前馈网络 --
        self.ffn: nn.Sequential = nn.Sequential(
            nn.Linear(hidden_size, 4 * hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_size, hidden_size),
            nn.Dropout(dropout),
        )

        # Log-parameterised weights so each term remains non-negative.
        # Log 参数化使各项权重非负。
        self.log_w_grad: nn.Parameter = nn.Parameter(torch.tensor(0.0))
        self.log_w_vortex: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        self.log_w_mem: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        self.noise_scale: nn.Parameter = nn.Parameter(torch.tensor(0.01))

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """One discrete CID step plus FFN.

        Args:
            x:           Input of shape (B, S, H). 输入张量。
            causal_mask: Optional causal mask, ``True`` = masked out.
                         可选因果掩码。
            add_noise:   Whether to inject colored noise. 是否注入色噪声。

        Returns:
            Tuple ``(x_next, info)``; ``info`` holds diagnostic scalars.
            返回更新后的张量和诊断信息。
        """
        info: Dict[str, float] = {}
        h = self.norm1(x)

        # 1. Associative-memory drift  -grad U.
        grad_term = torch.exp(self.log_w_grad) * self.attn(
            h, causal_mask=causal_mask
        )

        # 2. Vortex (curl).
        vortex_term = torch.zeros_like(h)
        if self.vortex is not None:
            v, vinfo = self.vortex(h)
            vortex_term = torch.exp(self.log_w_vortex) * v
            info.update({f"vortex_{k}": val for k, val in vinfo.items()})

        # 3. Sub-Ohmic memory damping.
        mem_term = torch.zeros_like(h)
        if self.memory is not None:
            mem_term = -torch.exp(self.log_w_mem) * self.memory(h)

        # 4. Colored fluctuation.
        noise_term = torch.zeros_like(h)
        if self.noise is not None and add_noise and self.training:
            xi = self.noise(h.shape[0], h.shape[1], h.device, h.dtype)
            noise_term = self.noise_scale * xi

        # Euler-Maruyama: dt is absorbed into per-term weights.
        # Euler-Maruyama 离散化；时间步 dt 已吸收进各项权重。
        x = x + grad_term + vortex_term + mem_term + noise_term

        # Standard FFN residual.
        x = x + self.ffn(self.norm2(x))
        return x, info


class CIDBlock(nn.Module):
    """Stack of ``num_layers`` CID layers.

    多层 CID 块；可选返回每层隐藏状态用于诊断。
    """

    def __init__(self, num_layers: int = 8, **layer_kwargs) -> None:
        """Initialise the stack.

        Args:
            num_layers: Number of CID layers. CID 层数。
            **layer_kwargs: Forwarded to :class:`CIDLayer`.
                            其余参数转发给 :class:`CIDLayer`。
        """
        super().__init__()
        if num_layers <= 0:
            raise ValueError(
                f"num_layers must be positive, got {num_layers}"
            )
        self.layers: nn.ModuleList = nn.ModuleList(
            [CIDLayer(**layer_kwargs) for _ in range(num_layers)]
        )

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
        return_hidden_states: bool = False,
    ) -> Tuple[torch.Tensor, Optional[List[torch.Tensor]], Dict[str, Dict]]:
        """Run the stack.

        Args:
            x:                    Input of shape (B, S, H). 输入。
            causal_mask:          Optional causal mask. 可选因果掩码。
            add_noise:            Whether to inject colored noise. 是否注入色噪声。
            return_hidden_states: If True, also return per-layer hidden
                                  tensors. 是否返回每层隐藏状态。

        Returns:
            Tuple ``(x_final, hidden_states, info)``;
            ``hidden_states`` is ``None`` unless requested.
        """
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
