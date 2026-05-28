# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Add zero-extra-parameter mode that derives the phase angle from
#     a non-owning reference to an external weight (e.g. attention
#     k_proj.weight), in keeping with §14.2's no-extra-params spirit.
#   * Bound the output phase to (-pi, pi) via tanh*pi to avoid
#     ungrounded high-frequency oscillations during training.
#   * Phase-invariant diagnostics (cos.mean, sin.mean) recommended
#     downstream; raw phases.mean() loses meaning under the 2*pi
#     ambiguity inherent in Berry phase.
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

"""Berry-phase layer (classical emulation).

Berry 几何相位层（经典模拟版本）。

We pair the real channels of the hidden state into 2D blocks and
rotate each pair by an angle ``phi`` computed from a (possibly
weight-shared) Berry connection.  This emulates the geometric phase
pick-up of a quantum state under adiabatic parameter transport.

理论：把隐状态相邻两维视为复数的实部/虚部对，按可学习的 Berry 联络
诱导一个角度，对每个二维子空间施加旋转。

v2.1 design notes:
    - "Owned" mode (legacy):  phase_proj is a dedicated (H -> H/2)
      Linear layer (~H^2/2 extra params per layer).
    - "Shared" mode (default when ``weight_ref`` is provided):
      derive the phase angle from the antisymmetric part of an
      external weight (e.g. attention k_proj.weight) — zero extra
      matrix parameters; only one scalar gate is added.
    - Output phases are bounded to (-pi, pi) via tanh*pi.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import torch
import torch.nn as nn


class BerryPhaseLayer(nn.Module):
    """Apply per-pair U(1) rotation derived from a Berry connection.

    根据 Berry 联络给出的角度，对成对的特征维施加 U(1) 旋转。

    Two construction modes:

        weight_ref is None:
            Build a dedicated (H -> H/2) Linear projection. Legacy
            behaviour with ~H*H/2 extra parameters per layer.

        weight_ref is provided (recommended):
            Build the phase angle from the antisymmetric part of the
            referenced (H, H) weight, mapped to H/2 via a fixed
            half-summing combiner. Zero extra matrix parameters; only
            one scalar gate (log_phase_strength) is added per layer.
    """

    def __init__(
        self,
        hidden_size: int,
        weight_ref: Optional[nn.Parameter] = None,
    ) -> None:
        """Initialise the layer.

        Args:
            hidden_size: Feature dimension; must be even.
            weight_ref:  Optional non-owning reference to an external
                         weight tensor (shape (H, H) or any (>=H, >=H));
                         when provided, the layer runs in
                         zero-extra-parameter mode.
        """
        super().__init__()
        if hidden_size % 2 != 0:
            raise ValueError(
                f"hidden_size must be even for paired rotation, got "
                f"{hidden_size}"
            )
        self.hidden_size: int = int(hidden_size)
        self.half: int = hidden_size // 2

        # +1 learnable scalar gate (always created): controls the
        # amplitude of the rotation, analogous to log_temp_diff in
        # VortexField.
        self.log_phase_strength: nn.Parameter = nn.Parameter(
            torch.tensor(-2.0)
        )

        if weight_ref is None:
            # Legacy: dedicated H -> H/2 Linear with small init.
            self.phase_proj: Optional[nn.Linear] = nn.Linear(
                hidden_size, self.half
            )
            nn.init.zeros_(self.phase_proj.bias)
            nn.init.normal_(self.phase_proj.weight, std=0.01)
            self._weight_ref: Optional[nn.Parameter] = None
        else:
            # Shared: zero extra matrix parameters.
            self.phase_proj = None
            self._weight_ref = weight_ref

    # ------------------------------------------------------------------
    # Internal: build the per-pair phase angle from the shared weight
    # ------------------------------------------------------------------

    def _phases_from_weight_ref(
        self, x: torch.Tensor,
    ) -> torch.Tensor:
        """Derive phase angles from the antisymmetric part of weight_ref.

        Build J = (W - W^T)/2  (shape (H, H)), then form
            phase_logits = x @ J^T          (shape (B, S, H))
            phases       = phase_logits[..., :H/2]   # take first half
        before bounding via tanh*pi. This mirrors the §14.2 zero-extra-
        parameter trick.
        """
        if self._weight_ref is None:
            raise RuntimeError("BerryPhaseLayer has no weight reference")
        w = self._weight_ref
        # If rectangular, take the top-left (H, H) square sub-block.
        if w.shape[0] != w.shape[1]:
            m = min(w.shape[0], w.shape[1], self.hidden_size)
            w = w[:m, :m]
        j = 0.5 * (w - w.transpose(-2, -1))  # (H, H)
        # x @ J^T : (B, S, H).
        logits = torch.matmul(x, j.transpose(-2, -1))
        # Take the first H/2 channels as the per-pair phase logits.
        return logits[..., : self.half]

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self, x: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Compute paired rotation and return output plus bounded phase.

        Args:
            x: Input of shape (B, S, H). 输入。

        Returns:
            ``(y, phases)`` where ``y`` is the rotated tensor of the
            same shape and ``phases`` is the (B, S, H/2) tensor of
            *bounded* angles in (-pi, pi). Use phase-invariant
            diagnostics like ``cos(phases).mean()`` downstream.
        """
        b, s, h = x.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, "
                f"got {h}"
            )

        x_real = x[..., : self.half]
        x_imag = x[..., self.half:]

        if self.phase_proj is not None:
            raw = self.phase_proj(x)  # (B, S, H/2)
        else:
            raw = self._phases_from_weight_ref(x)  # (B, S, H/2)

        # Bound to (-pi, pi) and gate by the learnable strength scalar.
        # tanh keeps gradients well-conditioned under arbitrary input
        # magnitudes; log_phase_strength controls the effective range.
        strength = torch.exp(self.log_phase_strength)
        phases = strength * math.pi * torch.tanh(raw)

        cos = torch.cos(phases)
        sin = torch.sin(phases)
        y_real = cos * x_real - sin * x_imag
        y_imag = sin * x_real + cos * x_imag
        y = torch.cat([y_real, y_imag], dim=-1)
        return y, phases
