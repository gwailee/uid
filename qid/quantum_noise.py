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

"""Quantum colored noise with zero-point contribution.

带零点涨落的量子色噪声。

Implements a spectral density of the form
    ``S_xi(omega) = (hbar * omega / 2) * coth(hbar * omega / (2 k_B T))``,
which smoothly interpolates between thermal (high-T) and zero-point
(T -> 0) regimes.

实现量子涨落-耗散关系的标准谱形式，在高温下回到经典色噪声，在低温下
退化为纯零点涨落（不耗能的随机性源）。
"""

from __future__ import annotations

from typing import Dict, Tuple

import torch
import torch.nn as nn


class QuantumColoredNoise(nn.Module):
    """FFT-shaped colored noise with a coth spectral envelope.

    用 FFT 整形的色噪声，其包络由 coth 函数描述，覆盖热涨落与零点涨落。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        hbar: float = 1.0,
        init_temperature: float = 1.0,
        omega_cutoff: float = 10.0,
    ) -> None:
        """Initialise the quantum-noise module.

        Args:
            hidden_size:      Feature dimension. 隐藏维度。
            hbar:             Reduced Planck constant in natural units.
                              自然单位下的 hbar。
            init_temperature: Initial environment temperature.
                              环境初始温度。
            omega_cutoff:     Maximum (dimensionless) frequency mapped
                              from the rfft grid. rfft 频率轴的最大映射值。
        """
        super().__init__()
        if hidden_size <= 0:
            raise ValueError(
                f"hidden_size must be positive, got {hidden_size}"
            )
        if init_temperature <= 0:
            raise ValueError(
                f"init_temperature must be positive, got {init_temperature}"
            )
        self.hidden_size: int = int(hidden_size)
        self.hbar: float = float(hbar)
        self.omega_cutoff: float = float(omega_cutoff)
        # Log-parameterised so T stays positive.
        # Log 参数化保证温度始终为正。
        self.log_temperature: nn.Parameter = nn.Parameter(
            torch.log(torch.tensor(float(init_temperature)))
        )

    def _spectrum(self, omega: torch.Tensor) -> torch.Tensor:
        """Return S(omega) = (hbar omega / 2) coth(hbar omega / 2T).

        计算量子谱密度（含零点项）。
        """
        temperature = torch.exp(self.log_temperature)
        x = self.hbar * omega / (2.0 * temperature + 1.0e-8)
        # 1 / tanh(x) = coth(x); the +1e-8 stabilises near x = 0.
        coth = 1.0 / torch.tanh(x + 1.0e-8)
        return (self.hbar * omega * 0.5) * coth

    def forward(
        self,
        batch_size: int,
        seq_len: int,
        device: torch.device,
        dtype: torch.dtype = torch.float32,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Sample a quantum colored-noise tensor.

        Args:
            batch_size: Batch size. 批大小。
            seq_len:    Sequence length. 序列长度。
            device:     Target device. 目标设备。
            dtype:      Target dtype. 数据类型。

        Returns:
            Tuple ``(noise, info)`` with noise of shape (B, S, H) and
            info dict reporting current temperature and the relative
            weight of the zero-point branch.
            返回噪声张量及诊断字典（当前温度、零点占比）。
        """
        if seq_len < 4:
            raise ValueError(f"seq_len must be >= 4, got {seq_len}")

        freqs = torch.fft.rfftfreq(seq_len, device=device, dtype=dtype)
        freqs = torch.where(
            freqs == 0, torch.full_like(freqs, 1.0e-10), freqs
        )
        omegas = freqs * self.omega_cutoff
        spec = self._spectrum(omegas).clamp_min(0.0)
        amp = torch.sqrt(spec + 1.0e-10)

        white = torch.randn(
            batch_size, seq_len, self.hidden_size, device=device, dtype=dtype
        )
        fft_w = torch.fft.rfft(white, dim=1)
        fft_q = fft_w * amp[None, :, None]
        noise = torch.fft.irfft(fft_q, n=seq_len, dim=1)

        with torch.no_grad():
            temperature = torch.exp(self.log_temperature).item()
            mean_omega = omegas.mean().item()
            zp_ratio = (
                self.hbar * mean_omega / (2.0 * temperature + 1.0e-8)
            )
            info: Dict[str, float] = {
                "temperature": float(temperature),
                "zero_point_ratio": float(zp_ratio),
                "is_quantum_dominant": float(zp_ratio > 1.0),
            }
        return noise, info
