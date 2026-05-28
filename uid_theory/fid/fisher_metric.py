# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
#   * Promote the "this is NOT the true Fisher matrix" warning to the
#     top of the docstring (was buried).
#   * compute(): accept an optional jitter override and verify seq_len
#     constraints; emit a one-time RuntimeWarning when seq_len < H
#     (rank-deficient covariance estimate).
#   * Add classmethod compute_true_fisher_diagonal(model, batch) for
#     calibration: O(M) diagonal Fisher computed via the standard
#     backprop trick. Useful as a sanity check against the empirical-
#     covariance surrogate.
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

"""Fisher information metric on hidden-state manifolds.

隐状态流形上的 Fisher 信息度量估算。

================================================================
IMPORTANT WARNING — read before using this module for any claim
================================================================
This implementation is a HIDDEN-STATE EMPIRICAL-COVARIANCE SURROGATE
of the Fisher information matrix. It is NOT the exact parameter-space
Fisher matrix that appears in Theory §2.2 of the paper.

  * The exact Fisher matrix is M x M (where M = parameter count) and
    is defined as  E_x[ ∂_i log p(x|θ) ∂_j log p(x|θ) ].
    Computing it densely is O(M^2) memory and infeasible for large
    networks.

  * What this class returns is an H x H *covariance* of hidden-state
    activations (averaged over the sequence axis). It is cheap and
    captures geometric anisotropy of representations.

  * The two objects differ both in dimensionality (H vs M) and in
    semantic (representation geometry vs parameter geometry).
    Quantitative agreement with Theory §6.1 prediction (eta > 0.5) is
    *qualitative* under this surrogate.

For calibration, this module also provides
``compute_true_fisher_diagonal(model, batch)``: an O(M) diagonal
Fisher estimator via the standard backprop trick that you can use as
a sanity check on a small number of samples.
================================================================

严格的 Fisher 信息矩阵需对模型参数求对数似然的二阶外积，O(M^2)
开销巨大。本实现采用**隐状态经验协方差**作为代理，便宜、本地、足够用于
FID 诊断；但**它不是参数空间的严格 Fisher 矩阵**。请勿据此宣称论文 §2.2
意义上的"Fisher 矩阵已实现"。
"""

from __future__ import annotations

import warnings
from typing import Iterable, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


# Module-level guard so we warn about rank-deficient covariance
# at most once per process.
_RANK_DEFICIENT_WARNED: set = set()


