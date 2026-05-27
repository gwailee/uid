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

"""Scalar-curvature probe for the FID layer.

FID 层的标量曲率探针。

This probe returns a *summary statistic* that behaves qualitatively
like a scalar curvature: it grows when the empirical metric becomes
sharply anisotropic and shrinks when it is close to a scaled identity.
It is **not** a quantitative scalar curvature of any specific manifold.

本探针返回一个**摘要统计量**，定性上与标量曲率行为相近（各向异性强时变
大，接近各向同性时变小）。它**不是**任何具体流形上严格定义的标量曲率。
"""

from __future__ import annotations

import torch
import torch.nn as nn

from .fisher_metric import FisherMetric


class ScalarCurvatureProbe(nn.Module):
    """Anisotropy-based curvature surrogate.

    基于各向异性程度的曲率代理量。
    """

    def __init__(self, hidden_size: int) -> None:
        """Initialise the probe.

        Args:
            hidden_size: Feature dimension. 隐藏维度。
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.fisher: FisherMetric = FisherMetric(hidden_size)

    @staticmethod
    def _anisotropy(metric: torch.Tensor) -> torch.Tensor:
        """Compute trace(g^2) / trace(g)^2 - 1/H, a non-negative anisotropy.

        计算正比于各向异性强度的统计量。
        """
        h = metric.shape[-1]
        tr_g = torch.diagonal(metric, dim1=-2, dim2=-1).sum(-1)
        tr_g2 = (metric * metric).sum(dim=(-1, -2))
        # For an isotropic metric tr(g^2)/tr(g)^2 = 1/H exactly; we
        # subtract this so the probe vanishes for isotropic metrics.
        # 各向同性时取值为 0。
        return tr_g2 / (tr_g.pow(2) + 1.0e-12) - 1.0 / h

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """Return the per-sample curvature surrogate.

        Args:
            hidden_states: Tensor of shape (B, S, H). 隐状态张量。

        Returns:
            Tensor of shape (B,) with the curvature surrogate.
            形状 (B,) 的曲率代理标量。
        """
        metric = self.fisher.compute(hidden_states)
        return self._anisotropy(metric)
