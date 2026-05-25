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

"""FID layer: QID dynamics with a geometric probe and soft regulariser.

FID 主层：在 QID 基础上加入几何探针与软正则项。

The geometric pieces (Fisher metric, curvature surrogate) are *probes*,
not strict implementations of the FID field equation.  Their primary
role here is diagnostic and as a mild regulariser that discourages
extreme anisotropy in hidden-state representations.

几何组件 (Fisher 度量、曲率代理) 主要承担**诊断与软正则**角色，并非 FID
场方程的严格实现；它们的作用是抑制隐状态表示的极端各向异性。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn

from ..qid.qid_layer import QIDLayer
from .curvature import ScalarCurvatureProbe


class FIDLayer(nn.Module):
    """QID layer enriched with a curvature-based diagnostic probe.

    在 QID 层上叠加曲率诊断探针的 FID 主层。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        dropout: float = 0.1,
        curvature_weight: float = 0.0,
    ) -> None:
        """Initialise the FID layer.

        Args:
            hidden_size:      Feature dimension. 隐藏维度。
            num_heads:        Attention heads. 注意力头数。
            dropout:          FFN dropout. FFN dropout。
            curvature_weight: Strength of the soft curvature penalty
                              that the host model can read from
                              ``info['curvature_loss']``.
                              曲率软正则强度；外部模型可从 info 读取并加入损失。
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.qid: QIDLayer = QIDLayer(
            hidden_size=hidden_size,
            num_heads=num_heads,
            dropout=dropout,
        )
        self.curvature: ScalarCurvatureProbe = ScalarCurvatureProbe(
            hidden_size
        )
        self.curvature_weight: float = float(curvature_weight)

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Run one FID step.

        Args:
            x:           Input of shape (B, S, H). 输入。
            causal_mask: Optional causal mask. 可选因果掩码。

        Returns:
            Tuple ``(x_next, info)``. info contains all QID diagnostics
            plus ``'curvature'`` and ``'curvature_loss'``.
        """
        x_next, info = self.qid(x, causal_mask=causal_mask)
        curv = self.curvature(x_next)  # shape (B,)
        with torch.no_grad():
            info["curvature"] = float(curv.mean().item())
        if self.curvature_weight > 0.0:
            info["curvature_loss"] = (
                self.curvature_weight * curv.mean()
            )  # Tensor (1-d): host model may add to loss
        return x_next, info