class FisherMetric(nn.Module):
    """Empirical-covariance surrogate of the Fisher metric.

    Fisher 度量的经验协方差代理。

    .. warning::
       This is NOT the true Fisher matrix on parameter space. See the
       module docstring for the precise scope and limitations.
    """

    MIN_SEQ_LEN: int = 2  # below this, covariance is undefined

    def __init__(self, hidden_size: int, jitter: float = 1.0e-4) -> None:
        """Initialise the probe.

        Args:
            hidden_size: Feature dimension. 隐藏维度。
            jitter:      Default diagonal regularisation for compute().
                          对角抖动默认值。
        """
        super().__init__()
        if hidden_size <= 0:
            raise ValueError(
                f"hidden_size must be positive, got {hidden_size}"
            )
        if jitter < 0.0:
            raise ValueError(f"jitter must be non-negative, got {jitter}")
        self.hidden_size: int = int(hidden_size)
        self.jitter: float = float(jitter)

    # ------------------------------------------------------------------
    # Empirical surrogate (cheap, batch-local)
    # ------------------------------------------------------------------

    def compute(
        self,
        hidden_states: torch.Tensor,
        jitter: Optional[float] = None,
    ) -> torch.Tensor:
        """Return a (B, H, H) PSD matrix per sample.

        Args:
            hidden_states: Tensor of shape (B, S, H). 隐状态张量。
            jitter:        Override the default jitter. Pass 0.0 to get
                           the raw covariance (may be rank-deficient).

        Returns:
            Symmetric PSD metric tensor of shape (B, H, H).
        """
        if hidden_states.dim() != 3:
            raise ValueError(
                "hidden_states must have shape (B, S, H), got "
                f"{tuple(hidden_states.shape)}"
            )
        b, s, h = hidden_states.shape
        if h != self.hidden_size:
            raise ValueError(
                f"channel dim mismatch: expected {self.hidden_size}, "
                f"got {h}"
            )
        if s < self.MIN_SEQ_LEN:
            raise ValueError(
                f"seq_len must be >= {self.MIN_SEQ_LEN} to estimate "
                f"covariance, got {s}. With seq_len=1 the covariance "
                "is identically zero and any downstream anisotropy "
                "metric will be meaningless."
            )
        if s < h:
            # Rank-deficient estimate: sample covariance has rank
            # at most s, but we are reporting an (h, h) matrix.
            # Warn exactly once per (hidden_size, seq_len) pair.
            warn_key = (self.hidden_size, int(s))
            if warn_key not in _RANK_DEFICIENT_WARNED:
                _RANK_DEFICIENT_WARNED.add(warn_key)
                warnings.warn(
                    f"FisherMetric.compute: seq_len={s} < hidden_size="
                    f"{h}, so the empirical covariance is rank-deficient "
                    "(rank <= seq_len). Downstream eta / Ricci surrogates "
                    "will be biased towards 1.0 / NaN respectively. "
                    "Use seq_len >= hidden_size for reliable estimates.",
                    RuntimeWarning,
                )

        centred = hidden_states - hidden_states.mean(dim=1, keepdim=True)
        cov = torch.einsum("bsi,bsj->bij", centred, centred) / max(s, 1)
        j = self.jitter if jitter is None else float(jitter)
        if j < 0.0:
            raise ValueError(f"jitter must be non-negative, got {j}")
        if j == 0.0:
            return cov
        eye = torch.eye(h, device=cov.device, dtype=cov.dtype)
        return cov + j * eye[None]

    # ------------------------------------------------------------------
    # Calibration: true diagonal Fisher (parameter space)
    # ------------------------------------------------------------------

    @classmethod
    def compute_true_fisher_diagonal(
        cls,
        model: nn.Module,
        batch_input_ids: torch.Tensor,
        param_filter: Optional[Iterable[str]] = None,
    ) -> torch.Tensor:
        """Compute the diagonal of the true (parameter-space) Fisher.

        计算参数空间真 Fisher 矩阵的对角元，作为代理质量的校准量。

        For a language model returning logits L of shape (B, S, V),
        the diagonal Fisher of parameter ``theta_i`` is
            F_ii = E_{x, y~p(y|x;theta)}[ (∂ log p(y|x;theta) / ∂ theta_i)^2 ]

        We approximate the inner expectation over y by sampling one
        ``y`` per token from the model's own predictive distribution
        (the standard "empirical Fisher" approximation — exact under
        well-calibrated models).

        Cost: O(M) memory, one extra forward + backward per sample.

        Args:
            model:           Model with forward(input_ids) -> .logits.
            batch_input_ids: (B, S) integer token ids.
            param_filter:    Optional iterable of parameter-name
                             substrings; if given, only parameters whose
                             name contains at least one substring are
                             included.

        Returns:
            1-D tensor of length sum(p.numel() for matching p),
            ordered to match model.named_parameters() iteration order.
        """
        model.eval()
        out = model(batch_input_ids)
        logits = out.logits  # (B, S, V)

        # Sample one y per token from p(y|x;theta).
        probs = F.softmax(logits, dim=-1)
        y = torch.distributions.Categorical(probs=probs).sample()  # (B, S)

        log_probs = F.log_softmax(logits, dim=-1)
        # Gather log p(y) per token, then sum (cross-token).
        chosen_log_prob = log_probs.gather(
            -1, y.unsqueeze(-1),
        ).squeeze(-1)  # (B, S)
        scalar_log_lik = chosen_log_prob.sum()

        # Backprop and collect squared grads for the requested params.
        diag_pieces = []
        # We do NOT zero_grad in case the caller already has accumulated
        # grads; we read .grad directly via autograd.grad.
        named_params = list(model.named_parameters())
        if param_filter is not None:
            keys = list(param_filter)
            named_params = [
                (n, p) for (n, p) in named_params
                if any(k in n for k in keys)
            ]
        params = [p for (_, p) in named_params if p.requires_grad]
        if not params:
            return torch.empty(0)

        grads = torch.autograd.grad(
            scalar_log_lik, params,
            retain_graph=False, create_graph=False,
            allow_unused=True,
        )
        for g in grads:
            if g is None:
                # Parameter did not participate in the forward pass.
                continue
            diag_pieces.append(g.detach().pow(2).flatten())
        if not diag_pieces:
            return torch.empty(0)
        return torch.cat(diag_pieces)
