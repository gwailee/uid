# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-06-23 (v2.3) — HONEST causal resolution of the ET symmetric term.
#   FINDING: Hoover et al. (2023)'s ET symmetric SECOND term is intrinsically
#   NON-CAUSAL. Its update for key position B aggregates over query positions
#   C (term_2(B) = sum_C softmax_C(scores)[C,B] * Q_C). Under autoregressive
#   masking the only consistent direction would let B depend on C >= B, i.e.
#   on FUTURE tokens — which BREAKS causality (verified: future-token leakage
#   ~0.11 in tests). The ET dual-softmax symmetry and autoregressive causality
#   are mathematically INCOMPATIBLE.
#
#   DECISION (route A, honest): in the causal-LM setting we DROP the
#   non-causal symmetric second term. With use_et_symmetric=True the module
#   keeps only the causal term_1, which in this regime coincides with standard
#   causal scaled dot-product attention. We therefore state plainly that the
#   §8.5 ET symmetric term is NOT realizable in a causal autoregressive model,
#   and that ET reduces to standard attention here. The faithful (non-causal)
#   ET remains available only for the non-causal / associative-memory regime
#   (not this codebase's causal LM), and compute_energy() is retained purely
#   as a diagnostic of the term_1 energy, NOT as a Lyapunov guarantee.

"""Modern Hopfield attention — honest causal treatment of the ET term.

关于 §8.5 ET 对称项的诚实结论
============================================================
Hoover et al. (2023) 的 ET 能量函数

    E_ATT(g) = -(1/beta) * sum_C log sum_{B!=C} exp(beta * K_B . Q_C)

其负梯度含两项；其中**对称第二项 term_2 本质上是非因果的**：
key 位置 B 的更新需要聚合 query 位置 C，且唯一自洽的方向是 C >= B
（即依赖未来 token）。在自回归因果 LM 中，这与因果性**数学上不可兼容**
（实测：保留 term_2 会造成约 0.11 的未来 token 泄漏）。

因此本实现采取诚实路线：在因果 LM 设置下**舍弃非因果的对称第二项**。
当 use_et_symmetric=True 时，仅保留因果安全的 term_1，此时它与标准因果
缩放点积注意力**一致**。换言之，**§8.5 的 ET 对称项在因果自回归模型中
不可实现，ET 在此退化为标准注意力**。忠实的（非因果）ET 仅适用于
非因果 / 联想记忆设置（非本仓库的因果 LM）。compute_energy() 仅作为
term_1 能量的工程诊断，**不构成 Lyapunov 单调下降的保证**。

符号约定：causal_mask 中 True 表示*禁止*注意，与 torch.masked_fill 一致。
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn


class HopfieldAttention(nn.Module):
    """Multi-head attention; ET symmetric term is dropped in the causal LM.

    多头注意力。因 ET 对称项在因果 LM 中不可实现，use_et_symmetric=True
    退化为因果安全的标准注意力（仅保留 term_1）。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        use_et_symmetric: bool = True,
        use_output_proj: bool = True,
    ) -> None:
        """Initialise the attention module.

        Args:
            hidden_size:      隐藏维度（必须被 num_heads 整除）。
            num_heads:        注意力头数。
            use_et_symmetric: 语义已更新：True（默认）启用"ET 因果分支"，
                              但因 ET 对称项非因果，该分支实际仅含因果安全的
                              term_1，等价于标准因果注意力。False 同样为标准
                              注意力（消融对照）。两者在因果 LM 下数值等价；
                              保留该开关仅为与历史接口、配置与参数命名兼容。
            use_output_proj:  是否施加 o_proj（默认 True，保持参数量对等）。
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
        self.scale: float = 1.0 / math.sqrt(self.head_dim)
        self.use_et_symmetric: bool = bool(use_et_symmetric)
        self.use_output_proj: bool = bool(use_output_proj)

        self.k_proj: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)
        self.q_proj: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)
        self.v_proj: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)
        self.o_proj: nn.Linear = nn.Linear(hidden_size, hidden_size, bias=False)

    def _attention(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor],
    ) -> torch.Tensor:
        """Causal scaled dot-product attention (the only causal-safe term).

        因果安全的标准缩放点积注意力。这是 ET term_1 在因果设置下的形式，
        也是 use_et_symmetric=True/False 共用的实现（ET 对称项已舍弃）。
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
        attn = torch.softmax(scores, dim=-1)  # 仅对 key 维(B)归一化, 严格因果
        out = torch.matmul(attn, v)           # 仅聚合 B<=C 的过去 token
        out = out.transpose(1, 2).contiguous().view(b, s, h)
        if self.use_output_proj:
            out = self.o_proj(out)
        return out

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Run attention.

        无论 use_et_symmetric 取何值，在因果 LM 下均执行因果安全的标准注意力
        （ET 对称项不可实现，已舍弃）。保留分支判断仅为日志/语义可读性。
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
        # use_et_symmetric=True 与 False 在因果 LM 下数值等价；统一走因果注意力。
        return self._attention(x, causal_mask)

    @torch.no_grad()
    def compute_energy(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        beta: float = 1.0,
    ) -> torch.Tensor:
        """Diagnostic ET term_1 energy (NOT a Lyapunov guarantee).

        诊断用 ET term_1 能量值；因果掩码下不保证单调下降。

            E(g) = -(1/beta) * sum_C log sum_{B<=C, B!=C} exp(beta * Q_C . K_B)
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, got {h}"
            )
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
        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale * beta  # [C,B]
        eye = torch.eye(s, device=x.device, dtype=torch.bool)
        scores = scores.masked_fill(eye[None, None, :, :], float("-inf"))
        if causal_mask is not None:
            scores = scores.masked_fill(
                causal_mask[None, None, :, :], float("-inf")
            )
        lse = torch.logsumexp(scores, dim=-1)  # over key dim B (causal)
        # 全 -inf 行（如首位置仅剩对角被排除）会得到 -inf，置 0 兜底。
        lse = torch.nan_to_num(lse, neginf=0.0)
        energy = -(1.0 / beta) * lse.sum()
        return energy
