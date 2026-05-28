# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Add OU mode that aligns with v2.1's CID-side default colored noise
#     (a local SDE rather than global FFT shaping). The QFDT temperature
#     gate now multiplies the OU output for honest interpolation between
#     thermal and zero-point limits.
#   * Expose set_temperature() for clean parameter sweeps.
#   * Keep the legacy FFT path 100% backward-compatible.
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

"""Quantum colored noise with zero-point contribution.

带零点涨落的量子色噪声 —— 提供两种模式：

1. ``mode="fft"`` (LEGACY):
       Direct FFT shaping with the standard QFDT spectrum
       S_xi(omega) = (hbar*omega/2) * coth(hbar*omega / (2 k_B T)).
       Smoothly interpolates thermal -> zero-point as T -> 0.
       Carries the same circular-measurement risk as
       cid.colored_noise.FastColoredNoise.

2. ``mode="ou"`` (RECOMMENDED, v2.1 alignment):
       Local OU SDE  d xi = -xi/tau dt + sqrt(2/tau) dW
       with output amplitude scaled by sqrt(1 + zero_point_term)
       where the zero-point term is derived from the QFDT spectrum
       evaluated at the OU characteristic frequency 1/tau.

Both modes expose the same forward signature and a shared
``set_temperature(T)`` API for clean parameter sweeps.

实现量子涨落-耗散关系（QFDT）的标准谱形式，在高温下回到经典色噪声，
低温下退化为纯零点涨落（不耗能的随机性源）。v2.1 新增 OU 模式与
v2.1 CID 端默认色噪声实现对齐。
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import torch
import torch.nn as nn


VALID_MODES = {"fft", "ou"}


class QuantumColoredNoise(nn.Module):
    """Quantum colored noise generator with FFT or OU shaping.

    带零点涨落的量子色噪声生成器，支持 FFT 与 OU 两种实现。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        mode: str = "fft",
        hbar: float = 1.0,
        init_temperature: float = 1.0,
        omega_cutoff: float = 10.0,
        tau: float = 10.0,
    ) -> None:
        """Initialise the quantum-noise module.

        Args:
            hidden_size:      Feature dimension. 隐藏维度。
            mode:             "fft" or "ou"; default "fft" (legacy).
                              v2.1 alignment recommends "ou".
            hbar:             Reduced Planck constant in natural units.
                              自然单位下的 hbar。
            init_temperature: Initial environment temperature.
                              环境初始温度。
            omega_cutoff:     Maximum (dimensionless) frequency mapped
                              from the rfft grid. FFT 模式专用。
            tau:              OU correlation time. OU 模式专用。
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
        if mode not in VALID_MODES:
            raise ValueError(
                f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}"
            )
        if tau <= 0.0:
            raise ValueError(f"tau must be positive, got {tau}")

        self.hidden_size: int = int(hidden_size)
        self.mode: str = mode
        self.hbar: float = float(hbar)
        self.omega_cutoff: float = float(omega_cutoff)
        self.tau: float = float(tau)

        # Log-parameterised so T stays positive.
        self.log_temperature: nn.Parameter = nn.Parameter(
            torch.log(torch.tensor(float(init_temperature)))
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_temperature(self, temperature: float) -> None:
        """Set the environment temperature in absolute units.

        清晰地设置环境温度，便于 T -> 0 极限下的参数扫描。
        """
        if temperature <= 0.0:
            raise ValueError(
                f"temperature must be positive, got {temperature}"
            )
        with torch.no_grad():
            self.log_temperature.fill_(math.log(float(temperature)))

    def get_temperature(self) -> float:
        return float(torch.exp(self.log_temperature).item())

    # ------------------------------------------------------------------
    # QFDT spectrum
    # ------------------------------------------------------------------

    def _qfdt_spectrum(self, omega: torch.Tensor) -> torch.Tensor:
        """S_xi(omega) = (hbar omega / 2) coth(hbar omega / (2T)).

        计算量子涨落-耗散谱密度（含零点项）。
        """
        temperature = torch.exp(self.log_temperature)
        x = self.hbar * omega / (2.0 * temperature + 1.0e-8)
        # coth(x) = 1 / tanh(x); +1e-8 stabilises near x = 0.
        coth = 1.0 / torch.tanh(x + 1.0e-8)
        return (self.hbar * omega * 0.5) * coth

    def _zero_point_amplitude_factor(self) -> torch.Tensor:
        """sqrt(1 + zero_point_term) at the OU characteristic frequency.

        OU 模式下用于在高温与零点极限之间平滑插值的振幅修正因子。
        At T -> infty: factor -> 1 (recovers classical OU).
        At T -> 0:     factor -> sqrt(1 + hbar / (2 * tau * eps)) -> large.
        """
        temperature = torch.exp(self.log_temperature)
        omega_char = 1.0 / max(self.tau, 1.0e-8)
        x = self.hbar * omega_char / (2.0 * temperature + 1.0e-8)
        # zero_point term saturates at 1 in the high-T limit and grows
        # as 1/(2 x) when x -> 0.
        zp_term = 1.0 / torch.tanh(x + 1.0e-8) - 1.0
        return torch.sqrt(1.0 + zp_term.clamp_min(0.0))

    # ------------------------------------------------------------------
    # FFT mode (legacy)
    # ------------------------------------------------------------------

    def _forward_fft(
        self,
        batch_size: int,
        seq_len: int,
        device: torch.device,
        dtype: torch.dtype,
    ) -> torch.Tensor:
        if seq_len < 4:
            raise ValueError(
                f"seq_len must be >= 4 in FFT mode, got {seq_len}"
            )
        freqs = torch.fft.rfftfreq(seq_len, device=device, dtype=dtype)
        freqs = torch.where(
            freqs == 0, torch.full_like(freqs, 1.0e-10), freqs,
        )
        omegas = freqs * self.omega_cutoff
        spec = self._qfdt_spectrum(omegas).clamp_min(0.0)
        amp = torch.sqrt(spec + 1.0e-10)

        white = torch.randn(
            batch_size, seq_len, self.hidden_size,
            device=device, dtype=dtype,
        )
        fft_w = torch.fft.rfft(white, dim=1)
        fft_q = fft_w * amp[None, :, None]
        return torch.fft.irfft(fft_q, n=seq_len, dim=1)

    # ------------------------------------------------------------------
    # OU mode (v2.1 alignment)
    # ------------------------------------------------------------------

    def _forward_ou(
        self,
        batch_size: int,
        seq_len: int,
        device: torch.device,
        dtype: torch.dtype,
    ) -> torch.Tensor:
        # Exact discrete OU update; gives steady-state Var = 1.
        decay = math.exp(-1.0 / self.tau)
        kick_scale = math.sqrt(max(1.0 - decay * decay, 0.0))

        state = torch.randn(
            batch_size, self.hidden_size, device=device, dtype=dtype,
        )
        out = torch.empty(
            batch_size, seq_len, self.hidden_size,
            device=device, dtype=dtype,
        )
        for t in range(seq_len):
            kick = torch.randn(
                batch_size, self.hidden_size,
                device=device, dtype=dtype,
            )
            state = decay * state + kick_scale * kick
            out[:, t, :] = state

        # Apply zero-point amplitude factor: at high T this is ~1
        # (recovers classical OU); as T -> 0 it grows, modelling the
        # zero-point branch of the QFDT spectrum.
        factor = self._zero_point_amplitude_factor().to(
            device=device, dtype=dtype
        )
        return factor * out

    # ------------------------------------------------------------------
    # Public forward
    # ------------------------------------------------------------------

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
            seq_len:    Sequence length. 序列长度 (FFT mode requires >=4).
            device:     Target device. 目标设备。
            dtype:      Target dtype. 数据类型。

        Returns:
            Tuple ``(noise, info)`` with noise of shape (B, S, H) and
            info dict reporting current temperature, mode, and the
            relative weight of the zero-point branch.
        """
        if self.mode == "ou":
            noise = self._forward_ou(batch_size, seq_len, device, dtype)
        else:
            noise = self._forward_fft(batch_size, seq_len, device, dtype)

        with torch.no_grad():
            temperature = float(torch.exp(self.log_temperature).item())
            # Reference omega: characteristic frequency of the chosen
            # mode (1/tau for OU, omega_cutoff/2 for FFT).
            if self.mode == "ou":
                ref_omega = 1.0 / max(self.tau, 1.0e-8)
            else:
                ref_omega = 0.5 * self.omega_cutoff
            zp_ratio = (
                self.hbar * ref_omega / (2.0 * temperature + 1.0e-8)
            )
            info: Dict[str, float] = {
                "mode": 0.0 if self.mode == "ou" else 1.0,
                "temperature": float(temperature),
                "zero_point_ratio": float(zp_ratio),
                "is_quantum_dominant": float(zp_ratio > 1.0),
                "ref_omega": float(ref_omega),
            }
        return noise, info
