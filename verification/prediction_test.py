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

"""Falsification tests for the UID theory predictions.

UID 理论可证伪预言的检验器。

Implemented tests:
    1. Avalanche-size exponent ``tau``  -- expected ~ 1.5.
    2. Hurst exponent ``H``             -- expected ~ 0.6 - 0.8.
    3. Power-spectrum slope ``beta``    -- expected ~ 0.7 - 1.3.
    4. Parameter efficiency vs. baseline -- expected >= 5x.

实现的测试：
    1. 雪崩规模指数 tau，理论值约 1.5。
    2. Hurst 指数 H，理论区间 0.6 - 0.8。
    3. 功率谱斜率 beta，理论区间 0.7 - 1.3。
    4. 相对基线的参数效率，理论应 >= 5x。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import numpy as np
import torch
from scipy import stats
from scipy.fft import rfft, rfftfreq
from torch.utils.data import DataLoader


class UIDPredictionTester:
    """Wrapper running all falsification tests on a trained model.

    针对训练好的模型运行全部可证伪测试的封装类。
    """

    def __init__(
        self, model: torch.nn.Module, device: str = "cuda"
    ) -> None:
        """Bind to a model.

        Args:
            model:  Trained model to be probed. 待测模型。
            device: Compute device. 计算设备。
        """
        self.model: torch.nn.Module = model
        self.device: str = str(device)

    # ------------------------------------------------------------------
    # Helpers / 辅助方法
    # ------------------------------------------------------------------
    def _get_hidden_states(
        self, sample_inputs: torch.Tensor, layer_idx: int = -1
    ) -> torch.Tensor:
        """Extract per-layer hidden states from the model.

        从模型提取每层隐藏状态。

        Args:
            sample_inputs: Token ids (B, S). 输入 token。
            layer_idx:     Which layer to return. 返回的层下标。

        Returns:
            Tensor of shape (B, S, H). 返回隐状态张量。

        Raises:
            RuntimeError: If the model does not expose hidden states.
        """
        self.model.eval()
        with torch.no_grad():
            out = self.model(
                sample_inputs.to(self.device), output_hidden_states=True
            )
        if out.hidden_states is None:
            raise RuntimeError(
                "Model did not return hidden_states; pass "
                "output_hidden_states=True from its forward()."
            )
        return out.hidden_states[layer_idx]

    # ------------------------------------------------------------------
    # 1. Avalanche-size exponent tau / 雪崩规模指数
    # ------------------------------------------------------------------
    def test_avalanche_exponent(
        self,
        sample_inputs: torch.Tensor,
        n_pairs: int = 200,
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """Estimate the avalanche-size exponent ``tau``.

        估算雪崩规模指数。每次对同一输入做两次随机前向（含 dropout
        与色噪声），收集差值的绝对值作为"雪崩规模"，对其分布做对数分
        箱并拟合幂律斜率。

        Args:
            sample_inputs: Token ids (B, S). 输入 token。
            n_pairs:       Number of forward-pair evaluations.
                           对比前向次数。
            threshold:     Lower cutoff on event sizes. 事件下截断。

        Returns:
            Dict with measured ``tau``, std-error, R-squared, theoretical
            value 1.5, and a boolean ``within`` indicating whether the
            measurement falls in the theoretical band.
            返回测得的 tau、标准误、决定系数、理论值和是否落入理论区间。
        """
        self.model.train()  # enable dropout & noise
        sample_inputs = sample_inputs.to(self.device)
        sizes: list[float] = []
        for _ in range(n_pairs):
            with torch.no_grad():
                a = self.model(sample_inputs).logits
                b = self.model(sample_inputs).logits
            diff = (b - a).abs().flatten().detach().cpu().numpy()
            sizes.extend(diff[diff > threshold].tolist())
        sizes_arr = np.asarray([s for s in sizes if s > 0.0])
        if sizes_arr.size < 200:
            return {"tau": float("nan"), "error": "not enough samples"}

        log_s = np.log10(sizes_arr)
        hist, edges = np.histogram(log_s, bins=40)
        centres = 0.5 * (edges[:-1] + edges[1:])
        mask = hist > 5
        if mask.sum() < 5:
            return {"tau": float("nan"), "error": "not enough bins"}
        slope, _, r, _, se = stats.linregress(
            centres[mask], np.log10(hist[mask] + 1)
        )
        tau = float(-slope)
        return {
            "tau": tau,
            "tau_err": float(se),
            "r_squared": float(r * r),
            "theory": 1.5,
            "within": abs(tau - 1.5) < 0.2,
            "n_events": int(sizes_arr.size),
        }

    # ------------------------------------------------------------------
    # 2. Hurst exponent / Hurst 指数
    # ------------------------------------------------------------------
    def test_hurst_exponent(
        self, sample_inputs: torch.Tensor, layer_idx: int = -1
    ) -> Dict[str, Any]:
        """Estimate the Hurst exponent ``H`` via R/S analysis.

        通过 R/S 分析估算 Hurst 指数。

        Args:
            sample_inputs: Token ids (B, S). 输入 token。
            layer_idx:     Layer from which to read hidden states.
                           读取隐状态的层下标。

        Returns:
            Dict with measured ``hurst``, std across channels, the
            theoretical range and a ``within`` flag.
            返回平均 H、跨通道标准差、理论区间和 within 标志。
        """
        hidden = self._get_hidden_states(sample_inputs, layer_idx)
        sig_all = hidden[0].detach().cpu().numpy()  # (S, H)
        n = sig_all.shape[0]
        if n < 64:
            return {"hurst": float("nan"), "error": "sequence too short"}

        lags = np.unique(
            np.logspace(0.6, np.log10(n // 4), 12).astype(int)
        )
        h_values: list[float] = []
        for d in range(min(sig_all.shape[1], 32)):
            sig = sig_all[:, d]
            rs: list[float] = []
            for lag in lags:
                n_chunks = n // lag
                if n_chunks < 2:
                    continue
                chunks = sig[: n_chunks * lag].reshape(n_chunks, lag)
                centred = chunks - chunks.mean(axis=1, keepdims=True)
                cum = np.cumsum(centred, axis=1)
                r = cum.max(axis=1) - cum.min(axis=1)
                s = chunks.std(axis=1)
                valid = s > 1.0e-8
                if not valid.any():
                    continue
                rs.append(float((r[valid] / s[valid]).mean()))
            if len(rs) < 4:
                continue
            slope, _, _, _, _ = stats.linregress(
                np.log(lags[: len(rs)]), np.log(np.asarray(rs))
            )
            h_values.append(float(slope))

        if not h_values:
            return {"hurst": float("nan"), "error": "no valid channels"}
        hurst = float(np.mean(h_values))
        return {
            "hurst": hurst,
            "hurst_std": float(np.std(h_values)),
            "theory_range": [0.6, 0.8],
            "within": 0.6 <= hurst <= 0.8,
            "n_channels_used": len(h_values),
        }

    # ------------------------------------------------------------------
    # 3. Power-spectrum slope beta / 功率谱斜率
    # ------------------------------------------------------------------
    def test_power_spectrum(
        self, sample_inputs: torch.Tensor, layer_idx: int = -1
    ) -> Dict[str, Any]:
        """Fit ``S(f) ~ f^(-beta)`` on hidden-state time series.

        在隐状态时间序列上拟合功率谱斜率。

        Args:
            sample_inputs: Token ids (B, S). 输入 token。
            layer_idx:     Layer index to probe. 探测的层下标。

        Returns:
            Dict with measured ``beta``, std-error, the theoretical
            range, the kept (freq, psd) pairs (truncated for JSON
            serialisation), and a ``within`` flag.
        """
        hidden = self._get_hidden_states(sample_inputs, layer_idx)
        sig = hidden[0].detach().cpu().numpy()  # (S, H)
        n = sig.shape[0]
        freqs = rfftfreq(n)
        psd = (np.abs(rfft(sig, axis=0)) ** 2).mean(axis=1)
        valid = (freqs > 4.0 / n) & (freqs < 0.4)
        if valid.sum() < 8:
            return {"beta": float("nan"), "error": "not enough frequencies"}
        slope, _, r, _, se = stats.linregress(
            np.log(freqs[valid]), np.log(psd[valid] + 1.0e-12)
        )
        beta = float(-slope)
        return {
            "beta": beta,
            "beta_err": float(se),
            "r_squared": float(r * r),
            "theory_range": [0.7, 1.3],
            "within": 0.7 <= beta <= 1.3,
            "frequencies": freqs[valid].tolist()[:128],
            "psd": psd[valid].tolist()[:128],
        }

    # ------------------------------------------------------------------
    # 4. Parameter efficiency vs. baseline / 参数效率
    # ------------------------------------------------------------------
    @staticmethod
    def _eval_loss(
        model: torch.nn.Module,
        loader: Iterable,
        device: str,
        max_batches: int = 50,
    ) -> float:
        """Compute token-weighted mean cross-entropy.

        计算 token 加权平均的交叉熵。
        """
        model.eval()
        total_loss = 0.0
        total_tokens = 0
        with torch.no_grad():
            for i, batch in enumerate(loader):
                if i >= max_batches:
                    break
                input_ids = batch["input_ids"].to(device)
                labels = batch.get("labels", input_ids).to(device)
                out = model(input_ids=input_ids, labels=labels)
                n = int((labels != -100).sum().item())
                total_loss += float(out.loss.item()) * n
                total_tokens += n
        return total_loss / max(total_tokens, 1)

    def test_parameter_efficiency(
        self,
        baseline_model: torch.nn.Module,
        eval_loader: DataLoader,
    ) -> Dict[str, Any]:
        """Compare CID-style model and the baseline at equal compute.

        在相同评估集上比较 CID 模型与基线模型的参数量和 PPL。

        Args:
            baseline_model: A trained baseline (e.g. ``TinyTransformerLM``).
                             已训练的基线模型。
            eval_loader:     Evaluation dataloader. 验证集 dataloader。

        Returns:
            Dict with parameter counts, perplexities, the parameter
            ratio and a boolean ``within`` flag (True if the UID model
            does *not* underperform the baseline).
        """
        cid_loss = self._eval_loss(self.model, eval_loader, self.device)
        trans_loss = self._eval_loss(
            baseline_model, eval_loader, self.device
        )
        cid_params = int(sum(p.numel() for p in self.model.parameters()))
        trans_params = int(
            sum(p.numel() for p in baseline_model.parameters())
        )
        cid_ppl = float(np.exp(cid_loss))
        trans_ppl = float(np.exp(trans_loss))
        param_ratio = trans_params / cid_params
        return {
            "cid_params": cid_params,
            "trans_params": trans_params,
            "cid_ppl": cid_ppl,
            "trans_ppl": trans_ppl,
            "param_ratio": param_ratio,
            "ppl_ratio_cid_over_trans": cid_ppl / trans_ppl,
            "theory_min": 5.0,
            "theory_target": 10.0,
            "within": (cid_ppl <= trans_ppl) and (param_ratio >= 1.0),
        }

    # ------------------------------------------------------------------
    # Driver / 总入口
    # ------------------------------------------------------------------
    def run_all(
        self,
        sample_inputs: torch.Tensor,
        baseline_model: Optional[torch.nn.Module] = None,
        eval_loader: Optional[DataLoader] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Run all available falsification tests and return their results.

        运行全部可用的可证伪测试，并返回结果字典。

        Args:
            sample_inputs: A small batch (B, S) for the spectral and
                            avalanche tests. 用于谱与雪崩测试的小批次。
            baseline_model: Optional baseline for parameter-efficiency
                             test. 可选的基线模型。
            eval_loader:    Optional dataloader for the efficiency test.
                             可选的验证 dataloader。
        """
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
