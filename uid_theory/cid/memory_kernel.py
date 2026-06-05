# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-06-05
#   * FIX-1: Remove L-dependent normalisation.  The original code divided
#     the power-law kernel by its sum, making the most-recent weight shrink
#     as memory_length grew (L=32 -> 0.065, L=512 -> 0.009).  The kernel
#     now uses raw t^(-alpha) weights plus a single learnable log_scale
#     scalar so the *shape* is physically grounded and the *magnitude* is
#     learned independently of L.
#   * FIX-2: Integrate over velocity (finite difference dx) instead of raw
#     state x.  Theory (C5.3) requires -∫γ(t-s)·φ̇(s)ds.  In the
#     Euler-Maruyama discretisation φ̇(s) ≈ x_s - x_{s-1}.  The previous
#     code convolved over x (state), not dx (velocity), which is a
#     qualitatively different integral.  dx[:, 0, :] = 0 (no prior state
#     at the causal boundary), consistent with zero initial velocity.
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

"""Power-law memory kernel implemented as a depthwise causal conv.

亚欧姆幂律记忆核：以 depthwise 因果卷积实现，时间复杂度 O(S * L)。

The kernel is initialised as ``gamma(t) ~ t^(-alpha)`` with
``alpha in (0, 1)`` (sub-Ohmic regime).  ``alpha`` controls the depth
of long-range temporal correlations; smaller ``alpha`` -> longer memory.

理论：sub-Ohmic 谱 J(omega) ~ omega^s (s = 1 - 2*alpha 时间域上的对应)
给出长程时间依赖。``alpha`` 越小，记忆越长。

修复说明（v2.2）
-----------------
原版存在两处偏离理论的近似：

1. **归一化问题**：原代码将核除以其和（sum=1）。这导致增大 memory_length
   时最近步权重随之缩小（L=32 时 0.065，L=512 时 0.009），即改变感受野
   长度会改变记忆强度——物理上不自洽。修复：保留原始 t^(-alpha) 权重，
   另引入一个可学习的 log_scale 标量，形状由物理决定，幅度由训练决定。

2. **积分对象问题**：理论要求对速度 φ̇(s) 积分，即
   -∫γ(t-s)·φ̇(s)ds。原代码对状态 x 做卷积，相当于对位置而非速度积
   分，是不同的物理量。修复：在 forward 中先对 x 取有限差分 dx（速度的
   Euler-Maruyama 近似），再对 dx 做卷积。
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class MemoryKernel(nn.Module):
    """Depthwise causal convolution with a power-law initial kernel.

    Depthwise 因果卷积；卷积核以幂律 ``t^(-alpha)`` 初始化（非归一化），
    并附带可学习缩放因子 log_scale。积分在速度（有限差分）上执行。

    Attributes:
        hidden_size:    Feature dimension (groups). 隐藏维度。
        memory_length:  Receptive field length L. 卷积感受野长度。
        alpha:          Initial power-law exponent. 初始幂律指数。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        memory_length: int = 64,
        alpha: float = 0.3,
    ) -> None:
        """Initialise the memory kernel.

        Args:
            hidden_size:    Number of channels (groups). 通道数。
            memory_length:  Length of the causal receptive field.
                            因果感受野长度，应 >= 2。
            alpha:          Sub-Ohmic exponent in (0, 1).
                            亚欧姆指数，需在 (0, 1) 区间。
        """
        super().__init__()
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if memory_length < 2:
            raise ValueError(
                f"memory_length must be >= 2, got {memory_length}"
            )

        self.hidden_size: int = int(hidden_size)
        self.memory_length: int = int(memory_length)
        self.alpha: float = float(alpha)

        # FIX-1: Build an UN-normalised power-law kernel.
        # t=1 is the most recent step; t=L is the oldest step in the window.
        # Raw weight at t=1 is always 1.0^(-alpha)=1.0 regardless of L,
        # so memory_length no longer affects the per-step scale.
        #
        # 修复1：构造非归一化幂律核。t=1 对应最近一步，权重恒为 1.0，
        # 与感受野长度 L 无关，解决了原版中改变 L 即改变记忆强度的问题。
        t = torch.arange(1, memory_length + 1, dtype=torch.float32)
        kernel = t.pow(-alpha)            # shape (L,); NOT divided by sum
        kernel = kernel.flip(0)           # conv1d expects time-reversed order
        # Depthwise: shape (out_channels=H, in_channels/groups=1, L).
        kernel = (
            kernel[None, None, :]
            .expand(hidden_size, 1, memory_length)
            .contiguous()
        )
        self.kernel: nn.Parameter = nn.Parameter(kernel)

        # FIX-1 (cont.): Separate learnable log-scale so the optimiser can
        # adjust the overall damping strength without distorting the shape.
        # Initialised to log(1/L) so the initial effective magnitude is
        # comparable to the old normalised kernel.
        #
        # 修复1（续）：独立可学习对数缩放因子，使优化器可调整整体阻尼强度
        # 而不扭曲核的幂律形状。初始值 log(1/L) 使初始幅度与原归一化核相当。
        init_log_scale = -float(torch.tensor(memory_length).log())
        self.log_scale: nn.Parameter = nn.Parameter(
            torch.tensor(init_log_scale)
        )

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply the causal convolution over the velocity (finite diff) of x.

        Theory (C5.3) specifies -∫γ(t-s)·φ̇(s)ds, i.e. the memory
        integral is over the *velocity* of the state trajectory, not the
        state itself.  In the Euler-Maruyama discretisation,
        φ̇(s) ≈ x_s − x_{s−1}.  The first time step has no prior state,
        so dx[:, 0, :] = 0 (zero initial velocity at the causal boundary).

        理论要求对速度 φ̇(s) 积分（而非状态 x）。
        Euler-Maruyama 离散化：φ̇(s) ≈ x_s − x_{s-1}。
        第一步无前驱，令 dx[:, 0, :] = 0（因果边界处初速为零）。

        Args:
            x: Tensor of shape (B, S, H). 输入张量。

        Returns:
            Tensor of shape (B, S, H), each output position is a
            causal weighted sum of the last ``memory_length`` *velocity*
            steps, scaled by exp(log_scale).
            对速度的因果加权积分，乘以可学习缩放因子。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )

        # FIX-2: Compute finite-difference velocity dx = x_t - x_{t-1}.
        # dx[:, 0, :] = 0 (no predecessor at t=0).
        # 修复2：计算有限差分速度 dx；t=0 处无前驱，设为零。
        dx = torch.zeros_like(x)
        dx[:, 1:, :] = x[:, 1:, :] - x[:, :-1, :]

        # (B, S, H) -> (B, H, S) for conv1d.
        dxt = dx.transpose(1, 2)
        # Left-pad with zeros to keep the convolution strictly causal.
        # 左侧补零以保持严格因果。
        dxt_padded = F.pad(dxt, (self.memory_length - 1, 0))
        out = F.conv1d(dxt_padded, self.kernel, groups=self.hidden_size)

        # Apply learnable scale: exp(log_scale) is always positive.
        # 乘以可学习正缩放因子。
        return torch.exp(self.log_scale) * out.transpose(1, 2)
