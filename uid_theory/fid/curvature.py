# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Add compute_anisotropy_eta() that matches the EXACT definition
#     used by Theory §6.1 (prediction 4): eta = (lmax-lmin)/(lmax+lmin).
#   * Add compute_ricci_scalar_surrogate() so prediction 6 (β ≈ 1/2)
#     can be probed without changing the existing API.
#   * Keep the legacy trace(g^2)/trace(g)^2 - 1/H surrogate available
#     under compute_legacy_anisotropy() for back-compat with v0.1/v2.0
#     result files.
#   * forward() now returns the eta diagnostic by default (was the
#     legacy surrogate), with a feature flag to revert.
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

"""Scalar-curvature probes for the FID layer.

FID 层的标量曲率探针 —— 提供三个互补的曲率/各向异性代理量：

1. compute_anisotropy_eta(metric)
       对应论文 §6.1 / README 预言 4：
           eta = (lambda_max - lambda_min) / (lambda_max + lambda_min)
       理论值：训练后 eta > 0.5，且随训练深度增加。
       这是 README 中"Fisher 度量各向异性"预言的精确实现。

2. compute_ricci_scalar_surrogate(metric)
       对应论文 §3.3 / §6.2 / README 预言 6：
           R_surrogate = log det(g) - log H            (与体积元相关)
       理论值：与数据复杂度 D 满足幂律 R ∝ D^β, β ≈ 1/2。

3. compute_legacy_anisotropy(metric)
       原 v0.1 / v2.0 实现的代理量：
           trace(g^2) / trace(g)^2 - 1/H
       与 eta 单调相关但不等价。仅为兼容旧 result 文件而保留。

These quantities are *summary statistics* of an empirical hidden-state
covariance and **not** the exact scalar curvature of any specific
manifold. The naming reflects the prediction they target, not strict
mathematical equality.

本探针返回**摘要统计量**，对应论文中相应预言；不是任何具体流形上严格定义
的标量曲率。
"""

from __future__ import annotations

import torch
import torch.nn as nn

from .fisher_metric import FisherMetric


