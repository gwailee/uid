# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Modern Transformer baseline with current best practices.

This replaces the weak `TinyTransformerLM` baseline of v0.1. The 
modern baseline uses:
- RoPE (Rotary Position Embedding)
- RMSNorm (instead of LayerNorm)
- SwiGLU FFN (instead of GELU)
- Pre-norm architecture

These are the standard choices in modern LLMs (Llama-2/3, Mistral, 
Qwen, etc.) and provide a fair benchmark against which UID must 
demonstrate superiority.
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers.modeling_outputs import CausalLMOutputWithPast


class RMSNorm(nn.Module):
    """Root mean square layer normalization (Zhang & Sennrich 2019)."""
    
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rms = torch.sqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return self.weight * (x / rms)


def precompute_rope_freqs(
    head_dim: int, max_seq_len: int, theta: float = 10000.0
) -> tuple[torch.Tensor, torch.Tensor]:
    """Precompute RoPE cos/sin frequencies."""
    freqs = 1.0 / (
        theta ** (torch.arange(0, head_dim, 2).float() / head_dim)
    )
    t = torch.arange(max_seq_len).float()
    freqs = torch.outer(t, freqs)
    return torch.cos(freqs), torch.sin(freqs)


def apply_rope(
    x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor
) -> torch.Tensor:
    """Apply rotary position embedding."""
    # x: (B, H, S, D)
    seq_len = x.shape[-2]
    cos = cos[:seq_len].unsqueeze(0).unsqueeze(0)  # (1, 1, S, D/2)
    sin = sin[:seq_len].unsqueeze(0).unsqueeze(0)
    
    x1, x2 = x.chunk(2, dim=-1)
    x_rotated = torch.cat([-x2, x1], dim=-1)
    return x * torch.cat([cos, cos], dim=-1) + x_rotated * torch.cat(
        [sin, sin], dim=-1
    )


class ModernAttention(nn.Module):
    """Multi-head attention with RoPE."""
    
    def __init__(self, hidden_size: int, num_heads: int, max_seq_len: int):
        super().__init__()
        assert hidden_size % num_heads == 0
        self.hidden_size = hidden_size
        self.num_heads = num_heads
        self.head_dim = hidden_size // num_heads
        self.scale = 1.0 / math.sqrt(self.head_dim)
        
        self.q_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.k_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.v_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        self.o_proj = nn.Linear(hidden_size, hidden_size, bias=False)
        
        cos, sin = precompute_rope_freqs(self.head_dim, max_seq_len)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
    
    def forward(
        self, x: torch.Tensor, causal_mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        b, s, h = x.shape
        
        q = self.q_proj(x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(b, s, self.num_heads, self.head_dim).transpose(1, 2)
        
        # Apply RoPE to q and k
        q = apply_rope(q, self.rope_cos, self.rope_sin)
        k = apply_rope(k, self.rope_cos, self.rope_sin)
        
        # Scaled dot-product attention
        scores = torch.matmul(q, k.transpose(-2, -1)) * self.scale
        if causal_mask is not None:
            scores = scores.masked_fill(
                causal_mask[None, None, :, :], float("-inf")
            )
        attn = F.softmax(scores, dim=-1)
        out = torch.matmul(attn, v)
        
        out = out.transpose(1, 2).contiguous().view(b, s, h)
        return self.o_proj(out)


class SwiGLU(nn.Module):
    """SwiGLU feed-forward (Shazeer 2020)."""
    
    def __init__(self, hidden_size: int, intermediate_size: Optional[int] = None):
        super().__init__()
        if intermediate_size is None:
            # Llama convention: ~2/3 * 4 * hidden_size, rounded to multiple of 256
            intermediate_size = int(hidden_size * 8 / 3)
            intermediate_size = ((intermediate_size + 255) // 256) * 256
        
        self.gate_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.up_proj = nn.Linear(hidden_size, intermediate_size, bias=False)
        self.down_proj = nn.Linear(intermediate_size, hidden_size, bias=False)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class ModernTransformerBlock(nn.Module):
    """Pre-norm Transformer block with modern components."""
    
    def __init__(self, hidden_size: int, num_heads: int, max_seq_len: int):
        super().__init__()
        self.norm1 = RMSNorm(hidden_size)
        self.attn = ModernAttention(hidden_size, num_heads, max_seq_len)
        self.norm2 = RMSNorm(hidden_size)
        self.ffn = SwiGLU(hidden_size)
    
    def forward(
        self, x: torch.Tensor, causal_mask: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        x = x + self.attn(self.norm1(x), causal_mask)
        x = x + self.ffn(self.norm2(x))
        return x


class ModernTransformerLM(nn.Module):
    """
    Modern Transformer LM as a strong baseline for UID comparisons.
    
    Architecture choices (Llama-2/3 style):
    - RoPE positional encoding (no learned positional embeddings)
    - RMSNorm
    - SwiGLU FFN
    - Pre-norm
    - Tied input/output embeddings
    """
    
    def __init__(
        self,
        vocab_size: int,
        hidden_size: int,
        num_layers: int,
        num_heads: int,
        max_seq_len: int,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.max_seq_len = max_seq_len
        
        self.tok_emb = nn.Embedding(vocab_size, hidden_size)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([
            ModernTransformerBlock(hidden_size, num_heads, max_seq_len)
            for _ in range(num_layers)
        ])
        self.norm = RMSNorm(hidden_size)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)
        self.lm_head.weight = self.tok_emb.weight  # tie weights
        
        self.apply(self._init_weights)
    
    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, std=0.02)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, std=0.02)
    
    def count_non_embedding_params(self) -> int:
        """Count parameters excluding embeddings (Chinchilla convention)."""
        total = sum(p.numel() for p in self.parameters())
        emb = self.tok_emb.weight.numel()
        # Note: lm_head shares with tok_emb, so we don't subtract it
        return total - emb
    
    def forward(
        self,
        input_ids: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
        output_hidden_states: bool = False,
        **kwargs,
    ) -> CausalLMOutputWithPast:
        b, s = input_ids.shape
        if s > self.max_seq_len:
            raise ValueError(f"Sequence length {s} > max {self.max_seq_len}")
        
        x = self.drop(self.tok_emb(input_ids))
        causal_mask = torch.triu(
            torch.ones(s, s, device=x.device, dtype=torch.bool),
            diagonal=1,
        )
        
        hidden_states_list = []
        for block in self.blocks:
            x = block(x, causal_mask)
            if output_hidden_states:
                hidden_states_list.append(x)
        
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
            hidden_states=tuple(hidden_states_list) if output_hidden_states else None,
            attentions=None,
        )
