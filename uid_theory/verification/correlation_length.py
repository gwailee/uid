# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
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

"""Correlation-length measurement (Theory §11.1 Definition 11.1).

关联长度测量 —— 实现理论文档 §11.1 定义 11.1 的 ξ。

Definition 11.1:
    Let {h_l,c(t)}_{t=1}^T be the hidden-state time series at layer l,
    channel c, of a trained model with noise injection disabled.
    The per-(layer, channel) correlation length is:

        xi_l,c := min { k >= 1 :
                        I(h_l,c(t); h_l,c(t+k)) <= (1/e) * I_self }

    where I is mutual information and I_self = I(h_l,c(t); h_l,c(t)).
    The model-wide xi is the median across all layers and channels.

Notes on the implementation:
    1. We estimate mutual information using k-NN (Kraskov-Stogbauer-
       Grassberger 2004 estimator) by default, which works for
       continuous variables without needing to choose bin widths.
       Histogram-based MI is offered as a fast fallback.

    2. The "self-mutual-information" I_self is, in finite samples,
       not the entropy itself but rather the k-NN MI estimate of a
       variable with itself. We take a stable estimate by computing
       I(h(t); h(t+0)) on the same lag-0 pairs used in the protocol,
       which absorbs estimator bias consistently.

    3. The threshold "<= (1/e) * I_self" is the Theory §11.1.3 (b)
       canonical choice. If you change it via `threshold`, document
       which threshold you used in the result file.

    4. We MUST measure with noise injection disabled (Theory
       §11.1.3 (d)) — otherwise xi reflects the injected noise, not
       the model's intrinsic emergent correlation. This module does
       not toggle the model state on its own; the caller is
       responsible for setting `model.set_noise_injection(False)`
       before collecting the hidden states.

    5. Sequence length T must be substantially larger than the
       expected xi for the estimate to be reliable. The result
       structure carries a `seq_len_too_short` flag when the search
       returns the upper bound (xi == k_max), warning that the true
       xi may be larger than the search range.

测量 ξ 的实现要点：
    1. 默认用 Kraskov-Stogbauer-Grassberger (KSG) k-NN 估计互信息，
       连续变量无需选择 bin 宽度；提供直方图法作为快速 fallback。
    2. "自互信息" I_self 在有限样本下不是熵本身；我们用 lag=0 配对
       上 KSG 估计，让估计偏差对称化。
    3. 阈值 "≤ (1/e) · I_self" 是论文 §11.1.3(b) 的规范选择；
       使用其他阈值时请在结果文件中记录。
    4. 测量必须在噪声注入关闭的状态下进行（论文 §11.1.3(d)）；
       本模块不主动切换模型状态，调用方需要先调
       model.set_noise_injection(False)。
    5. 序列长度 T 必须远大于预期 ξ；当搜索返回上界（ξ == k_max）
       时，结果结构会标记 seq_len_too_short 警告。
"""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import cKDTree
from scipy.special import digamma


# ======================================================================
# Result dataclass
# ======================================================================


@dataclass
class CorrelationLengthResult:
    """Container for one model-wide correlation-length measurement.

    模型整体关联长度测量的结果容器。

    Fields:
        xi_median:           Model-wide xi := median across (layer, channel).
        xi_mean:             Mean across (layer, channel) — informational.
        xi_std:              Std across (layer, channel) — informational.
        xi_per_layer:        Median xi per layer (length n_layers).
        xi_per_channel:      Flat list of per-(layer, channel) xi values.
        n_layers:            Number of layers measured.
        n_channels_per_layer:Number of channels sampled per layer.
        seq_len:             Length of the time series used.
        threshold:           Threshold used (default 1/e ≈ 0.3679).
        mi_estimator:        "ksg" or "histogram".
        ksg_k:               k of KSG estimator (only when ksg).
        seq_len_too_short:   True iff at least one (layer, channel) hit
                             the search upper bound k_max, meaning the
                             true xi may exceed seq_len // 4 and the
                             reported xi underestimates the truth.
        n_clipped:           Number of (layer, channel) pairs that hit
                             the search upper bound.
        notes:               Free-text diagnostic notes.
    """

    xi_median: float
    xi_mean: float
    xi_std: float
    xi_per_layer: List[float]
    xi_per_channel: List[float]
    n_layers: int
    n_channels_per_layer: int
    seq_len: int
    threshold: float
    mi_estimator: str
    ksg_k: int
    seq_len_too_short: bool
    n_clipped: int
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ======================================================================
# Mutual information estimators
# ======================================================================


