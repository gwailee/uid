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

"""A minimal Transformer baseline that mirrors the UID model API.

最小化 Transformer 基线模型；API 与 UID 模型保持一致以便对照实验。
"""

from __future__ import annotations

from typing import List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers.modeling_outputs import CausalLMOutputWithPast


class _Block(nn.Module):
    """A single pre-norm Transformer block.

    单个 pre-norm Transformer 块。
    """

    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.norm1: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.attn: nn.MultiheadAttention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
            bias=False,
        )
        self.norm2: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.ffn: nn.Sequential = nn.Sequential(
            nn.Linear(hidden_size, 4 * hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_size, hidden_size),
            nn.Dropout(dropout),
        )

    def forward(
        self, x: torch.Tensor, causal_mask: torch.Tensor
    ) -> torch.Tensor:
        """Run the block.

        Args:
            x:           Input (B, S, H). 输入。
            causal_mask: Float mask (S, S) with ``-inf`` on masked
                         positions (``MultiheadAttention`` convention).
                         浮点掩码，被屏蔽位置为 ``-inf``。
        """
        h = self.norm1(x)
        attn_out, _ = self.attn(
            h, h, h, attn_mask=causal_mask, need_weights=False
        )
        x = x + attn_out
        x = x + self.ffn(self.norm2(x))
        return x


class TinyTransformerLM(nn.Module):
    """Compact Transformer language model for baseline comparison.

    紧凑型 Transformer 语言模型，用作对照基线。
    """

    def __init__(
        self,
        vocab_size: int,
        hidden_size: int,
        num_layers: int,
        num_heads: int,
        max_position_embeddings: int,
        dropout: float = 0.1,
    ) -> None:
        """Initialise the model.

        Args:
            vocab_size:              Vocabulary size. 词表大小。
            hidden_size:             Feature dimension. 隐藏维度。
            num_layers:              Number of layers. 层数。
            num_heads:               Attention heads. 注意力头数。
            max_position_embeddings: Max sequence length. 最大序列长度。
            dropout:                 Dropout. Dropout 概率。
        """
        super().__init__()
        if hidden_size % num_heads != 0:
            raise ValueError(
                f"hidden_size ({hidden_size}) must be divisible by "
                f"num_heads ({num_heads})"
            )
        self.vocab_size: int = int(vocab_size)
        self.hidden_size: int = int(hidden_size)
        self.max_position_embeddings: int = int(max_position_embeddings)

        self.tok_emb: nn.Embedding = nn.Embedding(vocab_size, hidden_size)
        self.pos_emb: nn.Embedding = nn.Embedding(
            max_position_embeddings, hidden_size
        )
        self.drop: nn.Dropout = nn.Dropout(dropout)

        self.blocks: nn.ModuleList = nn.ModuleList(
            [
                _Block(hidden_size, num_heads, dropout)
                for _ in range(num_layers)
            ]
        )
        self.norm: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.lm_head: nn.Linear = nn.Linear(
            hidden_size, vocab_size, bias=False
        )
        # Tie input and output embeddings.
        # 输入与输出 embedding 共享权重。
        self.lm_head.weight = self.tok_emb.weight

        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        """Initialise weights with small Gaussian noise.

        小尺度高斯初始化。
        """
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, std=0.02)

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
        output_hidden_states: bool = False,
        **kwargs,
    ) -> CausalLMOutputWithPast:
        """Run the LM.

        Args:
            input_ids:            Token ids (B, S). Token id。
            labels:               Targets (B, S); use -100 to ignore.
                                   目标序列，-100 表示忽略。
            output_hidden_states: Return per-layer hidden states.
                                   是否返回各层隐状态。

        Returns:
            ``CausalLMOutputWithPast`` (loss, logits, hidden_states).
        """
        b, s = input_ids.shape
        if s > self.max_position_embeddings:
            raise ValueError(
                f"sequence length {s} exceeds "
                f"max_position_embeddings={self.max_position_embeddings}"
            )
        pos = torch.arange(s, device=input_ids.device)
        x = self.drop(self.tok_emb(input_ids) + self.pos_emb(pos)[None])

        # MultiheadAttention expects a float mask with -inf in masked
        # positions; we build a strictly upper-triangular -inf mask.
        # nn.MultiheadAttention 需要浮点掩码，被屏蔽位置为 -inf。
        causal_mask = torch.zeros(s, s, device=x.device, dtype=x.dtype)
        causal_mask = causal_mask.masked_fill(
            torch.triu(
                torch.ones(s, s, device=x.device, dtype=torch.bool),
                diagonal=1,
            ),
            float("-inf"),
        )

        hidden_list: List[torch.Tensor] = []
        for block in self.blocks:
            x = block(x, causal_mask)
            if output_hidden_states:
                hidden_list.append(x)
        x = self.norm(x)
        logits = self.lm_head(x)

        loss = None
        if labels is not None:
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, self.vocab_size),
                shift_labels.view(-1),
                ignore_index=-100,
            )

        return CausalLMOutputWithPast(
            loss=loss,
            logits=logits,
            past_key_values=None,
            hidden_states=(
                tuple(hidden_list) if output_hidden_states else None
            ),
            attentions=None,
        )
