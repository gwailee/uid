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

"""Fisher information metric on hidden-state manifolds.

隐状态流形上的 Fisher 信息度量估算。

The exact Fisher information for a neural language model would require
gradients of log p(x|theta) w.r.t. every parameter; here we adopt a
*hidden-state empirical-covariance* surrogate that is cheap, batch-
local, and sufficient for the FID *probe* role.  This is **not** the
exact Fisher matrix on parameter space.

严格 Fisher 信息矩阵需对参数求梯度，开销巨大。本实现采用**隐状态经验
协方差**作为代理，仅用于 FID 几何探针的诊断角色，并非参数空间的严格
Fisher 矩阵。
"""

from __future__ import annotations

import torch
import torch.nn as nn


class FisherMetric(nn.Module):
    """Empirical-covariance surrogate of the Fisher metric.

    Fisher 度量的经验协方差代理。
    """

    def __init__(self, hidden_size: int, jitter: float = 1.0e-4) -> None:
        """Initialise the probe.

        Args:
            hidden_size: Feature dimension. 隐藏维度。
            jitter:      Diagonal regularisation. 对角抖动。
        """
        super().__init__()
        if hidden_size <= 0:
            raise ValueError(
                f"hidden_size must be positive, got {hidden_size}"
            )
        self.hidden_size: int = int(hidden_size)
        self.jitter: float = float(jitter)

    def compute(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """Return a (B, H, H) PSD matrix per sample.

        Args:
            hidden_states: Tensor of shape (B, S, H). 隐状态张量。

        Returns:
            Symmetric positive-definite metric tensor of shape (B, H, H).
            对称正定的度量张量。
        """
        if hidden_states.dim() != 3:
            raise ValueError(
                "hidden_states must have shape (B, S, H), got "
                f"{tuple(hidden_states.shape)}"
            )
        b, s, h = hidden_states.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
        centred = hidden_states - hidden_states.mean(dim=1, keepdim=True)
        cov = torch.einsum("bsi,bsj->bij", centred, centred) / max(s, 1)
        eye = torch.eye(h, device=cov.device, dtype=cov.dtype)
        return cov + self.jitter * eye[None]
