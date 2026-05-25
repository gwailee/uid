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

"""QID block: CID base plus classical surrogates of quantum corrections.

QID 主层：在 CID 基础上叠加量子修正项的经典代理。

The quantum corrections implemented here are *classical emulations*:
    * Hamiltonian flow via an anti-symmetric linear map.
    * Lindblad dissipation as a learnable contractive map (phenomeno-
      logical surrogate; not a faithful Kraus-form decomposition).
    * Berry phase via per-pair U(1) rotation (see berry_phase.py).
    * Quantum colored noise with explicit zero-point branch.

Real quantum advantage requires actual quantum hardware; this module
exists so that the API and training pipeline are forward-compatible.

本模块为量子修正的经典代理实现，便于与真实量子硬件未来对接。Lindblad
项以现象学映射代替严格的 Kraus 形式，是工程近似，不构成数学严格的耗散
通道。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn

from ..cid.cid_layer import CIDLayer
from .berry_phase import BerryPhaseLayer
from .quantum_noise import QuantumColoredNoise


class QIDLayer(nn.Module):
    """CID layer plus quantum-style corrections.

    在 CID 层基础上加入量子修正项。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        num_lindblad_channels: int = 4,
        use_berry: bool = True,
        dropout: float = 0.1,
    ) -> None:
        """Initialise the QID layer.

        Args:
            hidden_size:           Feature dimension. 隐藏维度。
            num_heads:             Number of attention heads. 注意力头数。
            num_lindblad_channels: Number of phenomenological Lindblad
                                    channels. Lindblad 通道数（现象学）。
            use_berry:             Toggle Berry-phase rotation.
                                    是否启用 Berry 相位。
            dropout:               Dropout for the FFN. FFN dropout。
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.use_berry: bool = bool(use_berry)

        # CID base; we disable its colored noise because the QID layer
        # injects its own quantum-noise term below.
        # CID 基础层；关闭其色噪声，由 QID 层注入量子噪声替代。
        self.cid_base: CIDLayer = CIDLayer(
            hidden_size=hidden_size,
            num_heads=num_heads,
            use_vortex=True,
            use_memory=True,
            use_colored_noise=False,
            dropout=dropout,
        )

        # Hamiltonian generator: we will anti-symmetrise its weight at
        # forward time to enforce unitarity at first order.
        # 哈密顿生成元；前向时在通道维上反对称化，保证一阶幺正性。
        self.hamiltonian_weight: nn.Parameter = nn.Parameter(
            torch.randn(hidden_size, hidden_size) * 0.01
        )

        # Phenomenological Lindblad channels.
        # 现象学 Lindblad 通道（不是严格 Kraus 形式）。
        self.lindblad_ops: nn.ModuleList = nn.ModuleList(
            [
                nn.Linear(hidden_size, hidden_size, bias=False)
                for _ in range(num_lindblad_channels)
            ]
        )
        self.log_lindblad_rates: nn.Parameter = nn.Parameter(
            torch.full((num_lindblad_channels,), -4.0)
        )

        if use_berry:
            self.berry: Optional[BerryPhaseLayer] = BerryPhaseLayer(
                hidden_size
            )
        else:
            self.berry = None

        self.quantum_noise: QuantumColoredNoise = QuantumColoredNoise(
            hidden_size
        )

        # Bounded mixing coefficient via sigmoid.
        # 量子修正强度的有界混合系数。
        self.quantum_logit: nn.Parameter = nn.Parameter(
            torch.tensor(-2.0)
        )

    def _hamiltonian_step(
        self, x: torch.Tensor, dt: float = 0.1
    ) -> torch.Tensor:
        """First-order unitary step using anti-symmetrised generator.

        反对称化生成元的一阶幺正演化近似。
        """
        # Anti-symmetrise the (H, H) weight matrix.
        h_antisym = 0.5 * (
            self.hamiltonian_weight - self.hamiltonian_weight.T
        )
        # x_new = x + dt * (-i H) x  -->  first-order approximation in
        # the real-valued representation: x - dt * (h_antisym @ x).
        # 在实数表示下，一阶幺正近似。
        delta = torch.einsum("ij,bsj->bsi", h_antisym, x)
        return x - dt * delta

    def _lindblad_step(self, x: torch.Tensor) -> torch.Tensor:
        """Phenomenological dissipation (not a faithful Kraus form).

        现象学耗散项（仅作近似，非严格 Kraus 分解）。
        """
        out = torch.zeros_like(x)
        rates = torch.exp(self.log_lindblad_rates)
        for i, op in enumerate(self.lindblad_ops):
            out = out + rates[i] * (op(x) - 0.5 * x)
        return out

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Run one QID step.

        Args:
            x:           Input of shape (B, S, H). 输入。
            causal_mask: Optional causal mask. 可选因果掩码。

        Returns:
            Tuple ``(x_next, info)``. 输出张量及诊断信息字典。
        """
        info: Dict[str, float] = {}

        # 1. CID base step.
        x_classical, cid_info = self.cid_base(
            x, causal_mask=causal_mask, add_noise=False
        )
        info["cid_layers"] = sum(
            1 for k in cid_info if k.startswith("vortex_")
        )  # cheap marker

        # 2. Quantum corrections (each is a delta against x_classical).
        # 各量子修正都作为增量叠加到 x_classical 上。
        delta = torch.zeros_like(x_classical)
        delta = delta + (
            self._hamiltonian_step(x_classical) - x_classical
        )
        delta = delta + 0.1 * self._lindblad_step(x_classical)

        if self.berry is not None:
            y, phases = self.berry(x_classical)
            delta = delta + (y - x_classical)
            with torch.no_grad():
                info["berry_phase_mean"] = float(phases.mean().item())
                info["berry_phase_std"] = float(phases.std().item())

        if self.training:
            qn, qn_info = self.quantum_noise(
                x_classical.shape[0],
                x_classical.shape[1],
                x_classical.device,
                x_classical.dtype,
            )
            delta = delta + 0.01 * qn
            info.update({f"qnoise_{k}": v for k, v in qn_info.items()})

        weight = torch.sigmoid(self.quantum_logit)
        info["quantum_weight"] = float(weight.detach().item())
        return x_classical + weight * delta, info