def _mi_ksg(
    x: np.ndarray, y: np.ndarray, k: int = 4,
) -> float:
    """Kraskov-Stogbauer-Grassberger mutual information estimator.

    Reference:
        Kraskov, A., Stogbauer, H., & Grassberger, P. (2004).
        "Estimating mutual information." Phys. Rev. E 69, 066138.

    Args:
        x: Array of shape (N,) — one time series.
        y: Array of shape (N,) — one time series.
        k: Number of nearest neighbours; typical value 3-6.

    Returns:
        Estimated mutual information in nats. Can be slightly negative
        in finite samples; the caller should clip at 0 if needed.
    """
    n = len(x)
    if n != len(y):
        raise ValueError(
            f"x and y must have the same length, got {len(x)} vs {len(y)}"
        )
    if n < k + 2:
        return 0.0

    # Add a tiny independent jitter to break ties (KSG requires unique
    # distances). Std of jitter is small relative to data std.
    rng = np.random.default_rng(0)
    sx = max(float(x.std()), 1e-12)
    sy = max(float(y.std()), 1e-12)
    x_j = x + rng.normal(0.0, 1e-10 * sx, size=n)
    y_j = y + rng.normal(0.0, 1e-10 * sy, size=n)

    # Joint space distance to k-th neighbour, using Chebyshev
    # (max-norm) metric per the original KSG paper.
    xy = np.column_stack([x_j, y_j])
    tree = cKDTree(xy)
    # Self-match returned at k=0; we want the k-th neighbour
    # excluding self, hence query k+1 and take the last.
    dists, _ = tree.query(xy, k=k + 1, p=np.inf)
    eps = dists[:, -1]  # distance to k-th neighbour

    # Count neighbours strictly within eps in marginal x and y.
    tx = cKDTree(x_j[:, None])
    ty = cKDTree(y_j[:, None])
    nx = np.array(
        [len(tx.query_ball_point([xv], r=ev, p=np.inf)) - 1
         for xv, ev in zip(x_j, eps)]
    )
    ny = np.array(
        [len(ty.query_ball_point([yv], r=ev, p=np.inf)) - 1
         for yv, ev in zip(y_j, eps)]
    )
    # Avoid log(0).
    nx = np.maximum(nx, 1)
    ny = np.maximum(ny, 1)

    mi = (
        digamma(k)
        + digamma(n)
        - np.mean(digamma(nx + 1) + digamma(ny + 1))
    )
    return float(mi)


