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

"""Power-law memory kernel implemented as a depthwise causal conv.

亚欧姆幂律记忆核：以 depthwise 因果卷积实现，时间复杂度 O(S * L)。

The kernel is initialised as ``gamma(t) ~ t^(-alpha)`` with
``alpha in (0, 1)`` (sub-Ohmic regime).  ``alpha`` controls the depth
of long-range temporal correlations; smaller ``alpha`` -> longer memory.

理论：sub-Ohmic 谱 J(omega) ~ omega^s (s = 1 - 2*alpha 时间域上的对应)
给出长程时间依赖。``alpha`` 越小，记忆越长。
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class MemoryKernel(nn.Module):
    """Depthwise causal convolution with a power-law initial kernel.

    Depthwise 因果卷积；卷积核以幂律 ``t^(-alpha)`` 初始化并可被学习微调。

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

        # Build a normalised power-law kernel along the time axis.
        # 沿时间轴构造归一化幂律核。
        t = torch.arange(1, memory_length + 1, dtype=torch.float32)
        kernel = t.pow(-alpha)
        kernel = kernel / kernel.sum()
        kernel = kernel.flip(0)  # conv1d expects time-reversed kernel
        # Depthwise: shape (out_channels=H, in_channels/groups=1, L).
        kernel = (
            kernel[None, None, :]
            .expand(hidden_size, 1, memory_length)
            .contiguous()
        )
        self.kernel: nn.Parameter = nn.Parameter(kernel)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply the causal convolution along the time axis.

        Args:
            x: Tensor of shape (B, S, H). 输入张量。

        Returns:
            Tensor of shape (B, S, H), each output position is a
            causal weighted sum over the last ``memory_length`` inputs.
            因果加权后的张量。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
        # (B, S, H) -> (B, H, S) for conv1d.
        xt = x.transpose(1, 2)
        # Left-pad with zeros to keep the convolution strictly causal.
        # 左侧补零以保持严格因果。
        xt_padded = F.pad(xt, (self.memory_length - 1, 0))
        out = F.conv1d(xt_padded, self.kernel, groups=self.hidden_size)
        return out.transpose(1, 2)
