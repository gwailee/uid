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

"""Berry-phase layer (classical emulation).

Berry 几何相位层（经典模拟版本）。

We pair the real channels of the hidden state into 2D blocks and
rotate each pair by an angle ``phi`` computed from a learnable U(1)
Berry connection.  This emulates the geometric phase pick-up of a
quantum state under adiabatic parameter transport.

理论：把隐状态相邻两维视为复数的实部/虚部对，按可学习的 U(1) Berry 联络
诱导一个角度，对每个二维子空间施加旋转。这是 Berry 相位在经典数值上的
最小近似实现。
"""

from __future__ import annotations

from typing import Tuple

import torch
import torch.nn as nn


class BerryPhaseLayer(nn.Module):
    """Apply per-pair U(1) rotation derived from a Berry connection.

    根据 Berry 联络给出的角度，对成对的特征维施加 U(1) 旋转。
    """

    def __init__(self, hidden_size: int) -> None:
        """Initialise the layer.

        Args:
            hidden_size: Feature dimension; must be even so we can pair
                         real/imag channels. 必须为偶数。
        """
        super().__init__()
        if hidden_size % 2 != 0:
            raise ValueError(
                f"hidden_size must be even for paired rotation, got "
                f"{hidden_size}"
            )
        self.hidden_size: int = int(hidden_size)
        self.half: int = hidden_size // 2
        # Linear map producing the per-pair phase angle.
        # 输出每对 (real, imag) 的旋转角。
        self.phase_proj: nn.Linear = nn.Linear(hidden_size, self.half)
        # Small init so the layer starts close to identity.
        # 初始接近恒等映射。
        nn.init.zeros_(self.phase_proj.bias)
        nn.init.normal_(self.phase_proj.weight, std=0.01)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Compute paired rotation and return output plus mean phase.

        Args:
            x: Input of shape (B, S, H). 输入。

        Returns:
            ``(y, phases)`` where ``y`` is the rotated tensor of the same
            shape and ``phases`` of shape (B, S, H/2) holds the angles.
            返回旋转后的张量与角度张量（用于监控）。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )

        x_real = x[..., : self.half]
        x_imag = x[..., self.half :]
        phases = self.phase_proj(x)  # (B, S, H/2)

        cos = torch.cos(phases)
        sin = torch.sin(phases)
        y_real = cos * x_real - sin * x_imag
        y_imag = sin * x_real + cos * x_imag
        y = torch.cat([y_real, y_imag], dim=-1)
        return y, phases
