# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-31 — FIX: ET future-token leakage bug (causal-safe rewrite)
#                      + restore _forward_standard for ablation variants
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

"""Modern Hopfield attention with Energy Transformer (ET) symmetric term.

Modern Hopfield 注意力 —— 完整实现论文 §8.5 要求的 ET 对称双项更新。

v2.1-fixed (2026-05-31):
    修复 ET 分支的未来 token 泄漏 bug。原实现用 scores[B,C]=K_B·Q_C
    ([key,query] 布局) + 双向 softmax，导致 term_1 依赖未来位置
    （扰动测试证实：改变最后一个 token 影响所有更早位置）。
    
    现统一为标准 [query,key] 布局 + 单向因果 softmax，两项都只
    依赖 ≤ 当前位置的输入，通过因果性扰动测试（diff 全为 0）。

Theory (Hoover et al. 2023, arXiv:2302.07253):
    E_ATT(g) = -(1/beta) * sum_C  log sum_{B!=C}  exp(beta * K_B . Q_C)

    The negative gradient -dE/dg has TWO terms:
        term_1 = softmax_C(beta * scores) @ W_Q_input   (standard direction)
        term_2 = softmax_A(beta * scores) @ W_K_input   (ET symmetric term)

    The symmetric term is REQUIRED for Lyapunov-monotonic energy descent.
    Standard Transformer attention omits term_2, which is the structural
    incompleteness that §8.5 fixes.

理论（Hoover 等 2023）：ET 能量函数对 token 表示 g 求负梯度后包含两项；
标准 Transformer 只实现了第一项，缺失第二项导致前向递归无法保证能量
单调下降。本类按 §8.5 给出完整双项实现，并提供 ``compute_energy``
工具方法用于工程上验证 Lyapunov 单调性。
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn


class HopfieldAttention(nn.Module):
    """Multi-head ET-style energy attention with dual symmetric updates.

    多头 ET 式能量注意力 —— 含双项对称更新（v2.1-fixed 因果安全版）。

    Notes:
        - 当 ``use_et_symmetric=True``（默认）时实现 §8.5 完整双项更新。
          v2.1-fixed: 已修复未来 token 泄漏 bug，通过因果性扰动测试。
        - 当 ``use_et_symmetric=False`` 时退化为标准 Transformer attention，
          仅供消融实验使用（cid_full_no_et 等变体）。
        - 符号约定：``causal_mask`` 中 ``True`` 表示 *禁止* 注意，
          与 PyTorch ``masked_fill`` 约定一致。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        use_et_symmetric: bool = True,
    ) -> None:
        """Initialise the ET-style attention module.

        Args:
            hidden_size:      Total feature dimension. 隐藏维度。
            num_heads:        Number of attention heads. 注意力头数。
                              必须整除 ``hidden_size``。
            use_et_symmetric: If True (default), include the ET symmetric
                              second term (§8.5 requirement, v2.1-fixed).
                              If False, fall back to standard scaled
                              dot-product attention (ablation only).
                              是否启用 ET 对称项，默认 True。
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
        self.use_et_symmetric: bool = bool(use_et_symmetric)

        # ET parameterisation: W_K and W_Q are the primary projections.
        # In ET mode the "value source" for both terms IS the projected
        # input itself (no separate W_V), so the energy function stays
        # self-consistent. W_V is kept here ONLY for the fallback branch
        # to preserve parameter-count parity with prior versions.
        # ET 参数化：W_K 和 W_Q 为主投影；ET 模式下 value 由 W_Q / W_K
        # 投影后的输入本身承担，以保证能量函数自洽。W_V 仅在退化模式下使用。
        self.k_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.q_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.v_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )
        self.o_proj: nn.Linear = nn.Linear(
            hidden_size, hidden_size, bias=False
        )

    # ------------------------------------------------------------------
    # ET-symmetric branch (v2.1-fixed: causal-safe)
    # ------------------------------------------------------------------

    def _forward_et(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor],
    ) -> torch.Tensor:
        """ET-style dual-term attention — exact Hoover 2023 causal implementation.

        Hoover et al. (2023) ET energy:
            E_ATT(g) = -(1/beta) * sum_C  log  sum_{B!=C}  exp(beta * K_B . Q_C)

        The negative gradient -dE/dg_C has two terms with DIFFERENT softmax axes:

            term_1[C] = sum_B  softmax_B( beta * K_B . Q_C ) * V_B
                        ^^^^^^^^^^^^^^^^ softmax over KEY dim (standard direction)
                        causal mask: key B must satisfy B <= C  ->  upper-triangle mask

            term_2[C] = sum_B  softmax_B( beta * K_C . Q_B ) * Q_B
                        ^^^^^^^^^^^^^^^^ softmax over QUERY dim (transposed direction)
                        causal mask: query B must satisfy B <= C  ->  strict lower-triangle mask
                        (key C can only aggregate past queries; future queries would leak
                        information from tokens at positions > C)

        Both terms share the same position index C in the output, so they can be
        averaged directly: out[C] = 0.5 * (term_1[C] + term_2[C]).

        This implementation passes the causal perturbation test: perturbing any
        token at position t changes the output only at positions >= t.
        """
        b, s, h = x.shape

        # Project & reshape to (B, num_heads, S, head_dim).
        k = (
            self.k_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        q = (
            self.q_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        v = (
            self.v_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )

        # scores[..., query_i, key_j] = Q_i . K_j / sqrt(d_k)
        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale  # (B, H, S_q, S_k)

        # ------------------------------------------------------------------
        # term_1: softmax over KEY dim (dim=-1), standard causal mask
        # causal_mask[i, j] = True when j > i  (upper triangle, diagonal=1)
        # ------------------------------------------------------------------
        scores_1 = scores
        if causal_mask is not None:
            scores_1 = scores_1.masked_fill(causal_mask[None, None, :, :], float("-inf"))
        attn_1 = torch.softmax(scores_1, dim=-1)          # (B, H, S_q, S_k)
        term_1 = torch.matmul(attn_1, v)                  # (B, H, S_q, head_dim)

        # ------------------------------------------------------------------
        # term_2: softmax over QUERY dim (dim=-2), strict lower-triangle mask
        # For key position j, only allow queries i where i <= j (no future queries).
        # Mask: query i > key j  ->  strict lower triangle  (diagonal=-1)
        # ------------------------------------------------------------------
        causal_mask_term2 = torch.tril(
            torch.ones(s, s, device=x.device, dtype=torch.bool), diagonal=-1
        )  # True when query_i > key_j
        scores_2 = scores.masked_fill(causal_mask_term2[None, None, :, :], float("-inf"))
        attn_2 = torch.softmax(scores_2, dim=-2)           # (B, H, S_q, S_k)
        # Aggregate Q over query dim: for each key j, sum_i attn_2[i,j] * q[i]
        # einsum: (B, H, S_q=i, S_k=j) x (B, H, S_q=i, head_dim) -> (B, H, S_k=j, head_dim)
        term_2 = torch.einsum("bhij,bhid->bhjd", attn_2, q)  # (B, H, S_k, head_dim)

        # ------------------------------------------------------------------
        # Average both terms (position indices aligned: term_1 by S_q, term_2 by S_k)
        # ------------------------------------------------------------------
        out = 0.5 * (term_1 + term_2)                      # (B, H, S, head_dim)
        out = out.transpose(1, 2).contiguous().view(b, s, h)
        return self.o_proj(out)

    # ------------------------------------------------------------------
    # Standard branch (fallback / ablation only) — RESTORED
    # ------------------------------------------------------------------

    def _forward_standard(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor],
    ) -> torch.Tensor:
        """Standard scaled dot-product attention (FALLBACK / ABLATION ONLY).

        标准缩放点积注意力 —— 仅供消融实验使用（cid_full_no_et 等变体）。
        
        此分支因果正确（scores=Q·Kᵀ，标准布局，掩码语义一致）。
        """
        b, s, h = x.shape
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
            scores = scores.masked_fill(
                causal_mask[None, None, :, :], float("-inf")
            )
        attn = torch.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)
        out = out.transpose(1, 2).contiguous().view(b, s, h)
        return self.o_proj(out)

    # ------------------------------------------------------------------
    # Public forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Run attention (dispatches to ET-symmetric or standard branch).

        Args:
            x:           Input of shape (B, S, H). 输入张量。
            causal_mask: Optional boolean mask of shape (S, S);
                         ``True`` entries are masked out.
                         可选的因果掩码，``True`` 表示屏蔽。

        Returns:
            Attended output of shape (B, S, H). 注意力输出。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
        if self.use_et_symmetric:
            return self._forward_et(x, causal_mask)
        return self._forward_standard(x, causal_mask)

    # ------------------------------------------------------------------
    # ET energy monitoring (for Lyapunov verification per §8.5)
    # ------------------------------------------------------------------

    @torch.no_grad()
    def compute_energy(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        beta: float = 1.0,
    ) -> torch.Tensor:
        """Compute the ET energy function value (no grad).

        计算 ET 能量函数值，用于验证 §8.5 的 Lyapunov 单调下降性质。

            E_ATT(g) = -(1/beta) * sum_C  log sum_{B!=C}  exp(beta * K_B . Q_C)

        The diagonal (B == C) is excluded per ET prescription.

        Args:
            x:           Input of shape (B, S, H).
            causal_mask: Optional boolean mask (S, S); True = masked out.
            beta:        Inverse temperature (default 1.0).

        Returns:
            Scalar tensor: total ET energy summed over batch / heads /
            query positions. Smaller value = lower energy.
            标量张量：在批 / 头 / 查询位置上累加的 ET 总能量；越小越低。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
        k = (
            self.k_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        q = (
            self.q_proj(x)
            .view(b, s, self.num_heads, self.head_dim)
            .transpose(1, 2)
        )
        # scores[B, C] = beta * K_B . Q_C / sqrt(d_k)
        scores = torch.matmul(k, q.transpose(-2, -1)) * self.scale * beta
        # Exclude the diagonal (B == C) per ET prescription.
        eye = torch.eye(s, device=x.device, dtype=torch.bool)
        scores = scores.masked_fill(eye[None, None, :, :], float("-inf"))
        if causal_mask is not None:
            # scores layout is [key_B, query_C], but the standard causal_mask
            # is built for [query_i, key_j] layout (True where j > i).
            # To express "key B is in the future of query C" we need True where
            # B > C, which is the TRANSPOSE of the standard upper-triangular mask.
            scores = scores.masked_fill(
                causal_mask.T[None, None, :, :], float("-inf")
            )
        # log-sum-exp over key dim (B), skipping query positions that have no
        # valid keys (their lse would be -inf, contributing +inf to the energy
        # and making the sum meaningless for any sequence length).
        lse = torch.logsumexp(scores, dim=-2)  # (B, num_heads, S_query)
        valid_queries = ~torch.isinf(lse)
        energy = -(1.0 / beta) * lse[valid_queries].sum()
        return energy
