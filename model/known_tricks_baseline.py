# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
Modern Transformer + "all known tricks" baseline.

This is the CRITICAL comparison for UID's "physical framework" claim:
- If full CID does not outperform a Transformer that simply adds 
  colored noise + depthwise conv + a small linear projection, 
  then the "physical organization" claim is FALSIFIED.

This module assembles:
  - Modern Transformer (RoPE + RMSNorm + SwiGLU) 
  - Plus optional colored-noise injection
  - Plus optional depthwise causal convolution
  - Plus optional extra linear (commutator-style) term

By turning each on/off, we can verify whether CID's "physical 
synthesis" yields anything beyond their naive combination.
"""

from __future__ import annotations

from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers.modeling_outputs import CausalLMOutputWithPast

from .modern_transformer import (
    ModernAttention, RMSNorm, SwiGLU,
)
from uid_theory.cid.colored_noise import FastColoredNoise
from uid_theory.cid.memory_kernel import MemoryKernel
from uid_theory.cid.vortex_field import VortexField


class KnownTricksBlock(nn.Module):
    """
    Modern Transformer block with optional add-on tricks.
    
    The three tricks correspond to CID's three "physical" components 
    but are presented as standard ML techniques without physical framing:
    - `use_noise`: colored noise injection (similar to noise regularization)
    - `use_conv`: depthwise causal conv (similar to Mamba)
    - `use_linear`: extra linear projection (similar to a residual op)
    """
    
    def __init__(
        self,
        hidden_size: int,
        num_heads: int,
        max_seq_len: int,
        use_noise: bool = True,
        use_conv: bool = True,
        use_linear: bool = True,
        noise_beta: float = 1.0,
        conv_kernel_size: int = 64,
    ):
        super().__init__()
        self.use_noise = use_noise
        self.use_conv = use_conv
        self.use_linear = use_linear
        
        self.norm1 = RMSNorm(hidden_size)
        self.attn = ModernAttention(hidden_size, num_heads, max_seq_len)
        self.norm2 = RMSNorm(hidden_size)
        self.ffn = SwiGLU(hidden_size)
        
        # Optional add-on tricks (same implementations as CID's physical 
        # components, but presented without physical framing)
        if use_noise:
            self.noise = FastColoredNoise(beta=noise_beta, dim=hidden_size)
            self.noise_scale = nn.Parameter(torch.tensor(0.01))
        if use_conv:
            self.conv = MemoryKernel(
                hidden_size=hidden_size,
                memory_length=conv_kernel_size,
                alpha=0.3,
            )
            self.log_w_conv = nn.Parameter(torch.tensor(-2.0))
        if use_linear:
            self.linear_extra = VortexField(hidden_size)
            self.log_w_linear = nn.Parameter(torch.tensor(-2.0))
    
    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        h = self.norm1(x)
        attn_out = self.attn(h, causal_mask)
        
        extra = 0.0
        if self.use_conv:
            extra = extra + torch.exp(self.log_w_conv) * self.conv(h)
        if self.use_linear:
            v, _ = self.linear_extra(h)
            extra = extra + torch.exp(self.log_w_linear) * v
        if self.use_noise and self.training:
            xi = self.noise(h.shape[0], h.shape[1], h.device, h.dtype)
            extra = extra + self.noise_scale * xi
        
        x = x + attn_out + extra
        x = x + self.ffn(self.norm2(x))
        return x


class TransformerPlusTricksLM(nn.Module):
    """
    Modern Transformer LM enhanced with selectable add-on tricks.
    
    This serves as the critical "negative control": if UID's full CID 
    cannot beat this baseline (which uses the same techniques but 
    without the physical framing), then UID's contribution is purely 
    rhetorical.
    """
    
    def __init__(
        self,
        vocab_size: int,
        hidden_size: int,
        num_layers: int,
        num_heads: int,
        max_seq_len: int,
        use_noise: bool = True,
        use_conv: bool = True,
        use_linear: bool = True,
        dropout: float = 0.0,
    ):
        super().__init__()
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.max_seq_len = max_seq_len
        self.use_noise = use_noise
        self.use_conv = use_conv
        self.use_linear = use_linear
        
        self.tok_emb = nn.Embedding(vocab_size, hidden_size)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([
            KnownTricksBlock(
                hidden_size=hidden_size,
                num_heads=num_heads,
                max_seq_len=max_seq_len,
                use_noise=use_noise,
                use_conv=use_conv,
                use_linear=use_linear,
            )
            for _ in range(num_layers)
        ])
        self.norm = RMSNorm(hidden_size)
        self.lm_head = nn.Linear(hidden_size, vocab_size, bias=False)
        self.lm_head.weight = self.tok_emb.weight
        
        self.apply(self._init_weights)
    
    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, std=0.02)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, std=0.02)
    
    def count_non_embedding_params(self) -> int:
        total = sum(p.numel() for p in self.parameters())
        emb = self.tok_emb.weight.numel()
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
