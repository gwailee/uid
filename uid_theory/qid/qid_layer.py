# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Propagate v2.1 keys (noise_type, noise_tau, noise_beta,
#     use_et_symmetric) to the embedded CIDLayer so QID experiments
#     can ablate Theory §8.5 / §14.2 toggles too.
#   * Adopt zero-extra-parameter Hamiltonian generator: re-use the
#     CID FFN[0] antisymmetric projection (same trick as VortexField),
#     gated by a single learnable scalar.
#   * Make Lindblad channels OPTIONAL (off by default) and support
#     a shared-weights mode that adds only ONE H*H matrix instead
#     of K * H*H (significant parameter savings).
#   * Expose set_noise_injection / set_energy_monitoring at the QID
#     level for parity with the CID API.
#   * Add count_extras() diagnostic for regression tests.
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

"""QID block: CID base plus classical surrogates of quantum corrections.

QID 主层：在 CID 基础上叠加量子修正项的经典代理。

The quantum corrections implemented here are *classical emulations*:
    * Hamiltonian flow via an anti-symmetric linear map.
        - v2.1 default: built from the CID FFN[0] weight's antisymmetric
          part (zero extra matrix parameters; only +1 scalar gate).
        - legacy mode: dedicated H*H weight matrix (kept for back-compat).
    * Lindblad dissipation as an optional learnable contractive map
      (phenomenological surrogate; not a faithful Kraus decomposition).
        - default OFF (zero extra params)
        - "shared" mode: 1 H*H matrix shared across all channels
        - "independent" mode: K H*H matrices (legacy).
    * Berry phase via per-pair U(1) rotation (see berry_phase.py).
    * Quantum colored noise with explicit zero-point branch (FFT or OU).

Real quantum advantage requires actual quantum hardware; this module
exists so that the API and training pipeline are forward-compatible.

本模块为量子修正的经典代理实现。Lindblad 项以现象学映射代替严格的
Kraus 形式，是工程近似，不构成数学严格的耗散通道。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch
import torch.nn as nn

from ..cid.cid_layer import CIDLayer
from .berry_phase import BerryPhaseLayer
from .quantum_noise import QuantumColoredNoise


# Allowed modes for the Hamiltonian generator and Lindblad operators.
HAMILTONIAN_MODES = {"shared_with_ffn", "dedicated"}
LINDBLAD_MODES = {"off", "shared", "independent"}


class QIDLayer(nn.Module):
    """CID layer plus quantum-style corrections.

    在 CID 层基础上加入量子修正项。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        # ------ Quantum-correction toggles -----------------------------
        use_berry: bool = True,
        hamiltonian_mode: str = "shared_with_ffn",
        lindblad_mode: str = "off",
        num_lindblad_channels: int = 4,
        # ------ Quantum-noise selection --------------------------------
        quantum_noise_mode: str = "fft",  # "fft" or "ou"
        quantum_noise_tau: float = 10.0,
        quantum_noise_init_temperature: float = 1.0,
        # ------ FFN dropout --------------------------------------------
        dropout: float = 0.1,
        # ------ v2.1 keys forwarded to the embedded CIDLayer -----------
        noise_type: str = "ou",
        noise_tau: float = 10.0,
        noise_beta: float = 1.0,
        use_et_symmetric: bool = True,
    ) -> None:
        """Initialise the QID layer.

        Args:
            hidden_size:                Feature dimension.
            num_heads:                  Number of attention heads.
            use_berry:                  Toggle Berry-phase rotation.
            hamiltonian_mode:           "shared_with_ffn" (zero extra
                                        matrix params, default) or
                                        "dedicated" (legacy: own H*H).
            lindblad_mode:              "off" / "shared" (1 matrix) /
                                        "independent" (K matrices,
                                        legacy).
            num_lindblad_channels:      Number of Lindblad channels;
                                        only used when
                                        lindblad_mode != "off".
            quantum_noise_mode:         "fft" or "ou" — passed to
                                        QuantumColoredNoise.
            quantum_noise_tau:          OU relaxation time when
                                        quantum_noise_mode="ou".
            quantum_noise_init_temperature:
                                        Initial T for the QFDT spectrum.
            dropout:                    FFN dropout.
            noise_type:                 v2.1: CID-side colored-noise
                                        implementation.
            noise_tau:                  v2.1: CID-side OU tau.
            noise_beta:                 v2.1: CID-side FFT beta.
            use_et_symmetric:           v2.1: Theory §8.5 ET symmetric
                                        attention switch.
        """
        super().__init__()
        if hamiltonian_mode not in HAMILTONIAN_MODES:
            raise ValueError(
                f"hamiltonian_mode must be one of "
                f"{sorted(HAMILTONIAN_MODES)}, got {hamiltonian_mode!r}"
            )
        if lindblad_mode not in LINDBLAD_MODES:
            raise ValueError(
                f"lindblad_mode must be one of {sorted(LINDBLAD_MODES)}, "
                f"got {lindblad_mode!r}"
            )

        self.hidden_size: int = int(hidden_size)
        self.use_berry: bool = bool(use_berry)
        self.hamiltonian_mode: str = hamiltonian_mode
        self.lindblad_mode: str = lindblad_mode
        self.num_lindblad_channels: int = int(num_lindblad_channels)
        self.quantum_noise_mode: str = str(quantum_noise_mode).lower()

        # ----- CID base (with v2.1 params propagated) -----------------
        # We disable CID's own colored noise because the QID layer
        # injects its own quantum-noise term below.
        self.cid_base: CIDLayer = CIDLayer(
            hidden_size=hidden_size,
            num_heads=num_heads,
            use_vortex=True,
            use_memory=True,
            use_colored_noise=False,
            dropout=dropout,
            # v2.1 propagation
            noise_type=noise_type,
            noise_tau=noise_tau,
            noise_beta=noise_beta,
            use_et_symmetric=use_et_symmetric,
        )

        # ----- Hamiltonian generator ----------------------------------
        # +1 learnable scalar gate (always created).
        self.log_h_strength: nn.Parameter = nn.Parameter(
            torch.tensor(-3.0)
        )
        if hamiltonian_mode == "dedicated":
            # Legacy: dedicated H*H matrix (kept for backward compat).
            self.hamiltonian_weight: Optional[nn.Parameter] = nn.Parameter(
                torch.randn(hidden_size, hidden_size) * 0.01
            )
        else:
            # shared_with_ffn: zero extra matrix params; we will derive
            # the antisymmetric generator from CID FFN[0].weight at
            # forward time (analogous to VortexField).
            self.hamiltonian_weight = None
            # Hold a non-owning reference; do NOT register as parameter.
            self._ffn0_weight_ref: nn.Parameter = (
                self.cid_base.ffn[0].weight
            )

        # ----- Lindblad channels --------------------------------------
        self.lindblad_ops: Optional[nn.ModuleList]
        if lindblad_mode == "off":
            self.lindblad_ops = None
            self.log_lindblad_rates = None
        elif lindblad_mode == "shared":
            # 1 matrix shared across all "channels".
            self.lindblad_ops = nn.ModuleList([
                nn.Linear(hidden_size, hidden_size, bias=False),
            ])
            self.log_lindblad_rates: nn.Parameter = nn.Parameter(
                torch.full((num_lindblad_channels,), -4.0)
            )
        else:  # "independent" (legacy)
            self.lindblad_ops = nn.ModuleList([
                nn.Linear(hidden_size, hidden_size, bias=False)
                for _ in range(num_lindblad_channels)
            ])
            self.log_lindblad_rates = nn.Parameter(
                torch.full((num_lindblad_channels,), -4.0)
            )

        # ----- Berry phase --------------------------------------------
        if use_berry:
            self.berry: Optional[BerryPhaseLayer] = BerryPhaseLayer(
                hidden_size,
                # v2.1: prefer zero-extra-parameter mode by default;
                # see berry_phase.py for the new constructor.
                weight_ref=self.cid_base.attn.k_proj.weight,
            )
        else:
            self.berry = None

        # ----- Quantum colored noise ----------------------------------
        self.quantum_noise: QuantumColoredNoise = QuantumColoredNoise(
            hidden_size,
            mode=self.quantum_noise_mode,
            tau=quantum_noise_tau,
            init_temperature=quantum_noise_init_temperature,
        )

        # ----- Bounded mixing coefficient via sigmoid -----------------
        self.quantum_logit: nn.Parameter = nn.Parameter(
            torch.tensor(-2.0)
        )

    # ------------------------------------------------------------------
    # Public switch propagation (parity with CIDLayer)
    # ------------------------------------------------------------------

    def set_noise_injection(self, enabled: bool) -> None:
        """Toggle BOTH CID and quantum-noise injection."""
        # CID base does not currently inject its own noise (we built it
        # with use_colored_noise=False), but we still propagate for
        # forward compatibility / future configurations.
        if hasattr(self.cid_base, "set_noise_injection"):
            self.cid_base.set_noise_injection(enabled)
        self._inject_quantum_noise: bool = bool(enabled)

    def set_energy_monitoring(self, enabled: bool) -> None:
        """Forward to CID base for ET energy monitoring (Theory §8.5)."""
        if hasattr(self.cid_base, "set_energy_monitoring"):
            self.cid_base.set_energy_monitoring(enabled)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def count_extras(self) -> Dict[str, int]:
        """Count the EXTRA parameters QID adds on top of pure CID.

        统计 QID 在 CID 之上引入的额外参数数量；
        用于 §14.2 零参数原则的回归测试。

        Returns:
            Dict listing per-component extra parameter counts plus a
            "total" entry.
        """
        out: Dict[str, int] = {}

        # Hamiltonian: in shared mode this is just 1 scalar (log_h_strength).
        # In dedicated mode it is H*H + 1.
        h_count = self.log_h_strength.numel()
        if self.hamiltonian_weight is not None:
            h_count += self.hamiltonian_weight.numel()
        out["hamiltonian"] = int(h_count)

        # Lindblad: depends on mode.
        l_count = 0
        if self.lindblad_ops is not None:
            l_count += sum(
                p.numel() for op in self.lindblad_ops for p in op.parameters()
            )
        if self.log_lindblad_rates is not None:
            l_count += self.log_lindblad_rates.numel()
        out["lindblad"] = int(l_count)

        # Berry phase: depends on its own implementation (see berry_phase.py).
        b_count = 0
        if self.berry is not None:
            b_count = sum(p.numel() for p in self.berry.parameters())
        out["berry"] = int(b_count)

        # Quantum noise.
        out["quantum_noise"] = int(
            sum(p.numel() for p in self.quantum_noise.parameters())
        )

        # Mixing scalar.
        out["mixing_logit"] = int(self.quantum_logit.numel())

        out["total"] = int(sum(out.values()))
        return out

    # ------------------------------------------------------------------
    # Internal building blocks
    # ------------------------------------------------------------------

    def _hamiltonian_step(
        self, x: torch.Tensor, dt: float = 0.1
    ) -> torch.Tensor:
        """First-order unitary step using an anti-symmetrised generator.

        反对称化生成元的一阶幺正演化近似。

        In "shared_with_ffn" mode (default), the antisymmetric matrix
        is built on the fly from the CID FFN[0] weight — zero extra
        matrix parameters. In "dedicated" mode it uses the layer's own
        H*H weight. In both cases the strength is gated by a single
        learnable scalar (log_h_strength).
        """
        # Source matrix (H_eff or H_dim).
        if self.hamiltonian_weight is not None:
            # Dedicated H*H matrix.
            w = self.hamiltonian_weight
            # If it is rectangular for any reason, take its top-left square.
            if w.shape[0] != w.shape[1]:
                m = min(w.shape[0], w.shape[1], self.hidden_size)
                w = w[:m, :m]
        else:
            # Shared with CID FFN[0]; FFN expansion makes it (4H, H),
            # so we take the top-left (H, H) square sub-block.
            w = self._ffn0_weight_ref
            if w.shape[0] != w.shape[1]:
                m = min(w.shape[0], w.shape[1], self.hidden_size)
                w = w[:m, :m]

        h_antisym = 0.5 * (w - w.transpose(-2, -1))
        strength = torch.exp(self.log_h_strength)
        # x_new = x - dt * strength * (h_antisym @ x).
        delta = torch.einsum("ij,bsj->bsi", h_antisym, x)
        return x - dt * strength * delta

    def _lindblad_step(self, x: torch.Tensor) -> torch.Tensor:
        """Phenomenological dissipation (not a faithful Kraus form).

        现象学耗散项；off 模式下直接返回 0。
        """
        if self.lindblad_ops is None or self.log_lindblad_rates is None:
            return torch.zeros_like(x)

        out = torch.zeros_like(x)
        rates = torch.exp(self.log_lindblad_rates)

        if self.lindblad_mode == "shared":
            # Single shared op, applied K times with different rates.
            shared_op = self.lindblad_ops[0]
            for k in range(self.num_lindblad_channels):
                out = out + rates[k] * (shared_op(x) - 0.5 * x)
        else:
            # Independent: each channel has its own op.
            for i, op in enumerate(self.lindblad_ops):
                out = out + rates[i] * (op(x) - 0.5 * x)
        return out

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """Run one QID step.

        Args:
            x:           Input of shape (B, S, H). 输入。
            causal_mask: Optional causal mask. 可选因果掩码。

        Returns:
            Tuple ``(x_next, info)``. 输出张量及诊断信息字典。
        """
        info: Dict[str, float] = {}

        # 1. CID base step (no CID-side noise injection here).
        x_classical, cid_info = self.cid_base(
            x, causal_mask=causal_mask, add_noise=False,
        )
        info["cid_layers"] = sum(
            1 for k in cid_info if k.startswith("vortex_")
        )  # cheap marker
        # Forward ET energy if CID has it enabled.
        if "et_energy" in cid_info:
            info["et_energy"] = float(cid_info["et_energy"])

        # 2. Quantum corrections (each is a delta against x_classical).
        delta = torch.zeros_like(x_classical)
        delta = delta + (
            self._hamiltonian_step(x_classical) - x_classical
        )
        if self.lindblad_mode != "off":
            delta = delta + 0.1 * self._lindblad_step(x_classical)

        if self.berry is not None:
            y, phases = self.berry(x_classical)
            delta = delta + (y - x_classical)
            with torch.no_grad():
                # Phase-invariant diagnostics: cos.mean is invariant
                # to the 2*pi ambiguity inherent in Berry phase.
                info["berry_cos_mean"] = float(
                    torch.cos(phases).mean().item()
                )
                info["berry_phase_std"] = float(phases.std().item())

        inject_qn = (
            getattr(self, "_inject_quantum_noise", True)
            and self.training
        )
        if inject_qn:
            qn, qn_info = self.quantum_noise(
                x_classical.shape[0],
                x_classical.shape[1],
                x_classical.device,
                x_classical.dtype,
            )
            delta = delta + 0.01 * qn
            info.update({f"qnoise_{k}": v for k, v in qn_info.items()})

        weight = torch.sigmoid(self.quantum_logit)
        info["quantum_weight"] = float(weight.detach().item())
        info["hamiltonian_strength"] = float(
            torch.exp(self.log_h_strength).detach().item()
        )
        return x_classical + weight * delta, info
