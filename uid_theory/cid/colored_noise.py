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

"""Colored-noise generator (1/f^beta spectrum).

色噪声生成器：实现 S(omega) ~ omega^(-beta) 的功率谱。

The generator is parameterised purely by the spectral slope ``beta``.
The Hurst exponent of the resulting signal is *not* fixed by ``beta``
alone (the precise relation depends on whether the underlying process
is fractional Gaussian noise or fractional Brownian motion); H is
therefore left as an *independent observable* to be measured a
posteriori on hidden-state sequences.  See ``verification/
prediction_test.py``.

理论依据：神经雪崩、皮层 EEG 与 MEG 普遍呈现 1/f^beta 谱（He, 2014;
Linkenkaer-Hansen et al., 2001）。CID 主方程将色阻尼 + 色涨落作为内嵌
机制，使系统具备长程时间依赖。
"""

from __future__ import annotations

import torch
import torch.nn as nn


class FastColoredNoise(nn.Module):
    """Vectorised FFT-based colored-noise generator.

    使用 FFT 在批维度与隐维度上向量化的色噪声生成器；
    单次调用即可生成 (B, S, D) 形状的色噪声样本。

    Attributes:
        beta: Spectral slope, S(omega) ~ omega^(-beta). beta=0 -> white;
              beta=1 -> pink (1/f); beta=2 -> red (Brownian).
              功率谱斜率。0 为白噪声，1 为粉红噪声，2 为布朗噪声。
        dim:  Per-token feature dimension. 每个 token 的特征维度。
    """

    def __init__(self, beta: float = 1.0, dim: int = 768) -> None:
        """Initialise the colored-noise generator.

        Args:
            beta: Target spectral slope (default 1.0 -> pink noise).
            dim:  Feature dimension over which independent noise channels
                  are drawn. 每个特征维度独立采样。
        """
        super().__init__()
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self.beta: float = float(beta)
        self.dim: int = int(dim)

    def forward(
        self,
        batch_size: int,
        seq_len: int,
        device: torch.device,
        dtype: torch.dtype = torch.float32,
    ) -> torch.Tensor:
        """Sample a colored-noise tensor of shape (B, S, D).

        Args:
            batch_size: Batch size B. 批大小。
            seq_len:    Sequence length S (>= 4). 序列长度。
            device:     Target device. 目标设备。
            dtype:      Target dtype. 目标数据类型。

        Returns:
            Tensor of shape (batch_size, seq_len, self.dim), unit
            variance along the sequence axis.
            形状 (B, S, D) 的色噪声张量，沿序列维归一化为单位方差。
        """
        if seq_len < 4:
            raise ValueError(f"seq_len must be >= 4, got {seq_len}")

        # rfft frequency grid (length seq_len // 2 + 1).
        # 实数 FFT 的频率轴。
        freqs = torch.fft.rfftfreq(seq_len, device=device, dtype=dtype)
        # Replace the zero-frequency bin with a small positive number to
        # avoid division by zero in the power-law factor.
        # 用一个小正数替代 0 频，避免除零。
        freqs = torch.where(
            freqs == 0,
            torch.full_like(freqs, 1.0e-10),
            freqs,
        )
        amp = freqs.pow(-self.beta / 2.0)  # shape: (n_freq,)

        # White noise on all (B, S, D) entries.
        # 在 (B, S, D) 上独立采样白噪声。
        white = torch.randn(
            batch_size, seq_len, self.dim, device=device, dtype=dtype
        )
        fft_white = torch.fft.rfft(white, dim=1)
        # Broadcast amp over (B, n_freq, D).
        fft_colored = fft_white * amp[None, :, None]
        out = torch.fft.irfft(fft_colored, n=seq_len, dim=1)

        # Normalise so that per-channel std along the time axis is ~1.
        # 沿时间维标准化到单位方差。
        std = out.std(dim=1, keepdim=True)
        return out / (std + 1.0e-8)
