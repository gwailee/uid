# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Complete ablation suite (5+ variants including cid_no_memory).

This module FIXES the v0.1 issue of missing the `cid_no_memory` 
ablation variant, which is essential for isolating the contribution 
of the memory kernel.

The full ablation matrix:
    Group A (CID components):
        1. cid_no_vortex       — turn off vortex term
        2. cid_no_memory       — turn off memory kernel  ← NEW in v2.0
        3. cid_no_noise        — turn off colored noise
        4. cid_full            — all three terms active
    
    Group B (known-tricks baselines):
        5. transformer_baseline           — modern Transformer
        6. transformer_plus_noise         — + colored noise only
        7. transformer_plus_conv          — + depthwise conv only
        8. transformer_plus_linear        — + extra linear term only
        9. transformer_plus_all_tricks    — all three known tricks

The critical comparison: cid_full vs transformer_plus_all_tricks. 
If full CID does not significantly outperform the baseline with the 
same known tricks attached, then UID's "physical framework" 
contribution is FALSIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List

import torch.nn as nn

from model.modern_transformer import ModernTransformerLM
from model.known_tricks_baseline import TransformerPlusTricksLM
from model.model_uid import UIDConfig, UIDModel


@dataclass
class AblationConfig:
    """Configuration for a single ablation variant."""
    name: str
    description: str
    family: str  # "transformer", "transformer_plus_tricks", "cid"
    use_noise: bool = False
    use_conv: bool = False
    use_linear: bool = False
    use_vortex: bool = False
    use_memory: bool = False
    use_colored_noise: bool = False


def get_ablation_configs() -> List[AblationConfig]:
    """Return the canonical 9-way ablation matrix."""
    return [
        # Group A: CID component ablations
        AblationConfig(
            name="cid_no_vortex",
            description="CID with vortex (v) term DISABLED",
            family="cid",
            use_vortex=False, use_memory=True, use_colored_noise=True,
        ),
        AblationConfig(
            name="cid_no_memory",
            description="CID with memory kernel DISABLED [NEW in v2.0]",
            family="cid",
            use_vortex=True, use_memory=False, use_colored_noise=True,
        ),
        AblationConfig(
            name="cid_no_noise",
            description="CID with colored noise DISABLED",
            family="cid",
            use_vortex=True, use_memory=True, use_colored_noise=False,
        ),
        AblationConfig(
            name="cid_full",
            description="Full CID with all three components active",
            family="cid",
            use_vortex=True, use_memory=True, use_colored_noise=True,
        ),
        # Group B: known-tricks baselines
        AblationConfig(
            name="transformer_baseline",
            description="Modern Transformer (RoPE+RMSNorm+SwiGLU) baseline",
            family="transformer",
        ),
        AblationConfig(
            name="transformer_plus_noise",
            description="Transformer + colored-noise injection only",
            family="transformer_plus_tricks",
            use_noise=True,
        ),
        AblationConfig(
            name="transformer_plus_conv",
            description="Transformer + depthwise causal conv only",
            family="transformer_plus_tricks",
            use_conv=True,
        ),
        AblationConfig(
            name="transformer_plus_linear",
            description="Transformer + extra linear (commutator) term only",
            family="transformer_plus_tricks",
            use_linear=True,
        ),
        AblationConfig(
            name="transformer_plus_all_tricks",
            description=(
                "Transformer + ALL three known tricks "
                "(CRITICAL comparison vs cid_full)"
            ),
            family="transformer_plus_tricks",
            use_noise=True, use_conv=True, use_linear=True,
        ),
    ]


def build_ablation_model(
    config: AblationConfig,
    vocab_size: int,
    hidden_size: int,
    num_layers: int,
    num_heads: int,
    max_seq_len: int,
) -> nn.Module:
    """Build a model for the given ablation configuration."""
    if config.family == "transformer":
        return ModernTransformerLM(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            max_seq_len=max_seq_len,
        )
    elif config.family == "transformer_plus_tricks":
        return TransformerPlusTricksLM(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            max_seq_len=max_seq_len,
            use_noise=config.use_noise,
            use_conv=config.use_conv,
            use_linear=config.use_linear,
        )
    elif config.family == "cid":
        cfg = UIDConfig(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_hidden_layers=num_layers,
            num_attention_heads=num_heads,
            max_position_embeddings=max_seq_len,
            use_vortex=config.use_vortex,
            use_memory=config.use_memory,
            use_colored_noise=config.use_colored_noise,
        )
        return UIDModel(cfg)
    else:
        raise ValueError(f"Unknown family: {config.family}")