def _mi_histogram(
    x: np.ndarray, y: np.ndarray, n_bins: int = 16,
) -> float:
    """Plug-in histogram MI estimator (fast fallback).

    用直方图估计互信息（快速回退方案）。

    Args:
        x: Array of shape (N,).
        y: Array of shape (N,).
        n_bins: Number of bins per axis.

    Returns:
        MI in nats; clipped at 0.
    """
    if len(x) != len(y):
        raise ValueError(
            f"x and y must have the same length, got {len(x)} vs {len(y)}"
        )
    n = len(x)
    if n < n_bins * n_bins:
        return 0.0
    # Equal-quantile bins for robustness against heavy tails.
    x_edges = np.quantile(x, np.linspace(0, 1, n_bins + 1))
    y_edges = np.quantile(y, np.linspace(0, 1, n_bins + 1))
    # Add tiny jitter to right edge to make digitize half-open intervals
    # cover the maximum value.
    x_edges[-1] += 1e-12 * (abs(x_edges[-1]) + 1.0)
    y_edges[-1] += 1e-12 * (abs(y_edges[-1]) + 1.0)
    h_xy, _, _ = np.histogram2d(x, y, bins=[x_edges, y_edges])
    p_xy = h_xy / max(h_xy.sum(), 1.0)
    p_x = p_xy.sum(axis=1, keepdims=True)
    p_y = p_xy.sum(axis=0, keepdims=True)
    # Avoid log(0).
    with np.errstate(divide="ignore", invalid="ignore"):
        log_term = np.where(
            p_xy > 0,
            np.log(p_xy / (p_x * p_y + 1e-30) + 1e-30),
            0.0,
        )
    mi = float(np.sum(p_xy * log_term))
    return max(mi, 0.0)


# ======================================================================
# Per-channel xi search
# ======================================================================


