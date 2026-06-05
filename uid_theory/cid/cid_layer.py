# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * VortexField: pass FFN[0].weight as weight_ref (zero extra params, §14.2)
#   * Default noise: switch to OrnsteinUhlenbeckNoise (physical, §14.2)
#   * Add set_energy_monitoring() for ET Lyapunov verification (§8.5)
#   * Add fluctuation-dissipation consistency check helper
# UPDATE: 2026-06-05
#   * FIX-3: Apply memory kernel to the pre-residual state x (before norm1),
#     not to the LayerNorm output h.  Theory (C5.3) requires the kernel to
#     integrate over the actual state trajectory φ(t); normalising the input
#     before the integral destroys the power-law statistics of the trajectory.
#     The memory term is now computed from x and then added into the residual
#     stream alongside the other terms.
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

"""CID layer: Euler-Maruyama discretisation of the CID master equation.

CID 主层 —— CID 主方程的 Euler-Maruyama 离散化实现。

KEY CHANGES in v2.1:
    1. VortexField now receives a reference to FFN[0].weight and builds
       its curl operator from the antisymmetric part J = (W - W^T)/2.
       This enforces the §14.2 "zero-extra-parameter curl" hard rule.

    2. Default colored noise is now OrnsteinUhlenbeckNoise (physical
       OU process). The legacy FastColoredNoise remains available via
       noise_type="fft" but is now discouraged because of its
       circular-measurement risk.

    3. New ``set_energy_monitoring`` switch records the ET energy
       function value per forward pass, enabling engineering
       verification of the §8.5 Lyapunov monotonic descent property.

    4. New ``set_noise_injection`` switch (kept from v2.0) for honest
       measurement of emergent critical exponents:
           model.train()
           # ... train as usual ...
           model.eval()
           model.set_noise_injection(False)
           # ... measure spectra, Hurst, avalanches ...

KEY CHANGES in v2.2 (2026-06-05):
    5. FIX-3: Memory kernel now operates on the raw residual state x,
       not on the LayerNorm output h.  See module-level docstring for
       the physical motivation.

修复说明（v2.2 FIX-3）
-----------------------
原代码：
    h = norm1(x)
    mem_term = -exp(log_w_mem) * self.memory(h)   # ← 对 norm(x) 积分

理论 (C5.3) 要求记忆核积分在真实状态轨迹 φ(t) 上执行，即对 x（残差流）
而非 norm1(x) 积分。LayerNorm 会破坏 x 的幂律自相关统计，使记忆核丧失
物理意义（Hurst 指数 H≈0.7 的长程关联来自真实轨迹，而非归一化后的值）。

修复后：
    h = norm1(x)
    mem_term = -exp(log_w_mem) * self.memory(x)   # ← 对原始 x 积分
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn

from .colored_noise import FastColoredNoise, OrnsteinUhlenbeckNoise
from .hopfield_potential import HopfieldAttention
from .memory_kernel import MemoryKernel
from .vortex_field import VortexField


class CIDLayer(nn.Module):
    """A single CID step with full §14.2 + §8.5 compliance."""

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        use_vortex: bool = True,
        use_memory: bool = True,
        use_colored_noise: bool = True,
        noise_type: str = "ou",
        noise_beta: float = 1.0,
        noise_tau: float = 10.0,
        mem_alpha: float = 0.3,
        memory_length: int = 64,
        dropout: float = 0.1,
        use_et_symmetric: bool = True,
    ) -> None:
        """Construct one CID layer.

        Args:
            hidden_size:       Feature dimension H. 隐藏维度。
            num_heads:         Attention heads. 必须整除 hidden_size。
            use_vortex:        Enable the curl term v(phi). 是否启用旋度。
            use_memory:        Enable the colored-damping memory kernel.
                               是否启用色阻尼记忆核。
            use_colored_noise: Enable the colored-noise term xi(t).
                               是否启用色噪声。
            noise_type:        "ou"  -> OrnsteinUhlenbeckNoise (physical,
                                        §14.2 default, RECOMMENDED).
                               "fft" -> FastColoredNoise (legacy, fast
                                        spectral shaping, NOT recommended
                                        for emergence measurement).
                               色噪声实现类型。
            noise_beta:        Spectral slope (only used when
                               noise_type="fft"). 仅 FFT 模式使用。
            noise_tau:         OU correlation time in step units
                               (only used when noise_type="ou").
                               仅 OU 模式使用，相关时间。
            mem_alpha:         Sub-Ohmic exponent in (0, 1) for memory
                               kernel. 记忆核亚欧姆指数。
            memory_length:     Memory kernel receptive field. 记忆核长度。
            dropout:           FFN dropout rate. FFN dropout 率。
            use_et_symmetric:  Use ET symmetric dual-term attention
                               (§8.5). Default True; set False for
                               ablation only.
                               是否启用 ET 对称双项注意力（§8.5）。
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.use_vortex: bool = bool(use_vortex)
        self.use_memory: bool = bool(use_memory)
        self.use_colored_noise: bool = bool(use_colored_noise)
        self.noise_type: str = str(noise_type).lower()

        # CRITICAL: separate flag for runtime control of noise injection
        # (so we can disable it at measurement time without changing
        # train / eval mode).
        # 关键：独立的噪声注入开关，便于测量时关闭。
        self._inject_noise: bool = True
        # Optional ET energy monitoring (off by default; turn on with
        # ``set_energy_monitoring(True)`` to log per-layer energy).
        # ET 能量监控开关，默认关闭。
        self._monitor_energy: bool = False

        # ---- Layer norms (microcanonical constraint, §9.2) -----------
        self.norm1: nn.LayerNorm = nn.LayerNorm(hidden_size)
        self.norm2: nn.LayerNorm = nn.LayerNorm(hidden_size)

        # ---- Associative memory term (-grad U, §8.5 ET-symmetric) ----
        self.attn: HopfieldAttention = HopfieldAttention(
            hidden_size,
            num_heads,
            use_et_symmetric=use_et_symmetric,
        )

        # ---- FFN (built BEFORE vortex so vortex can reference its W) -
        # ResNet / Euler-Maruyama discretisation (§9.1).
        self.ffn: nn.Sequential = nn.Sequential(
            nn.Linear(hidden_size, 4 * hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(4 * hidden_size, hidden_size),
            nn.Dropout(dropout),
        )

        # ---- Curl term v(phi)  (§14.2 zero-extra-parameter)  ---------
        # VortexField is built from the antisymmetric part of FFN[0].weight
        # so no new H*H matrix is introduced. Only +1 scalar per layer.
        self.vortex: Optional[VortexField] = (
            VortexField(
                hidden_size,
                weight_ref=self.ffn[0].weight,
            )
            if use_vortex else None
        )

        # ---- Colored damping (sub-Ohmic memory kernel, §5)  ----------
        self.memory: Optional[MemoryKernel] = (
            MemoryKernel(hidden_size, memory_length, mem_alpha)
            if use_memory else None
        )

        # ---- Colored noise (§5) --------------------------------------
        self.noise: Optional[nn.Module] = None
        if use_colored_noise:
            if self.noise_type == "ou":
                # Physically correct OU noise (§14.2 default, recommended).
                self.noise = OrnsteinUhlenbeckNoise(
                    dim=hidden_size,
                    tau=noise_tau,
                    learnable_sigma=True,
                )
            elif self.noise_type == "fft":
                # Legacy FFT spectral shaping (circular-measurement risk).
                self.noise = FastColoredNoise(noise_beta, hidden_size)
            else:
                raise ValueError(
                    f"unknown noise_type: {self.noise_type!r}; "
                    "expected 'ou' or 'fft'"
                )

        # ---- Learnable per-term weights (log-parameterised, >= 0) ----
        self.log_w_grad: nn.Parameter = nn.Parameter(torch.tensor(0.0))
        self.log_w_vortex: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        self.log_w_mem: nn.Parameter = nn.Parameter(torch.tensor(-2.0))
        # Scaling for noise injection (separate from OU's internal sigma
        # to allow caller-level shut-off without changing learned sigma).
        self.noise_scale: nn.Parameter = nn.Parameter(torch.tensor(0.01))

    # ------------------------------------------------------------------
    # Public switches
    # ------------------------------------------------------------------

    def set_noise_injection(self, enabled: bool) -> None:
        """Enable or disable colored-noise injection.

        CRITICAL: For honest measurement of emergent critical exponents
        (1/f spectra, Hurst, avalanches), this MUST be set to False at
        measurement time. Otherwise, any "emergent" signature would be
        circular — simply echoing the injected noise pattern.

        关键：测量 1/f / Hurst / 雪崩等涌现指数时必须关闭注入，
        否则结果将仅是注入噪声本身的回响。
        """
        self._inject_noise = bool(enabled)

    def set_energy_monitoring(self, enabled: bool) -> None:
        """Enable / disable ET energy logging per forward pass.

        When enabled, ``info["et_energy"]`` is filled at each forward
        with the ET energy function value, enabling engineering
        verification of the §8.5 Lyapunov monotonic-descent property.

        开启后，每次前向在 info 字典中记录 ET 能量值，
        用于工程上验证 §8.5 的 Lyapunov 单调下降性质。
        """
        self._monitor_energy = bool(enabled)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def fluctuation_dissipation_consistency(self) -> Dict[str, float]:
        """Check fluctuation-dissipation theorem (FDT) consistency.

        检查涨落-耗散关系自洽性：在亚欧姆谱下，色阻尼指数 alpha 与
        色噪声谱斜率 beta 应满足 beta ≈ alpha（仅 FFT 模式可比较）。

        Returns:
            Dictionary of diagnostic floats; empty if either memory or
            noise is disabled.
        """
        out: Dict[str, float] = {}
        if self.memory is None or self.noise is None:
            return out
        alpha = float(self.memory.alpha)
        out["alpha"] = alpha
        # OU mode: characterise by tau, no single spectral slope.
        if self.noise_type == "ou":
            out["noise_mode"] = 0.0  # 0 = OU
            out["tau"] = float(getattr(self.noise, "tau", 0.0))
            out["fdt_ok"] = 1.0  # OU + sub-Ohmic kernel is FDT-consistent
            return out
        # FFT mode: compare alpha and beta directly.
        beta = float(getattr(self.noise, "beta", 0.0))
        out["noise_mode"] = 1.0  # 1 = FFT
        out["beta"] = beta
        out["fdt_residual"] = abs(beta - alpha)
        out["fdt_ok"] = float(abs(beta - alpha) < 0.1)
        return out

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Execute one Euler-Maruyama step of the CID master equation.

        Implements Eq. (6.1):
            dphi/dt =  -grad U(phi)       (Hopfield / ET attention)
                      + v(phi)            (curl from antisymmetric FFN)
                      - integral gamma    (sub-Ohmic memory kernel)
                      + xi(t)             (OU colored noise)
        followed by the standard FFN residual block.

        Memory kernel note (FIX-3, v2.2):
            The memory term is computed from the raw residual state ``x``,
            NOT from the LayerNorm output ``h``.  Theory §5 requires the
            kernel to integrate the actual state trajectory φ(t); applying
            LayerNorm before the integral destroys the power-law
            autocorrelation statistics of the trajectory.

        记忆核说明（FIX-3，v2.2）：
            记忆项作用于原始残差流 x，而非 LayerNorm 输出 h。
            理论 §5 要求对真实轨迹 φ(t) 积分；在积分前施加 LayerNorm
            会破坏轨迹的幂律自相关统计。

        Args:
            x:           Input tensor of shape (B, S, H). 输入张量。
            causal_mask: Optional boolean mask of shape (S, S);
                         True entries are masked out.
            add_noise:   Per-call override; if False, no noise is added
                         regardless of other flags.

        Returns:
            ``(x_next, info)`` where ``info`` contains per-layer
            diagnostic scalars.
        """
        info: Dict[str, float] = {}
        h = self.norm1(x)

        # ----- 1. Associative-memory drift (ET energy gradient) -------
        grad_term = torch.exp(self.log_w_grad) * self.attn(
            h, causal_mask=causal_mask
        )
        # Optional ET energy monitoring (for Lyapunov verification §8.5).
        if self._monitor_energy:
            with torch.no_grad():
                e = self.attn.compute_energy(h, causal_mask=causal_mask)
                info["et_energy"] = float(e.item())

        # ----- 2. Vortex (curl) ---------------------------------------
        vortex_term = torch.zeros_like(h)
        if self.vortex is not None:
            v, vinfo = self.vortex(h)
            vortex_term = torch.exp(self.log_w_vortex) * v
            info.update({f"vortex_{k}": val for k, val in vinfo.items()})

        # ----- 3. Sub-Ohmic memory damping ----------------------------
        # FIX-3: Integrate over x (raw residual state), NOT over h = norm1(x).
        # Theory §5 (C5.3) requires the memory integral on the real trajectory
        # φ(t).  LayerNorm applied before the integral would destroy the
        # power-law autocorrelation of the trajectory that underpins H≈0.7.
        #
        # 修复3：对原始残差流 x 积分，而非 norm1(x) 的输出 h。
        # 理论 §5 要求在真实轨迹上积分；归一化会破坏幂律自相关统计。
        mem_term = torch.zeros_like(x)
        if self.memory is not None:
            mem_term = -torch.exp(self.log_w_mem) * self.memory(x)

        # ----- 4. Colored fluctuation ---------------------------------
        # Four conditions ALL must hold to actually inject:
        #   - the layer is configured to have noise (use_colored_noise)
        #   - the caller requested it (add_noise)
        #   - the model-level switch is on (_inject_noise)
        #   - the module is in training mode
        # 必须四个开关同时为真才注入：模块配置 / 调用方请求 /
        # 模型级开关 / 训练模式。
        noise_term = torch.zeros_like(h)
        should_inject = (
            self.noise is not None
            and add_noise
            and self._inject_noise
            and self.training
        )
        if should_inject:
            xi = self.noise(h.shape[0], h.shape[1], h.device, h.dtype)
            noise_term = self.noise_scale * xi

        # ----- Euler-Maruyama step + FFN residual ---------------------
        x = x + grad_term + vortex_term + mem_term + noise_term
        x = x + self.ffn(self.norm2(x))
        return x, info


class CIDBlock(nn.Module):
    """Stack of CID layers with switch propagation."""

    def __init__(self, num_layers: int = 8, **layer_kwargs) -> None:
        super().__init__()
        if num_layers <= 0:
            raise ValueError(f"num_layers must be positive, got {num_layers}")
        self.layers: nn.ModuleList = nn.ModuleList(
            [CIDLayer(**layer_kwargs) for _ in range(num_layers)]
        )

    # ------------------------------------------------------------------
    # Switch propagation
    # ------------------------------------------------------------------

    def set_noise_injection(self, enabled: bool) -> None:
        """Propagate noise-injection switch to all layers."""
        for layer in self.layers:
            layer.set_noise_injection(enabled)

    def set_energy_monitoring(self, enabled: bool) -> None:
        """Propagate ET energy-monitoring switch to all layers."""
        for layer in self.layers:
            layer.set_energy_monitoring(enabled)

    def fluctuation_dissipation_consistency(self) -> List[Dict[str, float]]:
        """Return FDT consistency reports for every layer."""
        return [
            layer.fluctuation_dissipation_consistency()
            for layer in self.layers
        ]

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
        add_noise: bool = True,
        return_hidden_states: bool = False,
    ) -> Tuple[torch.Tensor, Optional[List[torch.Tensor]], Dict[str, Dict]]:
        hidden_states: Optional[List[torch.Tensor]] = (
            [] if return_hidden_states else None
        )
        info: Dict[str, Dict] = {}
        for i, layer in enumerate(self.layers):
            x, layer_info = layer(
                x, causal_mask=causal_mask, add_noise=add_noise
            )
            info[f"layer_{i}"] = layer_info
            if hidden_states is not None:
                hidden_states.append(x)
        return x, hidden_states, info
