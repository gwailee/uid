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

"""Vortex (curl) field from two-bath coupling.

双热浴旋度场：v(phi) = (T1 - T2) [W1, W2] phi 的可学习实现。

Theory:
    The Helmholtz decomposition of the drift in the generalised Langevin
    equation gives ``mu = -grad U + v``.  Detailed balance requires
    ``v == 0``.  When the system is coupled to two heat baths with
    different temperatures via non-commuting operators ``W1`` and
    ``W2``, the resulting steady state has a non-vanishing probability
    current proportional to the commutator ``[W1, W2]``.

理论：广义 Langevin 方程漂移项的 Helmholtz 分解给出 ``mu = -grad U + v``。
细致平衡要求 ``v == 0``。当系统通过非对易算符 ``W1, W2`` 耦合到温度不同
的两个热浴时，稳态概率流非零，方向正比于对易子 ``[W1, W2]``。
"""

from __future__ import annotations

from typing import Dict, Tuple

import torch
import torch.nn as nn


class VortexField(nn.Module):
    """Learnable curl field implemented via a commutator structure.

    通过对易子结构实现的可学习旋度场。

    The output is ``temp_diff * (W1(W2 x) - W2(W1 x))`` where ``W1`` and
    ``W2`` are two independent linear maps and ``temp_diff = exp(log_t)``
    is a non-negative learnable scalar interpreted as ``|T1 - T2|``.

    输出为 ``temp_diff * (W1 W2 x - W2 W1 x)``，其中 ``W1, W2`` 是两个
    独立线性变换，``temp_diff = exp(log_t)`` 是非负的可学习温差标量。
    """

    def __init__(self, hidden_size: int = 768) -> None:
        """Initialise the vortex field.

        Args:
            hidden_size: Feature dimension. 隐藏维度。
        """
        super().__init__()
        if hidden_size <= 0:
            raise ValueError(
                f"hidden_size must be positive, got {hidden_size}"
            )
        self.hidden_size: int = int(hidden_size)

        self.w1: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)
        self.w2: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)
        # log-parameterised temperature difference, so |T1 - T2| >= 0.
        # 用 log 参数化保证温差非负。
        self.log_temp_diff: nn.Parameter = nn.Parameter(torch.tensor(-1.0))

        # Modest initial gain to keep the commutator small at init.
        # 适度的初始化增益，使初始旋度较小，便于训练稳定起步。
        nn.init.xavier_uniform_(self.w1.weight, gain=0.5)
        nn.init.xavier_uniform_(self.w2.weight, gain=0.5)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Compute the curl contribution to dphi/dt.

        Args:
            x: Input tensor of shape (B, S, H). 输入张量。

        Returns:
            A tuple ``(vortex, info)`` where ``vortex`` is the curl
            contribution and ``info`` is a dictionary of diagnostic
            scalars (already detached, safe to log).
            返回旋度贡献张量以及诊断标量字典（已 detach）。
        """
        # Commutator [W1, W2] x = W1(W2 x) - W2(W1 x).
        w1x = self.w1(x)
        w2x = self.w2(x)
        commutator = self.w1(w2x) - self.w2(w1x)

        temp_diff = torch.exp(self.log_temp_diff)
        vortex = temp_diff * commutator

        # Detach diagnostics to avoid forcing GPU->CPU sync on hot path.
        # 仅在需要时计算，且 detach 避免热路径同步。
        with torch.no_grad():
            info: Dict[str, float] = {
                "vortex_norm": float(vortex.detach().norm().item()),
                "temp_diff": float(temp_diff.detach().item()),
            }
        return vortex, info