def _xi_for_channel(
    signal: np.ndarray,
    threshold_fraction: float,
    mi_estimator: str,
    ksg_k: int,
    n_bins: int,
    k_max: int,
) -> Tuple[int, bool]:
    """Find xi for a single 1-D time series.

    在单条 1-D 时间序列上搜索 ξ。

    Returns:
        (xi, was_clipped) where was_clipped = True iff xi == k_max
        (i.e. the search did not find a lag at which MI dropped below
        the threshold within the search range).
    """
    n = len(signal)
    if n < 8:
        return (1, True)
    # Lag-0 self-MI as the reference.
    if mi_estimator == "ksg":
        mi_ref = _mi_ksg(signal, signal, k=ksg_k)
    else:
        mi_ref = _mi_histogram(signal, signal, n_bins=n_bins)
    if mi_ref <= 0:
        # Pathological case (constant signal); declare xi = 1 to avoid
        # blowing up downstream.
        return (1, False)
    target = threshold_fraction * mi_ref

    # Search lag k = 1, 2, ..., k_max for the first lag whose MI
    # falls below `target`.
    upper = min(k_max, n // 4)
    for k in range(1, upper + 1):
        if mi_estimator == "ksg":
            mi_k = _mi_ksg(signal[:-k], signal[k:], k=ksg_k)
        else:
            mi_k = _mi_histogram(signal[:-k], signal[k:], n_bins=n_bins)
        if mi_k <= target:
            return (k, False)
    return (upper, True)


# ======================================================================
# Public API
# ======================================================================


def measure_correlation_length(
    hidden_states: Sequence[np.ndarray],
    *,
    n_channels_per_layer: int = 16,
    threshold: Optional[float] = None,
    mi_estimator: str = "ksg",
    ksg_k: int = 4,
    n_bins: int = 16,
    k_max: Optional[int] = None,
    seed: int = 0,
) -> CorrelationLengthResult:
    """Measure the model-wide correlation length per Theory §11.1
    Definition 11.1.

    按论文 §11.1 定义 11.1 测量模型整体关联长度 ξ。

    Args:
        hidden_states: Sequence of arrays, one per layer. Each array
            must have shape ``(seq_len, hidden_dim)``. The caller is
            responsible for collecting these from a SINGLE input
            sequence with noise injection DISABLED. For batched
            collection, see `aggregate_correlation_length` below.
            隐状态序列的列表（每层一项）；调用方负责在噪声注入关闭
            状态下采集。
        n_channels_per_layer: Number of channels to sample per layer.
            Per-layer xi is the median across these.
            每层采样的通道数。
        threshold: Threshold fraction. The default ``None`` means
            ``1/e`` (Theory §11.1.3 (b) canonical choice).
            阈值；默认 None 即 1/e。
        mi_estimator: "ksg" (default; recommended) or "histogram"
            (fast fallback).
        ksg_k: k for the KSG estimator (only when mi_estimator="ksg").
        n_bins: Number of bins for the histogram estimator (only
            when mi_estimator="histogram").
        k_max: Upper bound on the lag search. Defaults to seq_len // 4.
            搜索上限；默认 seq_len/4。
        seed: RNG seed for channel sampling.

    Returns:
        :class:`CorrelationLengthResult` with the model-wide median xi
        and full per-(layer, channel) breakdown.

    Raises:
        ValueError: If hidden_states is empty, or any layer has the
            wrong shape, or hyper-parameters are out of range.

    Example:
        >>> # Collect hidden states with noise OFF
        >>> model.set_noise_injection(False)
        >>> model.eval()
        >>> hidden_per_layer = []
        >>> with torch.no_grad():
        ...     out = model(input_ids, output_hidden_states=True)
        >>> for h in out.hidden_states:
        ...     hidden_per_layer.append(h[0].cpu().numpy())   # B=1
        >>> result = measure_correlation_length(hidden_per_layer)
        >>> print(f"Model xi = {result.xi_median:.1f}")
    """
    # ----- Argument validation ----------------------------------------
    if not isinstance(hidden_states, (list, tuple)):
        raise ValueError(
            f"hidden_states must be a list/tuple of (S, H) arrays; "
            f"got {type(hidden_states).__name__}"
        )
    if len(hidden_states) == 0:
        raise ValueError("hidden_states is empty")
    if mi_estimator not in {"ksg", "histogram"}:
        raise ValueError(
            f"mi_estimator must be 'ksg' or 'histogram', got "
            f"{mi_estimator!r}"
        )
    if n_channels_per_layer <= 0:
        raise ValueError(
            f"n_channels_per_layer must be positive, got "
            f"{n_channels_per_layer}"
        )
    if ksg_k < 1:
        raise ValueError(f"ksg_k must be >= 1, got {ksg_k}")
    if n_bins < 4:
        raise ValueError(f"n_bins must be >= 4, got {n_bins}")
    if threshold is not None:
        if not (0.0 < threshold < 1.0):
            raise ValueError(
                f"threshold must be in (0, 1), got {threshold}"
            )
    threshold_value = float(1.0 / math.e) if threshold is None else float(threshold)

    # Validate per-layer shapes.
    seq_lens = []
    hidden_dims = []
    for i, h in enumerate(hidden_states):
        h_arr = np.asarray(h)
        if h_arr.ndim != 2:
            raise ValueError(
                f"Layer {i}: expected 2-D array (S, H); got shape "
                f"{h_arr.shape}"
            )
        seq_lens.append(int(h_arr.shape[0]))
        hidden_dims.append(int(h_arr.shape[1]))
    if len(set(seq_lens)) > 1:
        raise ValueError(
            f"All layers must have the same seq_len; got {seq_lens}"
        )
    seq_len = seq_lens[0]
    if seq_len < 16:
        raise ValueError(
            f"seq_len must be >= 16 to estimate xi; got {seq_len}"
        )

    if k_max is None:
        k_max = seq_len // 4
    if k_max < 2:
        raise ValueError(f"k_max must be >= 2; got {k_max}")

    rng = np.random.default_rng(seed)
    notes: List[str] = []

    # ----- Per-(layer, channel) xi search -----------------------------
    xi_per_channel: List[float] = []
    xi_per_layer_list: List[float] = []
    n_clipped = 0
    for layer_idx, h in enumerate(hidden_states):
        h_arr = np.asarray(h, dtype=np.float64)
        H = h_arr.shape[1]
        n_take = min(int(n_channels_per_layer), H)
        # Stratified random sampling by stride to cover the channel
        # axis evenly.
        channel_indices = rng.choice(H, size=n_take, replace=False)
        layer_xis: List[float] = []
        for c in channel_indices:
            sig = h_arr[:, int(c)]
            xi_c, was_clipped = _xi_for_channel(
                sig,
                threshold_fraction=threshold_value,
                mi_estimator=mi_estimator,
                ksg_k=ksg_k,
                n_bins=n_bins,
                k_max=int(k_max),
            )
            xi_per_channel.append(float(xi_c))
            layer_xis.append(float(xi_c))
            if was_clipped:
                n_clipped += 1
        if layer_xis:
            xi_per_layer_list.append(float(np.median(layer_xis)))
        else:
            xi_per_layer_list.append(float("nan"))

    if not xi_per_channel:
        raise RuntimeError(
            "No (layer, channel) pairs were measured; check that "
            "every layer has at least one channel"
        )

    arr = np.asarray(xi_per_channel, dtype=np.float64)
    xi_median = float(np.median(arr))
    xi_mean = float(np.mean(arr))
    xi_std = float(np.std(arr))

    seq_len_too_short = bool(n_clipped > 0)
    if seq_len_too_short:
        notes.append(
            f"WARN: {n_clipped}/{len(arr)} (layer,channel) pairs hit "
            f"the search upper bound k_max={k_max}; the true xi may "
            f"exceed this bound. Re-measure with longer sequences "
            f"(seq_len >> reported xi_median)."
        )

    return CorrelationLengthResult(
        xi_median=xi_median,
        xi_mean=xi_mean,
        xi_std=xi_std,
        xi_per_layer=xi_per_layer_list,
        xi_per_channel=[float(x) for x in xi_per_channel],
        n_layers=len(hidden_states),
        n_channels_per_layer=int(n_channels_per_layer),
        seq_len=int(seq_len),
        threshold=threshold_value,
        mi_estimator=mi_estimator,
        ksg_k=int(ksg_k),
        seq_len_too_short=seq_len_too_short,
        n_clipped=int(n_clipped),
        notes=notes,
    )


# ======================================================================
# Aggregation across multiple sequences
# ======================================================================


def aggregate_correlation_length(
    per_sequence_results: Sequence[CorrelationLengthResult],
) -> CorrelationLengthResult:
    """Aggregate xi measurements from multiple input sequences.

    在多条输入序列的 ξ 测量结果上做聚合，给出一个稳健的整体 ξ。

    Returns a synthetic CorrelationLengthResult whose `xi_median` is
    the median of per-sequence medians (the standard meta-analysis
    approach for a quantity that is itself defined as a median).
    """
    if not per_sequence_results:
        raise ValueError("per_sequence_results is empty")
    medians = [r.xi_median for r in per_sequence_results]
    means = [r.xi_mean for r in per_sequence_results]
    flat_per_channel: List[float] = []
    for r in per_sequence_results:
        flat_per_channel.extend(r.xi_per_channel)
    n_clipped = sum(r.n_clipped for r in per_sequence_results)
    seq_len_too_short = any(r.seq_len_too_short for r in per_sequence_results)

    # Use the configuration of the first result (they should all match).
    base = per_sequence_results[0]
    notes = list(base.notes)
    if any(
        r.threshold != base.threshold or r.mi_estimator != base.mi_estimator
        for r in per_sequence_results
    ):
        notes.append(
            "WARN: per-sequence results used different threshold or "
            "estimator; aggregation may mix estimators."
        )

    return CorrelationLengthResult(
        xi_median=float(np.median(medians)),
        xi_mean=float(np.mean(means)),
        xi_std=float(np.std(means)),
        xi_per_layer=base.xi_per_layer,  # representative
        xi_per_channel=flat_per_channel,
        n_layers=base.n_layers,
        n_channels_per_layer=base.n_channels_per_layer,
        seq_len=base.seq_len,
        threshold=base.threshold,
        mi_estimator=base.mi_estimator,
        ksg_k=base.ksg_k,
        seq_len_too_short=seq_len_too_short,
        n_clipped=n_clipped,
        notes=notes,
    )
