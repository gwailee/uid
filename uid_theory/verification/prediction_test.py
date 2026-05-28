# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28 — DEPRECATED. Re-routes to v2.0/v2.1 toolchain.
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

"""DEPRECATED v0.1 prediction tester — re-routed to v2.0/v2.1 toolchain.

.. deprecated:: 2.0
    The original v0.1 implementation of this module suffered from
    *three* methodological defects that have since been corrected in
    the dedicated v2.0+ modules:

    1. **Avalanche detection used ``|logits_a - logits_b|``**
       (a measure of stochastic forward-pass noise, NOT a Beggs-Plenz
       avalanche). Fixed in :mod:`avalanche_detector`.

    2. **Power-law fitting used log-binned linear regression**
       (a known-unreliable estimator). Fixed in
       :mod:`powerlaw_estimator` (Clauset-Shalizi-Newman MLE + KS test).

    3. **Hurst exponent used R/S analysis with noise injection ON**
       (circular measurement — the measured 1/f exponent could simply
       echo the injected noise spectrum). Fixed in
       :mod:`critical_exponents` (DFA gold-standard + mandatory
       ``disable_noise=True`` switch).

    This file is preserved ONLY as a thin re-routing wrapper, so any
    external code that still imports :class:`UIDPredictionTester`
    transparently runs the corrected v2.0+ pipeline (and emits a
    DeprecationWarning to alert the caller).

    **Please migrate to the new toolchain directly**:

        from uid_theory.verification.critical_exponents import (
            run_critical_exponent_battery,
        )
        from uid_theory.verification.avalanche_detector import (
            detect_avalanches,
        )
        from uid_theory.verification.powerlaw_estimator import (
            fit_power_law,
        )

----

本模块为 v0.1 遗留的预言检验器，已废弃。

原 v0.1 实现存在三处方法学缺陷，已在 v2.0+ 专用模块中修正：

1. **雪崩检测用 ``|logits_a - logits_b|``**（实际测的是前向随机噪声，
   并非 Beggs-Plenz 雪崩）—— 已由 :mod:`avalanche_detector` 修正。
2. **幂律拟合用对数分箱线性回归**（已知不可靠）—— 已由
   :mod:`powerlaw_estimator` 修正（Clauset-Shalizi-Newman MLE + KS）。
3. **Hurst 测量在噪声注入开启下进行**（循环测量：测出的 1/f 仅是
   注入噪声的回响）—— 已由 :mod:`critical_exponents` 修正
   （DFA 金标准 + 强制 ``disable_noise=True`` 开关）。

本文件保留只是为了让仍在 ``import UIDPredictionTester`` 的外部代码
透明地走 v2.0+ 修正后的流水线（并发出 DeprecationWarning）。
**请直接迁移到新工具链**。
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, Optional

import torch
from torch.utils.data import DataLoader

from .avalanche_detector import detect_avalanches
from .critical_exponents import (
    measure_hurst_exponent,
    measure_power_spectrum,
)
from .powerlaw_estimator import fit_power_law


_DEPRECATION_MSG = (
    "UIDPredictionTester is deprecated as of v2.0 due to three "
    "methodological defects in v0.1 (incorrect avalanche detection, "
    "unreliable log-binned power-law fit, circular Hurst measurement "
    "with noise injection ON). This wrapper now re-routes calls to "
    "the corrected v2.0+ toolchain (avalanche_detector, "
    "powerlaw_estimator, critical_exponents). Please migrate directly: "
    "see uid_theory/verification/critical_exponents.py."
)


class UIDPredictionTester:
    """DEPRECATED wrapper. Re-routes to the v2.0+ corrected toolchain.

    已废弃。透明转发至 v2.0+ 修正后的工具链。

    Construction emits a single ``DeprecationWarning``.
    """

    def __init__(
        self, model: torch.nn.Module, device: str = "cuda"
    ) -> None:
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
        self.model: torch.nn.Module = model
        self.device: str = str(device)

    # ------------------------------------------------------------------
    # Internal: honestly collect hidden states with noise injection OFF
    # ------------------------------------------------------------------

    def _collect_hidden_states_eval(
        self,
        sample_inputs: torch.Tensor,
        layer_idx: int = -1,
    ) -> "torch.Tensor":
        """Run the model in eval mode with noise injection DISABLED.

        这是 v2.0 的关键修正：测量临界涌现前必须关闭噪声注入，
        否则测出的 1/f / Hurst 仅是注入噪声的回响。
        """
        # Prefer top-level v2.1 API.
        switched = False
        prev_state: Optional[bool] = None
        if hasattr(self.model, "set_noise_injection"):
            # Best effort: try to record prior state if available.
            backbone = getattr(self.model, "backbone", None)
            if backbone is not None and backbone.layers:
                prev_state = bool(backbone.layers[0]._inject_noise)
            self.model.set_noise_injection(False)
            switched = True
        elif hasattr(self.model, "backbone") and hasattr(
            self.model.backbone, "set_noise_injection"
        ):
            if self.model.backbone.layers:
                prev_state = bool(
                    self.model.backbone.layers[0]._inject_noise
                )
            self.model.backbone.set_noise_injection(False)
            switched = True

        self.model.eval()
        try:
            with torch.no_grad():
                out = self.model(
                    sample_inputs.to(self.device),
                    output_hidden_states=True,
                )
        finally:
            # Restore the original injection state (do NOT force True).
            if switched and prev_state is not None:
                if hasattr(self.model, "set_noise_injection"):
                    self.model.set_noise_injection(prev_state)
                elif hasattr(self.model, "backbone"):
                    self.model.backbone.set_noise_injection(prev_state)

        if out.hidden_states is None:
            raise RuntimeError(
                "Model did not return hidden_states; pass "
                "output_hidden_states=True from its forward()."
            )
        return out.hidden_states[layer_idx]

    # ------------------------------------------------------------------
    # Re-routed tests (keep v0.1 API surface but call v2.0+ tools)
    # ------------------------------------------------------------------

    def test_avalanche_exponent(
        self,
        sample_inputs: torch.Tensor,
        n_pairs: int = 200,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """DEPRECATED. Re-routed to Beggs-Plenz + Clauset MLE pipeline.

        Args ``n_pairs`` and ``threshold`` are accepted for backward
        compatibility but IGNORED — the v0.1 forward-pair approach is
        no longer used.
        """
        del n_pairs, threshold  # silently ignored (see docstring)
        hidden = self._collect_hidden_states_eval(sample_inputs)
        hidden_np = hidden.detach().cpu().numpy()
        sizes = detect_avalanches(hidden_np, threshold_sigma=2.0)
        if len(sizes) < 100:
            return {
                "tau": float("nan"),
                "error": f"insufficient avalanches ({len(sizes)} < 100)",
                "n_events": int(len(sizes)),
            }
        fit = fit_power_law(sizes)
        return {
            "tau": float(fit.alpha),
            "tau_err": float(fit.alpha_se),
            "xmin": float(fit.xmin),
            "ks_statistic": float(fit.ks_statistic),
            "p_value": float(fit.p_value),
            "is_power_law": bool(fit.is_power_law),
            "theory": 1.5,
            "within": abs(fit.alpha - 1.5) < 0.2 and fit.is_power_law,
            "n_events": int(fit.n_tail),
            "_method": "Beggs-Plenz + Clauset-Shalizi-Newman MLE (v2.0)",
        }

    def test_hurst_exponent(
        self,
        sample_inputs: torch.Tensor,
        layer_idx: int = -1,
    ) -> Dict[str, Any]:
        """DEPRECATED. Re-routed to DFA gold-standard estimator."""
        hidden = self._collect_hidden_states_eval(sample_inputs, layer_idx)
        hidden_np = hidden.detach().cpu().numpy()
        # measure_hurst_exponent expects (n_seq, seq_len, hidden_dim).
        # If we collected only a single forward, add the batch dim.
        if hidden_np.ndim == 2:
            hidden_np = hidden_np[None, :, :]
        result = measure_hurst_exponent(hidden_np)
        hurst = float(result.hurst_mean)
        return {
            "hurst": hurst,
            "hurst_std": float(result.hurst_std),
            "n_series": int(result.n_series),
            "theory_range": [0.6, 0.8],
            "within": (0.6 <= hurst <= 0.8),
            "_method": "DFA (v2.0 gold standard, noise injection OFF)",
        }

    def test_power_spectrum(
        self,
        sample_inputs: torch.Tensor,
        layer_idx: int = -1,
    ) -> Dict[str, Any]:
        """DEPRECATED. Re-routed to v2.0 spectrum estimator."""
        hidden = self._collect_hidden_states_eval(sample_inputs, layer_idx)
        hidden_np = hidden.detach().cpu().numpy()
        if hidden_np.ndim == 2:
            hidden_np = hidden_np[None, :, :]
        result = measure_power_spectrum(hidden_np)
        beta = float(result.beta_mean)
        return {
            "beta": beta,
            "beta_err": float(result.beta_std),
            "r_squared": float(result.r_squared_mean),
            "n_series": int(result.n_series),
            "theory_range": [0.7, 1.3],
            "within": (0.7 <= beta <= 1.3),
            "_method": "rFFT + log-log regression (noise injection OFF)",
        }

    def test_parameter_efficiency(
        self,
        baseline_model: torch.nn.Module,
        eval_loader: DataLoader,
    ) -> Dict[str, Any]:
        """DEPRECATED. Use ``experiments/run_scaling_law.py`` instead.

        The v0.1 "equal model size, compare PPL" approach is not a
        valid parameter-efficiency test: the 5x/10x targets demand
        an iso-FLOP scaling-law study, not a single point comparison.
        See README §"Pre-registered falsification conditions" point 1.

        This wrapper still returns single-point PPL numbers as a
        rough indicator, but the canonical comparison is the scaling
        law in experiments/run_scaling_law.py.
        """
        import numpy as np

        def _eval_loss(model, loader, max_batches=50):
            model.eval()
            total_loss = 0.0
            total_tokens = 0
            with torch.no_grad():
                for i, batch in enumerate(loader):
                    if i >= max_batches:
                        break
                    input_ids = batch["input_ids"].to(self.device)
                    labels = batch.get("labels", input_ids).to(self.device)
                    out = model(input_ids=input_ids, labels=labels)
                    n = int((labels != -100).sum().item())
                    total_loss += float(out.loss.item()) * n
                    total_tokens += n
            return total_loss / max(total_tokens, 1)

        cid_loss = _eval_loss(self.model, eval_loader)
        trans_loss = _eval_loss(baseline_model, eval_loader)
        cid_params = int(sum(p.numel() for p in self.model.parameters()))
        trans_params = int(
            sum(p.numel() for p in baseline_model.parameters())
        )
        cid_ppl = float(np.exp(cid_loss))
        trans_ppl = float(np.exp(trans_loss))
        return {
            "cid_params": cid_params,
            "trans_params": trans_params,
            "cid_ppl": cid_ppl,
            "trans_ppl": trans_ppl,
            "param_ratio": trans_params / cid_params,
            "ppl_ratio_cid_over_trans": cid_ppl / trans_ppl,
            "theory_min": 5.0,
            "theory_target": 10.0,
            "within": (cid_ppl <= trans_ppl) and (cid_params <= trans_params),
            "_method": (
                "Single-point PPL comparison (DEPRECATED — use "
                "experiments/run_scaling_law.py for the canonical "
                "iso-FLOP scaling-law test)"
            ),
        }

    def run_all(
        self,
        sample_inputs: torch.Tensor,
        baseline_model: Optional[torch.nn.Module] = None,
        eval_loader: Optional[DataLoader] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Run all available tests (each re-routed to v2.0+ tools)."""
        results: Dict[str, Dict[str, Any]] = {}
        try:
            results["avalanche"] = self.test_avalanche_exponent(
                sample_inputs
            )
        except Exception as exc:  # pylint: disable=broad-except
            results["avalanche"] = {"error": str(exc)}
        try:
            results["hurst"] = self.test_hurst_exponent(sample_inputs)
        except Exception as exc:  # pylint: disable=broad-except
            results["hurst"] = {"error": str(exc)}
        try:
            results["power_spectrum"] = self.test_power_spectrum(
                sample_inputs
            )
        except Exception as exc:  # pylint: disable=broad-except
            results["power_spectrum"] = {"error": str(exc)}
        if baseline_model is not None and eval_loader is not None:
            try:
                results["efficiency"] = self.test_parameter_efficiency(
                    baseline_model, eval_loader
                )
            except Exception as exc:  # pylint: disable=broad-except
                results["efficiency"] = {"error": str(exc)}
        return results
