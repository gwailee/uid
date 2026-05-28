# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Propagate v2.1 keys (use_et_symmetric, noise_type, noise_tau,
#     noise_beta) PLUS all QID-level toggles to the embedded QIDLayer.
#   * Expose top-level switch APIs (set_noise_injection,
#     set_energy_monitoring, set_temperature) so users do not need
#     to pierce through fid.qid.cid_base.* manually.
#   * Disentangle JSON-safe diagnostics from autograd-bearing loss
#     tensors in the info dict, and add extract_loss_tensors() helper.
#     This fixes a latent json.dumps crash in experiments/run_*.py
#     when curvature_weight > 0.
#   * Report THREE FID-layer geometric diagnostics that map directly
#     to README predictions 4 / 6:
#       - 'fisher_anisotropy_eta'   (Theory §6.1 prediction)
#       - 'ricci_scalar_surrogate'  (Theory §6.2 prediction)
#       - 'anisotropy_legacy'       (the pre-v2.1 surrogate, kept for
#                                    back-compat with old result files)
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

"""FID layer: QID dynamics with a geometric probe and soft regulariser.

FID 主层：在 QID 基础上加入几何探针与软正则项。

The geometric pieces (Fisher metric, curvature surrogate) are *probes*,
not strict implementations of the FID field equation. Their primary
role here is diagnostic and as a mild regulariser that discourages
extreme anisotropy in hidden-state representations.

几何组件 (Fisher 度量、曲率代理) 主要承担**诊断与软正则**角色，并非 FID
场方程的严格实现；它们的作用是抑制隐状态表示的极端各向异性。

v2.1 design notes:
    - All v2.1-relevant CID / QID toggles must be forwarded explicitly
      so that downstream ablations (e.g. cid_full_no_et applied at the
      FID level) really take effect.
    - Top-level switch APIs (set_noise_injection / set_energy_monitoring
      / set_temperature) mirror those exposed on UIDModel.
    - The info dict is strictly JSON-safe; loss tensors live under
      a separate dedicated key carrying the LOSS_PREFIX prefix.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import torch
import torch.nn as nn

from ..qid.qid_layer import QIDLayer
from .curvature import ScalarCurvatureProbe


# Loss tensors smuggled through the info dict carry this prefix, so a
# caller can detect them with extract_loss_tensors() before any JSON
# serialisation step.
LOSS_PREFIX: str = "__loss__"


def extract_loss_tensors(info: Dict[str, Any]) -> Dict[str, torch.Tensor]:
    """Return (and remove) all autograd-bearing tensors hidden in ``info``.

    从 info 字典中分离出（并移除）所有带梯度的 Tensor，
    用于让 host model 把它们加入总损失，同时让 info 保持 JSON 可序列化。

    Args:
        info: Dictionary returned by ``FIDLayer.forward`` (mutated
              in place — the LOSS_PREFIX entries are removed).

    Returns:
        Dictionary mapping the loss name (with prefix stripped) to the
        corresponding Tensor.
    """
    out: Dict[str, torch.Tensor] = {}
    for k in list(info.keys()):
        if k.startswith(LOSS_PREFIX):
            out[k[len(LOSS_PREFIX):]] = info.pop(k)
    return out


class FIDLayer(nn.Module):
    """QID layer enriched with a curvature-based diagnostic probe.

    在 QID 层上叠加曲率诊断探针的 FID 主层。
    """

    def __init__(
        self,
        hidden_size: int = 768,
        num_heads: int = 8,
        dropout: float = 0.1,
        curvature_weight: float = 0.0,
        # ---- v2.1 keys forwarded to QIDLayer / CIDLayer --------------
        use_et_symmetric: bool = True,
        noise_type: str = "ou",
        noise_tau: float = 10.0,
        noise_beta: float = 1.0,
        # ---- QID-level configuration ---------------------------------
        use_berry: bool = True,
        hamiltonian_mode: str = "shared_with_ffn",
        lindblad_mode: str = "off",
        num_lindblad_channels: int = 4,
        quantum_noise_mode: str = "ou",  # v2.1: default OU, aligned w/ CID
        quantum_noise_tau: float = 10.0,
        quantum_noise_init_temperature: float = 1.0,
    ) -> None:
        """Initialise the FID layer.

        Args:
            hidden_size:                Feature dimension.
            num_heads:                  Attention heads.
            dropout:                    FFN dropout.
            curvature_weight:           Strength of the soft curvature
                                        penalty that the host model can
                                        read from ``info`` (under the
                                        LOSS_PREFIX key) and add to the
                                        total loss.
            use_et_symmetric:           v2.1 §8.5: ET symmetric attention.
            noise_type:                 v2.1 CID-side colored noise impl.
            noise_tau:                  v2.1 CID-side OU tau.
            noise_beta:                 v2.1 CID-side FFT beta.
            use_berry:                  QID Berry-phase toggle.
            hamiltonian_mode:           QID Hamiltonian mode (see
                                        qid_layer.HAMILTONIAN_MODES).
            lindblad_mode:              QID Lindblad mode.
            num_lindblad_channels:      QID Lindblad channel count.
            quantum_noise_mode:         QID quantum-noise mode ("ou" or
                                        "fft"). Default "ou" in v2.1.
            quantum_noise_tau:          QID quantum-noise tau (OU mode).
            quantum_noise_init_temperature:
                                        QID quantum-noise initial T.
        """
        super().__init__()
        self.hidden_size: int = int(hidden_size)
        self.curvature_weight: float = float(curvature_weight)

        # ----- Embedded QID layer -------------------------------------
        self.qid: QIDLayer = QIDLayer(
            hidden_size=hidden_size,
            num_heads=num_heads,
            dropout=dropout,
            # v2.1 propagation
            use_et_symmetric=use_et_symmetric,
            noise_type=noise_type,
            noise_tau=noise_tau,
            noise_beta=noise_beta,
            # QID-specific
            use_berry=use_berry,
            hamiltonian_mode=hamiltonian_mode,
            lindblad_mode=lindblad_mode,
            num_lindblad_channels=num_lindblad_channels,
            quantum_noise_mode=quantum_noise_mode,
            quantum_noise_tau=quantum_noise_tau,
            quantum_noise_init_temperature=quantum_noise_init_temperature,
        )

        # ----- Curvature probe ----------------------------------------
        self.curvature: ScalarCurvatureProbe = ScalarCurvatureProbe(
            hidden_size
        )

    # ------------------------------------------------------------------
    # Public switch APIs (mirror CID / QID parity)
    # ------------------------------------------------------------------

    def set_noise_injection(self, enabled: bool) -> None:
        """Toggle noise injection at ALL underlying layers."""
        self.qid.set_noise_injection(enabled)

    def set_energy_monitoring(self, enabled: bool) -> None:
        """Toggle §8.5 ET energy monitoring at the CID base layer."""
        self.qid.set_energy_monitoring(enabled)

    def set_temperature(self, temperature: float) -> None:
        """Set the environment temperature for QID's quantum noise."""
        self.qid.quantum_noise.set_temperature(temperature)

    # ------------------------------------------------------------------
    # Diagnostics: parameter budget
    # ------------------------------------------------------------------

    def count_extras(self) -> Dict[str, int]:
        """Return a parameter budget breakdown for THIS FID layer.

        Combines QID's count_extras() with FID-specific extras
        (the Fisher metric jitter buffer adds no learnable params).
        """
        qid_extras = self.qid.count_extras()
        out = {f"qid_{k}": v for k, v in qid_extras.items()}
        # FID itself adds no learnable parameters (the FisherMetric and
        # curvature probe are non-parametric in this implementation).
        out["fid_extras"] = 0
        out["total"] = int(sum(out.values()) - out["total"]
                           if "total" in out else sum(out.values()))
        # Recompute total cleanly (the above expression is intentionally
        # defensive, but we recompute to be safe).
        out["total"] = int(
            sum(v for k, v in out.items() if k != "total")
        )
        return out

    # ------------------------------------------------------------------
    # Forward
    # ------------------------------------------------------------------

    def forward(
        self,
        x: torch.Tensor,
        causal_mask: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, Any]]:
        """Run one FID step.

        Args:
            x:           Input of shape (B, S, H). 输入。
            causal_mask: Optional causal mask. 可选因果掩码。

        Returns:
            ``(x_next, info)`` where ``info`` contains:
              * all QID diagnostics (JSON-safe floats);
              * 'fisher_anisotropy_eta' — Theory §6.1 prediction (B,);
              * 'ricci_scalar_surrogate' — Theory §6.2 prediction;
              * 'anisotropy_legacy' — pre-v2.1 trace(g^2)/trace(g)^2-1/H;
              * (if curvature_weight > 0)
                '__loss__curvature' — a torch.Tensor that the host model
                must extract via extract_loss_tensors() before any
                JSON dump.
        """
        x_next, info = self.qid(x, causal_mask=causal_mask)

        # ------------------------------------------------------------------
        # Geometric diagnostics (Theory §6.1 / §6.2 directly addressable)
        # ------------------------------------------------------------------
        # Compute the metric once and reuse for all three reporters
        # to avoid redundant tensor ops on the hot path.
        metric = self.curvature.fisher.compute(x_next)
        eta = self.curvature.compute_anisotropy_eta(metric)
        ricci = self.curvature.compute_ricci_scalar_surrogate(metric)
        legacy = self.curvature.compute_legacy_anisotropy(metric)

        with torch.no_grad():
            info["fisher_anisotropy_eta"] = float(eta.mean().item())
            info["ricci_scalar_surrogate"] = float(ricci.mean().item())
            info["anisotropy_legacy"] = float(legacy.mean().item())
            # Backward compat: original 'curvature' key kept, pointing
            # to the legacy surrogate.
            info["curvature"] = info["anisotropy_legacy"]

        # ------------------------------------------------------------------
        # Soft curvature penalty (autograd-bearing tensor)
        # ------------------------------------------------------------------
        # We use the LEGACY surrogate for the loss so that downstream
        # behaviour is unchanged when users opted in via curvature_weight.
        # The (much sharper) eta and ricci diagnostics are reported
        # separately for analysis.
        if self.curvature_weight > 0.0:
            loss_tensor = self.curvature_weight * legacy.mean()
            # Mark with LOSS_PREFIX so json.dumps cannot accidentally
            # swallow the Tensor.
            info[f"{LOSS_PREFIX}curvature"] = loss_tensor

        return x_next, info
