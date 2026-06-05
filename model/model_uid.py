# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * UIDConfig: add noise_type, noise_tau, use_et_symmetric so the v2.1
#     CIDLayer defaults survive save_pretrained / from_pretrained.
#   * UIDModel: expose set_noise_injection / set_energy_monitoring /
#     fluctuation_dissipation_consistency at the TOP level — README's
#     critical-exponent measurement workflow depends on these.
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

"""Causal language model built from CID/QID/FID blocks.

由 CID/QID/FID 块组成的因果语言模型。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import PretrainedConfig, PreTrainedModel
from transformers.modeling_outputs import CausalLMOutputWithPast

from cid.cid_layer import CIDBlock


class UIDConfig(PretrainedConfig):
    """Configuration object for :class:`UIDModel`.

    UID 模型的配置类。
    """

    model_type = "uid"

    def __init__(
        self,
        vocab_size: int = 6400,
        hidden_size: int = 512,
        num_hidden_layers: int = 8,
        num_attention_heads: int = 8,
        max_position_embeddings: int = 2048,
        use_vortex: bool = True,
        use_memory: bool = True,
        use_colored_noise: bool = True,
        # v2.1: noise configuration.
        # OU is the physically correct default per Theory §14.2;
        # FFT is kept available for legacy comparison.
        noise_type: str = "ou",
        noise_beta: float = 1.0,
        noise_tau: float = 10.0,
        mem_alpha: float = 0.3,
        memory_length: int = 64,
        dropout: float = 0.1,
        # v2.1: §8.5 ET symmetric dual-term attention.
        use_et_symmetric: bool = True,
        **kwargs,
    ) -> None:
        """Build the configuration.

        Args:
            vocab_size:              Vocabulary size. 词表大小。
            hidden_size:             Feature dim. 隐藏维度。
            num_hidden_layers:       Number of CID layers. 层数。
            num_attention_heads:     Attention heads. 注意力头数。
            max_position_embeddings: Maximum sequence length. 最大序列长度。
            use_vortex:              Enable vortex term. 启用旋度项。
            use_memory:              Enable memory kernel. 启用记忆核。
            use_colored_noise:       Enable colored noise. 启用色噪声。
            noise_type:              "ou" (physical, §14.2 default) or
                                     "fft" (legacy spectral shaping).
                                     色噪声类型。
            noise_beta:              Spectral slope of colored noise
                                     (only used when noise_type="fft").
                                     仅 FFT 模式使用的功率谱斜率。
            noise_tau:               OU correlation time (only used when
                                     noise_type="ou").
                                     仅 OU 模式使用的相关时间。
            mem_alpha:               Sub-Ohmic exponent. 亚欧姆指数。
            memory_length:           Memory-kernel receptive field.
                                     记忆核感受野长度。
            dropout:                 Dropout. Dropout 概率。
            use_et_symmetric:        Whether to use the ET symmetric
                                     dual-term attention update (§8.5).
                                     是否启用 §8.5 ET 对称双项注意力。
        """
        super().__init__(**kwargs)
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.max_position_embeddings = max_position_embeddings
        self.use_vortex = use_vortex
        self.use_memory = use_memory
        self.use_colored_noise = use_colored_noise
        self.noise_type = str(noise_type).lower()
        self.noise_beta = noise_beta
        self.noise_tau = noise_tau
        self.mem_alpha = mem_alpha
        self.memory_length = memory_length
        self.dropout = dropout
        self.use_et_symmetric = bool(use_et_symmetric)


class UIDModel(PreTrainedModel):
    """Causal LM whose backbone is a stack of CID layers.

    主干为 CID 层堆叠的因果语言模型。
    """

    config_class = UIDConfig

    def __init__(self, config: UIDConfig) -> None:
        """Initialise the model from a config object.

        Args:
            config: A :class:`UIDConfig`. 模型配置对象。
        """
        super().__init__(config)
        self.config = config

        self.tok_emb: nn.Embedding = nn.Embedding(
            config.vocab_size, config.hidden_size
        )
        self.pos_emb: nn.Embedding = nn.Embedding(
            config.max_position_embeddings, config.hidden_size
        )
        self.drop: nn.Dropout = nn.Dropout(config.dropout)

        self.backbone: CIDBlock = CIDBlock(
            num_layers=config.num_hidden_layers,
            hidden_size=config.hidden_size,
            num_heads=config.num_attention_heads,
            use_vortex=config.use_vortex,
            use_memory=config.use_memory,
            use_colored_noise=config.use_colored_noise,
            noise_type=config.noise_type,
            noise_beta=config.noise_beta,
            noise_tau=config.noise_tau,
            mem_alpha=config.mem_alpha,
            memory_length=config.memory_length,
            dropout=config.dropout,
            use_et_symmetric=config.use_et_symmetric,
        )

        self.norm: nn.LayerNorm = nn.LayerNorm(config.hidden_size)
        self.lm_head: nn.Linear = nn.Linear(
            config.hidden_size, config.vocab_size, bias=False
        )
        # Weight tying / 权重绑定.
        self.lm_head.weight = self.tok_emb.weight

        self.apply(self._init_weights)

    @staticmethod
    def _init_weights(module: nn.Module) -> None:
        """Initialise weights with small Gaussian noise.

        以小尺度高斯初始化权重。
        """
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, std=0.02)
            if module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, std=0.02)

    # ------------------------------------------------------------------
    # Top-level API (v2.1): expose backbone switches for honest
    # measurement of emergent critical exponents and for ET Lyapunov
    # verification per Theory §8.5.
    # ------------------------------------------------------------------

    def set_noise_injection(self, enabled: bool) -> None:
        """Enable / disable colored-noise injection model-wide.

        CRITICAL for honest measurement of emergent critical exponents:
        before measuring 1/f spectra, Hurst, or avalanche statistics,
        call ``model.set_noise_injection(False)`` so the measured
        signature is NOT a circular echo of the injected noise.

        关键：测量临界涌现指标前必须关闭噪声注入，否则结果将仅是
        注入噪声的回响而非真实涌现。
        """
        self.backbone.set_noise_injection(enabled)

    def set_energy_monitoring(self, enabled: bool) -> None:
        """Enable / disable ET energy monitoring at every layer.

        When enabled, each layer's forward fills
        ``info[layer_i]["et_energy"]`` with the §8.5 ET energy value,
        enabling engineering verification of Lyapunov monotonicity.

        开启后，每层前向在 info 中记录 ET 能量值，
        便于工程上验证 §8.5 Lyapunov 单调下降性质。
        """
        self.backbone.set_energy_monitoring(enabled)

    def fluctuation_dissipation_consistency(self) -> List[Dict[str, float]]:
        """Return per-layer fluctuation-dissipation consistency reports.

        返回每一层的涨落-耗散自洽性诊断报告。
        """
        return self.backbone.fluctuation_dissipation_consistency()

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        input_ids: torch.Tensor,
        labels: Optional[torch.Tensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
        output_hidden_states: bool = False,
        return_dict: bool = True,
        **kwargs,
    ) -> CausalLMOutputWithPast:
        """Run the language model.

        Args:
            input_ids:            (B, S) integer token ids. 输入 token。
            labels:               (B, S) optional targets; ``-100`` is
                                  ignored. 可选目标序列。
            attention_mask:       Unused (kept for HF compatibility).
                                  暂未使用，保留 HF 接口。
            output_hidden_states: If True, returns per-layer hidden
                                  states. 是否返回每层隐状态。
            return_dict:          Always returns ``CausalLMOutputWithPast``.

        Returns:
            A :class:`CausalLMOutputWithPast`.
        """
        del attention_mask  # not used in this minimal implementation
        del return_dict     # always uses the dataclass output

        b, s = input_ids.shape
        if s > self.config.max_position_embeddings:
            raise ValueError(
                f"sequence length {s} exceeds "
                f"max_position_embeddings"
                f"={self.config.max_position_embeddings}"
            )

        device = input_ids.device
        pos = torch.arange(s, device=device)
        x = self.drop(self.tok_emb(input_ids) + self.pos_emb(pos)[None])

        # Causal mask: True = blocked.
        # 因果掩码：True 表示屏蔽。
        causal_mask = torch.triu(
            torch.ones(s, s, device=device, dtype=torch.bool),
            diagonal=1,
        )

        x, hidden_states, _ = self.backbone(
            x,
            causal_mask=causal_mask,
            add_noise=self.training,
            return_hidden_states=output_hidden_states,
        )
        x = self.norm(x)
        logits = self.lm_head(x)

        loss = None
        if labels is not None:
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, self.config.vocab_size),
                shift_labels.view(-1),
                ignore_index=-100,
            )

        return CausalLMOutputWithPast(
            loss=loss,
            logits=logits,
            past_key_values=None,
            hidden_states=(
                tuple(hidden_states)
                if hidden_states is not None
                else None
            ),
            attentions=None,
        )

    @torch.no_grad()
    def generate(
        self,
        input_ids: torch.Tensor,
        max_new_tokens: int = 64,
        temperature: float = 1.0,
        top_k: int = 50,
    ) -> torch.Tensor:
        """Greedy / top-k sampling generation loop.

        贪心 / top-k 采样的简单生成循环。

        Args:
            input_ids:       Prompt (B, S0). 提示 token。
            max_new_tokens:  Tokens to generate. 生成的 token 数。
            temperature:     Sampling temperature. 采样温度。
            top_k:           If > 0, keep top-k logits. top-k 截断。

        Returns:
            Tensor of shape (B, S0 + max_new_tokens). 生成结果。
        """
        self.eval()
        for _ in range(max_new_tokens):
            cropped = input_ids[:, -self.config.max_position_embeddings :]
            out = self.forward(cropped)
            logits = out.logits[:, -1, :] / max(float(temperature), 1.0e-6)
            if top_k > 0:
                v, _ = torch.topk(logits, top_k)
                logits[logits < v[:, [-1]]] = float("-inf")
            probs = torch.softmax(logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
            input_ids = torch.cat([input_ids, next_token], dim=1)
        return input_ids