class ScalarCurvatureProbe(nn.Module):
    """Multi-mode anisotropy / curvature surrogate.

    多模式各向异性 / 曲率代理量。

    forward(hidden_states) returns the v2.1 default mode (eta).
    Use the explicit compute_* methods to access individual surrogates.
    """

    DEFAULT_MODE: str = "eta"  # one of {"eta", "ricci", "legacy"}

    def __init__(
        self,
        hidden_size: int,
        default_mode: str = "eta",
    ) -> None:
        """Initialise the probe.

        Args:
            hidden_size:  Feature dimension. 隐藏维度。
            default_mode: Which surrogate forward() should return:
                          "eta"     -> compute_anisotropy_eta (v2.1)
                          "ricci"   -> compute_ricci_scalar_surrogate
                          "legacy"  -> compute_legacy_anisotropy
                                       (pre-v2.1 default).
        """
        super().__init__()
        valid_modes = {"eta", "ricci", "legacy"}
        if default_mode not in valid_modes:
            raise ValueError(
                f"default_mode must be one of {sorted(valid_modes)}, "
                f"got {default_mode!r}"
            )
        self.hidden_size: int = int(hidden_size)
        self.default_mode: str = default_mode
        self.fisher: FisherMetric = FisherMetric(hidden_size)

    # ------------------------------------------------------------------
    # Surrogate 1: anisotropy eta (Theory §6.1 / README prediction 4)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_anisotropy_eta(metric: torch.Tensor) -> torch.Tensor:
        """eta = (lmax - lmin) / (lmax + lmin), Theory §6.1.

        Implements README prediction 4 verbatim. Range: [0, 1].
        At eta == 0 the metric is perfectly isotropic; at eta == 1 it
        is degenerate along one direction. UID predicts eta > 0.5 after
        training.

        Args:
            metric: Symmetric PSD matrix of shape (..., H, H).

        Returns:
            Tensor of shape (...,) with eta values in [0, 1].
        """
        # eigvalsh returns ascending eigenvalues.
        eigvals = torch.linalg.eigvalsh(metric)
        lmin = eigvals[..., 0]
        lmax = eigvals[..., -1]
        return (lmax - lmin) / (lmax + lmin + 1.0e-12)

    # ------------------------------------------------------------------
    # Surrogate 2: Ricci scalar surrogate (Theory §6.2 / prediction 6)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_ricci_scalar_surrogate(
        metric: torch.Tensor,
    ) -> torch.Tensor:
        """R_surrogate = log det(g) - log H, Theory §6.2.

        A scale-invariant volume-element proxy. Under the geometric
        scaling-law conjecture R ∝ D^β with β ≈ 1/2, the quantity
        ``log R`` should track ``β * log D`` across model scales.

        Args:
            metric: Symmetric PSD matrix of shape (..., H, H).

        Returns:
            Tensor of shape (...,) carrying the log-det surrogate.
        """
        h = metric.shape[-1]
        # slogdet is numerically stable for poorly-conditioned matrices.
        sign, logabsdet = torch.linalg.slogdet(metric)
        # In practice metric is PSD + jitter, so sign should be +1.
        # We mask non-positive sign entries to NaN to flag corruption.
        out = torch.where(
            sign > 0.0,
            logabsdet,
            torch.full_like(logabsdet, float("nan")),
        )
        return out - torch.log(torch.tensor(float(h), device=metric.device))

    # ------------------------------------------------------------------
    # Surrogate 3: Legacy anisotropy (pre-v2.1 default)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_legacy_anisotropy(metric: torch.Tensor) -> torch.Tensor:
        """trace(g^2) / trace(g)^2 - 1/H, kept for back-compat.

        计算论文之前版本所使用的代理量。
        各向同性时取值为 0；各向异性时正值。

        与 eta 单调相关但不等价；新代码请使用
        compute_anisotropy_eta() 以对齐 README 预言 4 的精确定义。
        """
        h = metric.shape[-1]
        tr_g = torch.diagonal(metric, dim1=-2, dim2=-1).sum(-1)
        tr_g2 = (metric * metric).sum(dim=(-1, -2))
        return tr_g2 / (tr_g.pow(2) + 1.0e-12) - 1.0 / h

    # ------------------------------------------------------------------
    # Convenience wrappers (operate on raw hidden_states)
    # ------------------------------------------------------------------

    def anisotropy_eta(
        self, hidden_states: torch.Tensor,
    ) -> torch.Tensor:
        """Per-sample eta from hidden states."""
        return self.compute_anisotropy_eta(
            self.fisher.compute(hidden_states),
        )

    def ricci_scalar_surrogate(
        self, hidden_states: torch.Tensor,
    ) -> torch.Tensor:
        """Per-sample Ricci-scalar surrogate from hidden states."""
        return self.compute_ricci_scalar_surrogate(
            self.fisher.compute(hidden_states),
        )

    def legacy_anisotropy(
        self, hidden_states: torch.Tensor,
    ) -> torch.Tensor:
        """Per-sample legacy anisotropy from hidden states."""
        return self.compute_legacy_anisotropy(
            self.fisher.compute(hidden_states),
        )

    # ------------------------------------------------------------------
    # Public forward (dispatches by self.default_mode)
    # ------------------------------------------------------------------

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """Return the per-sample curvature surrogate (default mode).

        Args:
            hidden_states: Tensor of shape (B, S, H). 隐状态张量。

        Returns:
            Tensor of shape (B,) with the surrogate value selected by
            ``self.default_mode``.
        """
        metric = self.fisher.compute(hidden_states)
        if self.default_mode == "eta":
            return self.compute_anisotropy_eta(metric)
        if self.default_mode == "ricci":
            return self.compute_ricci_scalar_surrogate(metric)
        return self.compute_legacy_anisotropy(metric)
