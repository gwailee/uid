# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * AblationConfig: propagate v2.1 keys (noise_type, noise_tau,
#     use_et_symmetric) so Theory §8.5 / §14.2 switches participate
#     in the canonical ablation matrix.
#   * Add two new variants required by Theory §8.5 / §14.2:
#       - cid_full_no_et:        full CID but with ET symmetric term OFF
#       - cid_full_fft_noise:    full CID but with legacy FFT noise
#     These let us isolate the engineering contribution of the two
#     v2.1 fixes from the underlying CID skeleton.
"""
Complete ablation suite (11 variants including two v2.1 isolations).

This module FIXES two prior gaps:
    (1) v0.1 was missing the `cid_no_memory` ablation variant.
    (2) v2.0 introduced §8.5 ET and §14.2 OU defaults but did not
        expose them in the ablation matrix, so their isolated effect
        could not be measured.

The full ablation matrix (v2.1):

    Group A (CID component ablations, traditional):
        1. cid_no_vortex          turn off vortex term v(phi)
        2. cid_no_memory          turn off memory kernel  ← v2.0 added
        3. cid_no_noise           turn off colored noise xi(t)
        4. cid_full               all three terms active

    Group A' (v2.1 fix isolations):
        5. cid_full_no_et         full CID but ET symmetric term OFF
                                  (isolates §8.5 contribution)
        6. cid_full_fft_noise     full CID but with FFT noise instead
                                  of OU (isolates §14.2 contribution)

    Group B (known-tricks baselines):
        7. transformer_baseline           modern Transformer
        8. transformer_plus_noise         + colored noise only
        9. transformer_plus_conv          + depthwise conv only
       10. transformer_plus_linear        + extra linear term only
       11. transformer_plus_all_tricks    all three known tricks

The critical comparisons:
    * cid_full vs transformer_plus_all_tricks
        — if not significantly better, UID's "physical framework"
          claim is FALSIFIED (the gains come from known tricks, not
          from physical organization).
    * cid_full vs cid_full_no_et
        — quantifies the §8.5 ET symmetric term's contribution.
    * cid_full vs cid_full_fft_noise
        — quantifies the §14.2 OU-vs-FFT noise contribution.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import torch.nn as nn

from model.modern_transformer import ModernTransformerLM
from model.known_tricks_baseline import TransformerPlusTricksLM
from model.model_uid import UIDConfig, UIDModel


@dataclass
class AblationConfig:
    """Configuration for a single ablation variant.

    Fields:
        name:             Unique identifier of the variant.
        description:      Human-readable description.
        family:           "transformer", "transformer_plus_tricks", "cid".
        use_noise:        (transformer_plus_tricks only) attach colored
                          noise.
        use_conv:         (transformer_plus_tricks only) attach
                          depthwise causal conv.
        use_linear:       (transformer_plus_tricks only) attach extra
                          linear term.
        use_vortex:       (cid only) enable curl term v(phi).
        use_memory:       (cid only) enable colored-damping kernel.
        use_colored_noise:(cid only) enable colored noise xi(t).
        noise_type:       (cid + transformer_plus_tricks) "ou" or "fft".
                          v2.1 default: "ou".
        noise_tau:        (only used when noise_type="ou") OU relaxation
                          time in step units. v2.1 default: 10.0.
        noise_beta:       (only used when noise_type="fft") FFT
                          spectral slope. Default: 1.0.
        use_et_symmetric: (cid only) enable §8.5 ET symmetric attention.
                          v2.1 default: True.
    """
    name: str
    description: str
    family: str  # "transformer", "transformer_plus_tricks", "cid"
    use_noise: bool = False
    use_conv: bool = False
    use_linear: bool = False
    use_vortex: bool = False
    use_memory: bool = False
    use_colored_noise: bool = False
    # v2.1 keys (defaults match UIDConfig / TransformerPlusTricksLM defaults)
    noise_type: str = "ou"
    noise_tau: float = 10.0
    noise_beta: float = 1.0
    use_et_symmetric: bool = True


def get_ablation_configs() -> List[AblationConfig]:
    """Return the canonical 11-way ablation matrix (v2.1).

    Returns:
        List of AblationConfig instances. The order is:
        4 traditional CID ablations + 2 v2.1 fix isolations +
        5 known-tricks baselines = 11 variants total.
    """
    return [
        # ------ Group A: traditional CID component ablations ------
        AblationConfig(
            name="cid_no_vortex",
            description="CID with vortex (v) term DISABLED",
            family="cid",
            use_vortex=False, use_memory=True, use_colored_noise=True,
        ),
        AblationConfig(
            name="cid_no_memory",
            description="CID with memory kernel DISABLED [added in v2.0]",
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
        # ------ Group A': v2.1 fix isolations ----------------------
        AblationConfig(
            name="cid_full_no_et",
            description=(
                "Full CID but ET symmetric attention term DISABLED "
                "[isolates Theory §8.5 contribution; added in v2.1]"
            ),
            family="cid",
            use_vortex=True, use_memory=True, use_colored_noise=True,
            use_et_symmetric=False,
        ),
        AblationConfig(
            name="cid_full_fft_noise",
            description=(
                "Full CID but with legacy FFT noise instead of OU "
                "[isolates Theory §14.2 OU contribution; added in v2.1]"
            ),
            family="cid",
            use_vortex=True, use_memory=True, use_colored_noise=True,
            noise_type="fft",
            noise_beta=1.0,
        ),
        # ------ Group B: known-tricks baselines --------------------
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
    """Build a model for the given ablation configuration.

    Args:
        config:        AblationConfig describing the variant.
        vocab_size:    Vocabulary size.
        hidden_size:   Feature dimension.
        num_layers:    Number of layers in the backbone.
        num_heads:     Number of attention heads.
        max_seq_len:   Maximum sequence length.

    Returns:
        Instantiated model (TransformerPlusTricksLM, ModernTransformerLM,
        or UIDModel depending on ``config.family``).

    Raises:
        ValueError: If ``config.family`` is unknown.
    """
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
            # v2.1: propagate noise configuration so baseline and CID
            # use the SAME noise implementation when comparing.
            noise_type=config.noise_type,
            noise_beta=config.noise_beta,
            noise_tau=config.noise_tau,
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
            # v2.1: propagate all three new keys.
            noise_type=config.noise_type,
            noise_tau=config.noise_tau,
            noise_beta=config.noise_beta,
            use_et_symmetric=config.use_et_symmetric,
        )
        return UIDModel(cfg)
    else:
        raise ValueError(f"Unknown family: {config.family}")
