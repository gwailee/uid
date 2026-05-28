# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28 — zero-extra-parameter vortex per Theory §14.2
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
# 本文件采用双许可证发布；商业使用须先获得苏州钧舵机器人有限公司书面授权，
# 商业授权联系: lig@jodell.cn

"""Vortex (curl) field from antisymmetric projection of FFN weights.

零额外参数的旋度场 —— 从 FFN 第一层权重的反对称分量构造，
严格符合论文 §14.2 "额外参数 = 0（掩码非参数化）" 的硬约束。

Theory:
    Helmholtz decomposition of the drift:  mu = -grad U + v.
    Detailed balance requires v == 0; intelligence requires v != 0.

    For two symmetric operators A^(1) and A^(2), the commutator
    [A^(1), A^(2)] is automatically antisymmetric — this IS the
    algebraic form of curl (Theorem 4.1, §4.4).

    Therefore, given ANY existing linear layer with weight W,
    the antisymmetric part
        J = (W - W^T) / 2
    is automatically a valid curl operator WITHOUT introducing any
    new parameters.

    The only learnable parameter per VortexField is one scalar
    ``log_temp_diff`` (interpreted as |T_1 - T_2|, the multi-bath
    temperature differential), giving exactly +1 parameter per layer
    in compliance with §14.2.

理论：任何已有线性层权重 W 的反对称分量 J = (W - W^T)/2 自动给出
合法的旋度算子，零额外参数。本类每层仅引入 1 个标量参数
``log_temp_diff``，与论文 §14.2 的零参数承诺一致。
"""

from __future__ import annotations

import warnings
from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn


class VortexField(nn.Module):
    """Zero-extra-parameter curl field via antisymmetric weight projection.

    通过 FFN 权重反对称投影实现的零额外参数旋度场。

    The curl operator J = (W - W^T) / 2 is rebuilt on every forward from
    a *non-owning reference* to an external weight tensor (typically
    ``FFN.0.weight``). This guarantees that ``state_dict`` and the
    optimiser see EXACTLY one extra learnable scalar per layer.

    旋度算子 J 在每次前向时由外部权重的非拥有引用实时构造，
    保证 ``state_dict`` 与优化器看到的额外可学习参数仅 1 个标量。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        weight_ref: Optional[nn.Parameter] = None,
    ) -> None:
        """Initialise the parameter-free vortex field.

        Args:
            hidden_size: Feature dimension. 隐藏维度。
            weight_ref:  Reference to an external weight tensor (e.g.
                         ``FFN.0.weight``). The curl is built from its
                         antisymmetric part — no new matrix parameter
                         is introduced.
                         When ``None``, the layer DEGRADES to zero curl
                         and emits a runtime warning — this preserves
                         backward compatibility but loses the curl term.
                         外部权重的非拥有引用；若为 None，旋度退化为零
                         （向后兼容但失去旋度项），并发出警告。
        """
        super().__init__()
        if hidden_size <= 0:
            raise ValueError(
                f"hidden_size must be positive, got {hidden_size}"
            )
        self.hidden_size: int = int(hidden_size)

        # NON-OWNING reference; do NOT register as parameter / buffer
        # to avoid double-counting in optimiser and checkpoint.
        # 非拥有引用；不注册为参数或 buffer，避免被优化器 / 检查点重复计数。
        self._weight_ref: Optional[nn.Parameter] = weight_ref

        if weight_ref is None:
            warnings.warn(
                "VortexField initialised without weight_ref; the curl "
                "term will be ZERO. Pass an external weight tensor "
                "(e.g. FFN[0].weight) to enable zero-extra-parameter "
                "curl per Theory §14.2.",
                RuntimeWarning,
            )

        # +1 learnable scalar: log temperature difference |T_1 - T_2|.
        # 唯一可学习参数：标量对数温差。
        self.log_temp_diff: nn.Parameter = nn.Parameter(torch.tensor(-1.0))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _antisymmetric(self) -> Optional[torch.Tensor]:
        """Build J = (W - W^T) / 2 on the fly from the referenced weight.

        实时构造反对称矩阵 J = (W - W^T) / 2，不引入新参数。

        Handles rectangular weights (e.g. FFN expansion to 4H) by taking
        the top-left (H, H) square sub-block.

        Returns:
            Antisymmetric matrix of shape (H, H), or ``None`` if no
            ``weight_ref`` was provided.
        """
        if self._weight_ref is None:
            return None
        w = self._weight_ref
        # Handle FFN expansion: take top-left (H, H) square sub-block.
        if w.shape[0] != w.shape[1]:
            min_dim = min(w.shape[0], w.shape[1], self.hidden_size)
            w_sq = w[:min_dim, :min_dim]
        else:
            w_sq = w
        # Antisymmetric part automatically satisfies J = -J^T.
        return 0.5 * (w_sq - w_sq.transpose(-2, -1))

    # ------------------------------------------------------------------
    # Public forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Compute the curl contribution v(phi) = temp_diff * J @ x.

        Args:
            x: Input tensor of shape (B, S, H). 输入张量。

        Returns:
            ``(vortex, info)`` where ``vortex`` has shape (B, S, H) and
            ``info`` is a dictionary of detached diagnostic scalars
            (safe to log without touching the autograd graph).
        """
        if x.shape[-1] != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, "
                f"got {x.shape[-1]}"
            )

        j = self._antisymmetric()
        if j is None:
            # Degrade gracefully: zero curl, but still log diagnostics.
            vortex = torch.zeros_like(x)
            info: Dict[str, float] = {
                "vortex_norm": 0.0,
                "temp_diff": float(torch.exp(self.log_temp_diff).item()),
                "vortex_active": 0.0,
                "antisym_residual": 0.0,
            }
            return vortex, info

        # v = temp_diff * J @ x  (broadcast over batch & sequence dims).
        # x: (B, S, H); J: (H, H); out: (B, S, H).
        # We multiply x @ J^T to keep PyTorch's row-major linear-layer
        # convention (equivalent to (J @ x^T)^T per token).
        temp_diff = torch.exp(self.log_temp_diff)
        vortex = temp_diff * torch.matmul(x, j.transpose(-2, -1))

        # Detached diagnostics; safe for logging on hot path.
        with torch.no_grad():
            info = {
                "vortex_norm": float(vortex.detach().norm().item()),
                "temp_diff": float(temp_diff.detach().item()),
                "vortex_active": 1.0,
                # Should be ≈ 0 if J truly antisymmetric.
                "antisym_residual": float(
                    (j + j.transpose(-2, -1)).abs().max().item()
                ),
            }
        return vortex, info
