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

"""Modern Hopfield attention as the gradient of an exponential potential.

Modern Hopfield 网络势能与其对应的注意力机制。

Theory (Ramsauer et al. 2020):
    The continuous Hopfield potential
        ``U(x) = (1/2)||x||^2 - (1/beta) log sum_mu exp(beta * xi_mu . x)``
    has gradient
        ``-grad U(x) = softmax(beta * K x) V - x``
    which, up to the residual ``-x`` (absorbed by the residual stream),
    is exactly the scaled dot-product attention used in Transformers.

理论：连续 Hopfield 势能的梯度恰好给出 Transformer 的 scaled dot-product
attention，是"Attention 即物理学结果"这一论断的核心依据。
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn


class HopfieldAttention(nn.Module):
    """Multi-head scaled dot-product attention with explicit physical role.

    多头注意力；其物理意义是 modern Hopfield 势能的负梯度。

    Notes:
        We follow the convention ``True`` in ``causal_mask`` means
        *masked out* (i.e. forbidden to attend).  This matches PyTorch's
        ``masked_fill`` convention.
        约定：``causal_mask`` 中 ``True`` 表示禁止注意，与 PyTorch
        ``masked_fill`` 的约定一致。
    """

    def __init__(self, hidden_size: int = 768, num_heads: int = 8) -> None:
        """Initialise the attention module.

        Args:
            hidden_size: Total feature dimension. 隐藏维度。
            num_heads:   Number of attention heads. 注意力头数。
                         Must divide ``hidden_size`` evenly. 必须整除。
        """
        super().__init__()
        if hidden_size % num_heads != 0:
            raise ValueError(
                f"hidden_size ({hidden_size}) must be divisible by "
                f"num_heads ({num_heads})"
            )
        self.hidden_size: int = int(hidden_size)
        self.num_heads: int = int(num_heads)
        self.head_dim: int = hidden_size // num_heads
        # 1 / sqrt(d_k) factor stems from random-matrix theory; it keeps
        # the softmax inputs at a non-degenerate temperature.
        # 缩放因子源自随机矩阵理论，保持 softmax 处于合理温度。
        self.scale: float = 1.0 / math.sqrt(self.head_dim)

        self.q_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.k_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.v_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.o_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Run multi-head attention.

        Args:
            x:           Input of shape (B, S, H). 输入张量。
            causal_mask: Optional boolean mask of shape (S, S) where
                         ``True`` entries are *masked out*.
                         可选的因果掩码，``True`` 表示屏蔽。

        Returns:
            Attended output of shape (B, S, H). 注意力输出。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )

        # Project & reshape to (B, num_heads, S, head_dim).
        q = (
            self.q_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        k = (
            self.k_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        v = (
            self.v_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )

        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale
        if causal_mask is not None:
            # Broadcast over batch & heads.
            scores = scores.masked_fill(
                causal_mask[None, None, :, :], float("-inf")
            )
        attn = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)  # (B, num_heads, S, head_dim)
        out = out.transpose(1, 2).contiguous().view(b, s, h)
        return self.o_proj(out)
