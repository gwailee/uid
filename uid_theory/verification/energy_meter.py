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

"""GPU inference energy meter (v2.1).

GPU 推理能耗实测工具（v2.1）。

This module replaces v0.1's Landauer-limit theoretical arithmetic with
actual hardware power measurements. The design follows six principles
identified during the v2.1 review:

  1. Sample power at high frequency (default 25 Hz) via ``pynvml``,
     with a transparent fallback to a background ``nvidia-smi`` poller
     when ``pynvml`` is not importable.
  2. Strict timing: each measurement window is delimited by explicit
     ``torch.cuda.synchronize()`` calls and timed with
     ``time.perf_counter_ns()`` so wall-clock and GPU work line up.
  3. Idle baseline: a separate "idle power" measurement is taken just
     before the workload, with the model already loaded onto the GPU
     but no forward running. ``power_above_idle_watts`` is reported in
     addition to raw average power.
  4. Workload disambiguation: we expose ``mode='prefill'`` (one full
     forward per sample of shape (B, S, V), useful for training-style
     comparisons) and ``mode='decode'`` (token-by-token greedy decode
     with KV cache off, useful for autoregressive inference cost).
  5. Hard failure on CPU / missing GPU drivers: refuses to silently
     return fictional numbers when there is no GPU to measure.
  6. The public ``measure_inference_energy(...)`` signature is
     deliberately backwards-compatible with the v2.0 caller in
     ``experiments/run_energy_benchmark.py``.

设计原则：用 pynvml 高频采样替换 v0.1 的 Landauer 理论推算；
严格 torch.cuda.synchronize() + perf_counter_ns 计时；
独立测量并报告 idle 基线；区分 prefill / decode 两种工况；
CPU 平台直接拒绝运行而不是返回伪造数据。
"""

from __future__ import annotations

import dataclasses
import math
import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

import torch
import torch.nn as nn


# ======================================================================
# Result dataclass
# ======================================================================


@dataclass
class EnergyMeasurement:
    """Container for one energy measurement run.

    单次能耗测量的结构化结果。

    Fields:
        model_name:                Caller-supplied name for logging.
        mode:                      "prefill" or "decode".
        device:                    e.g. "cuda" or "cuda:0".
        gpu_name:                  Human-readable GPU name (NVML query).
        sampler:                   "pynvml" or "nvidia_smi".
        sample_rate_hz:            Actual achieved sampling rate.
        n_samples:                 Number of power samples taken.
        n_warmup:                  Forward passes before measurement.
        n_measure:                 Forward passes during measurement.
        batch_size:                Batch size of one forward.
        seq_len:                   Sequence length of one forward.
        total_tokens:              Tokens processed across all measure
                                   iterations (B * S * n_measure in
                                   prefill mode; B * new_tokens *
                                   n_measure in decode mode).
        new_tokens_per_decode:     For decode mode: number of generated
                                   tokens per measure iteration; 0 in
                                   prefill mode.
        wall_clock_seconds:        Wall-clock duration of the measure
                                   window (sync'd).
        idle_power_watts:          Average idle power (no forward).
        idle_window_seconds:       Duration of the idle sampling window.
        avg_power_watts:           Mean instantaneous power during work.
        max_power_watts:           Peak instantaneous power during work.
        power_above_idle_watts:    avg_power_watts - idle_power_watts.
        total_energy_joules:       Integrated power x time during work.
        energy_above_idle_joules:  Integrated (power - idle) x time.
        energy_per_token_joules:   total_energy_joules / total_tokens.
        energy_per_token_above_idle_joules:
                                   energy_above_idle / total_tokens.
        notes:                     Free-text diagnostic notes.

    Both raw and "above-idle" numbers are reported so the caller can
    decide which one to use in cross-model comparisons. For small
    models the idle floor often dominates, in which case the "above
    idle" numbers are the honest ones.
    """

    model_name: str
    mode: str
    device: str
    gpu_name: str
    sampler: str
    sample_rate_hz: float
    n_samples: int
    n_warmup: int
    n_measure: int
    batch_size: int
    seq_len: int
    total_tokens: int
    new_tokens_per_decode: int
    wall_clock_seconds: float
    idle_power_watts: float
    idle_window_seconds: float
    avg_power_watts: float
    max_power_watts: float
    power_above_idle_watts: float
    total_energy_joules: float
    energy_above_idle_joules: float
    energy_per_token_joules: float
    energy_per_token_above_idle_joules: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ======================================================================
# Power-sampling backends
# ======================================================================


class _PowerSampler:
    """Background power sampler shared base class.

    后台功率采样器基类。

    Subclasses implement ``_read_power_watts()`` to return one
    instantaneous reading (watts). The base class drives the sampling
    loop in a background thread.
    """

    def __init__(
        self,
        device_index: int,
        sample_rate_hz: float = 25.0,
    ) -> None:
        if sample_rate_hz <= 0.0:
            raise ValueError(
                f"sample_rate_hz must be positive, got {sample_rate_hz}"
            )
        self.device_index: int = int(device_index)
        self.sample_rate_hz: float = float(sample_rate_hz)
        self._period_s: float = 1.0 / float(sample_rate_hz)
        self._thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        # Use a lock so the consumer thread (start/stop) cannot race
        # the producer thread (sampling loop) on the buffers.
        self._lock: threading.Lock = threading.Lock()
        self._timestamps_ns: List[int] = []
        self._powers_w: List[float] = []

    # ----- subclass hooks --------------------------------------------

    def _read_power_watts(self) -> float:
        raise NotImplementedError

    def _open(self) -> None:
        """Optional: per-thread resource initialisation."""

    def _close(self) -> None:
        """Optional: per-thread resource teardown."""

    @property
    def name(self) -> str:
        raise NotImplementedError

    # ----- lifecycle --------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Sampler already started")
        self._stop_event.clear()
        with self._lock:
            self._timestamps_ns.clear()
            self._powers_w.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"{self.name}-sampler", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        try:
            self._open()
            while not self._stop_event.is_set():
                t0 = time.perf_counter_ns()
                try:
                    p = float(self._read_power_watts())
                except Exception:  # pragma: no cover - hardware races
                    # If a single reading fails, skip it rather than
                    # crashing the whole measurement.
                    p = float("nan")
                if math.isfinite(p):
                    with self._lock:
                        self._timestamps_ns.append(t0)
                        self._powers_w.append(p)
                # Sleep the remainder of the period (clamped at 0).
                elapsed_s = (time.perf_counter_ns() - t0) / 1.0e9
                sleep_s = self._period_s - elapsed_s
                if sleep_s > 0:
                    time.sleep(sleep_s)
        finally:
            self._close()

    # ----- snapshot ---------------------------------------------------

    def snapshot(self) -> tuple[List[int], List[float]]:
        """Return a (timestamps_ns, powers_w) snapshot of all samples."""
        with self._lock:
            return list(self._timestamps_ns), list(self._powers_w)


class _PyNvmlSampler(_PowerSampler):
    """High-rate sampler backed by pynvml (NVML)."""

    def __init__(
        self, device_index: int, sample_rate_hz: float = 25.0,
    ) -> None:
        super().__init__(device_index, sample_rate_hz)
        # Import lazily so that this module can be imported even when
        # pynvml is not installed.
        try:
            import pynvml  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "pynvml is not available; cannot use the NVML sampler"
            ) from exc
        self._pynvml = pynvml
        # Init NVML on the main thread for the gpu_name lookup; we will
        # also call init in _open() inside the worker thread (NVML is
        # process-global so the second init is a no-op).
        self._pynvml.nvmlInit()
        self._handle = self._pynvml.nvmlDeviceGetHandleByIndex(
            self.device_index
        )

    def _open(self) -> None:
        # NVML is process-global; calling init twice is harmless.
        self._pynvml.nvmlInit()
        self._handle = self._pynvml.nvmlDeviceGetHandleByIndex(
            self.device_index
        )

    def _close(self) -> None:
        # NVML shutdown is process-global; we let the OS clean up
        # rather than risking other concurrent users.
        pass

    def _read_power_watts(self) -> float:
        # nvmlDeviceGetPowerUsage returns mW.
        mw = self._pynvml.nvmlDeviceGetPowerUsage(self._handle)
        return mw / 1000.0

    def gpu_name(self) -> str:
        raw = self._pynvml.nvmlDeviceGetName(self._handle)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    @property
    def name(self) -> str:
        return "pynvml"


class _NvidiaSmiSampler(_PowerSampler):
    """Fallback sampler that shells out to ``nvidia-smi`` per tick.

    This is significantly slower than pynvml (one process per sample)
    so we cap the rate at 10 Hz.
    """

    MAX_HZ_FALLBACK: float = 10.0

    def __init__(
        self, device_index: int, sample_rate_hz: float = 10.0,
    ) -> None:
        rate = float(min(sample_rate_hz, self.MAX_HZ_FALLBACK))
        super().__init__(device_index, rate)
        if shutil.which("nvidia-smi") is None:
            raise RuntimeError(
                "nvidia-smi not found in PATH; cannot use the "
                "subprocess fallback sampler."
            )

    def _read_power_watts(self) -> float:
        cmd = [
            "nvidia-smi",
            f"--id={self.device_index}",
            "--query-gpu=power.draw",
            "--format=csv,noheader,nounits",
        ]
        # 1s timeout is generous for a single nvidia-smi query.
        out = subprocess.check_output(
            cmd, timeout=1.0, stderr=subprocess.DEVNULL,
        )
        return float(out.decode("utf-8").strip())

    def gpu_name(self) -> str:
        try:
            cmd = [
                "nvidia-smi",
                f"--id={self.device_index}",
                "--query-gpu=name",
                "--format=csv,noheader",
            ]
            out = subprocess.check_output(
                cmd, timeout=1.0, stderr=subprocess.DEVNULL,
            )
            return out.decode("utf-8").strip()
        except Exception:
            return "unknown-gpu"

    @property
    def name(self) -> str:
        return "nvidia_smi"


def _build_sampler(
    device_index: int,
    requested_rate_hz: float,
    prefer: str = "auto",
) -> _PowerSampler:
    """Build the highest-fidelity sampler available.

    Args:
        device_index:      GPU index.
        requested_rate_hz: Desired sampling rate (Hz).
        prefer:            "auto"   -> pynvml if importable else
                                       nvidia-smi.
                           "pynvml" -> force pynvml (raise if missing).
                           "nvidia_smi" -> force the fallback.

    Returns:
        An instantiated, unstarted sampler.
    """
    prefer = prefer.lower()
    if prefer not in {"auto", "pynvml", "nvidia_smi"}:
        raise ValueError(
            f"prefer must be one of 'auto'/'pynvml'/'nvidia_smi', "
            f"got {prefer!r}"
        )

    if prefer == "nvidia_smi":
        return _NvidiaSmiSampler(device_index, requested_rate_hz)

    if prefer in ("auto", "pynvml"):
        try:
            return _PyNvmlSampler(device_index, requested_rate_hz)
        except RuntimeError:
            if prefer == "pynvml":
                raise
            # Fall through to nvidia-smi fallback.
    return _NvidiaSmiSampler(device_index, requested_rate_hz)


# ======================================================================
# Energy integration helpers
# ======================================================================


def _trapezoid_energy_j(
    timestamps_ns: List[int],
    powers_w: List[float],
) -> float:
    """Trapezoidal integration of power samples over time.

    用梯形法将 (timestamps_ns, powers_w) 积分得到焦耳能量。

    Args:
        timestamps_ns: Monotonically increasing sample times in
                       nanoseconds.
        powers_w:      Power readings in watts at each timestamp.

    Returns:
        Energy in joules. Returns 0.0 if fewer than 2 samples.
    """
    n = len(timestamps_ns)
    if n != len(powers_w):
        raise ValueError(
            "timestamps_ns and powers_w must have the same length"
        )
    if n < 2:
        return 0.0
    energy = 0.0
    for i in range(1, n):
        dt_s = (timestamps_ns[i] - timestamps_ns[i - 1]) / 1.0e9
        if dt_s <= 0.0:
            continue
        energy += 0.5 * (powers_w[i] + powers_w[i - 1]) * dt_s
    return float(energy)


def _filter_window(
    timestamps_ns: List[int],
    powers_w: List[float],
    start_ns: int,
    end_ns: int,
) -> tuple[List[int], List[float]]:
    """Keep only the samples whose timestamp lies in [start, end]."""
    ts_out: List[int] = []
    pw_out: List[float] = []
    for t, p in zip(timestamps_ns, powers_w):
        if start_ns <= t <= end_ns:
            ts_out.append(t)
            pw_out.append(p)
    return ts_out, pw_out


# ======================================================================
# Public entry point
# ======================================================================


def measure_inference_energy(
    model: nn.Module,
    model_name: str,
    input_ids: torch.Tensor,
    *,
    n_warmup: int = 50,
    n_measure: int = 500,
    device: str = "cuda",
    mode: str = "prefill",
    new_tokens_per_decode: int = 32,
    sample_rate_hz: float = 25.0,
    idle_window_seconds: float = 2.0,
    sampler_preference: str = "auto",
) -> EnergyMeasurement:
    """Measure inference energy on a real NVIDIA GPU.

    在真实 NVIDIA GPU 上测量推理能耗。

    Args:
        model:                  Module to benchmark (already constructed
                                with appropriate dtype). Will be moved
                                to ``device`` and put in eval mode.
        model_name:             Tag used in logs and the returned dict.
        input_ids:              Integer token ids of shape (B, S). Will
                                be moved to ``device``.
        n_warmup:               Forward passes to run BEFORE measurement
                                (compiles kernels, warms caches).
        n_measure:              Forward passes to run DURING measurement.
        device:                 Compute device; must be CUDA.
        mode:                   "prefill" -> one full forward per
                                            iteration; total_tokens =
                                            B * S * n_measure.
                                "decode"  -> autoregressive token-by-
                                            token decode with
                                            new_tokens_per_decode new
                                            tokens per iteration;
                                            total_tokens = B *
                                            new_tokens_per_decode *
                                            n_measure.
        new_tokens_per_decode:  Tokens generated per decode iteration
                                (ignored in prefill mode).
        sample_rate_hz:         Requested power-sampling rate.
        idle_window_seconds:    Duration of the idle baseline window.
        sampler_preference:     "auto" / "pynvml" / "nvidia_smi".

    Returns:
        :class:`EnergyMeasurement` with raw and above-idle numbers.

    Raises:
        RuntimeError: If CUDA is not available or no power sampler
                      can be initialised.
        ValueError:   If arguments are out of range.
    """
    # ----- Argument validation ---------------------------------------
    if not isinstance(input_ids, torch.Tensor):
        raise TypeError(
            f"input_ids must be a torch.Tensor, got {type(input_ids)}"
        )
    if input_ids.dim() != 2:
        raise ValueError(
            f"input_ids must have shape (B, S); got {tuple(input_ids.shape)}"
        )
    if n_warmup < 0 or n_measure < 1:
        raise ValueError(
            f"need n_warmup >= 0 and n_measure >= 1, got "
            f"n_warmup={n_warmup}, n_measure={n_measure}"
        )
    if mode not in {"prefill", "decode"}:
        raise ValueError(
            f"mode must be 'prefill' or 'decode', got {mode!r}"
        )
    if mode == "decode" and new_tokens_per_decode < 1:
        raise ValueError(
            "new_tokens_per_decode must be >= 1 in decode mode"
        )
    if idle_window_seconds <= 0.0:
        raise ValueError(
            "idle_window_seconds must be > 0"
        )

    # ----- Require an actual NVIDIA GPU ------------------------------
    if not str(device).startswith("cuda"):
        raise RuntimeError(
            "measure_inference_energy requires an NVIDIA GPU device; "
            f"got device={device!r}. CPU-only platforms cannot run a "
            "physical energy benchmark."
        )
    if not torch.cuda.is_available():
        raise RuntimeError(
            "measure_inference_energy requires CUDA-capable hardware; "
            "torch.cuda.is_available() returned False."
        )
    # Resolve device index for NVML.
    cuda_device = torch.device(device)
    device_index = int(
        cuda_device.index if cuda_device.index is not None else 0
    )

    # ----- Build sampler ---------------------------------------------
    sampler = _build_sampler(
        device_index=device_index,
        requested_rate_hz=float(sample_rate_hz),
        prefer=sampler_preference,
    )
    gpu_name = (
        sampler.gpu_name() if hasattr(sampler, "gpu_name")
        else "unknown-gpu"
    )

    notes: List[str] = [
        f"sampler={sampler.name}",
        f"requested_rate_hz={sample_rate_hz:.2f}",
    ]

    # ----- Prep model and inputs -------------------------------------
    model = model.to(cuda_device)
    model.eval()
    input_ids = input_ids.to(cuda_device)
    batch_size, seq_len = int(input_ids.shape[0]), int(input_ids.shape[1])

    # One forward function used in both warmup and measure loops.
    def _do_prefill() -> None:
        with torch.no_grad():
            _ = model(input_ids)

    def _do_decode() -> None:
        # Token-by-token greedy decode with KV cache OFF (most models
        # in this repo do not implement a KV cache). This deliberately
        # over-states the cost relative to a real production decoder;
        # it is the right reference for the "physical-framework"
        # comparison required by the UID predictions.
        with torch.no_grad():
            cur = input_ids
            max_len = getattr(
                getattr(model, "config", None),
                "max_position_embeddings",
                seq_len + new_tokens_per_decode + 1,
            )
            for _ in range(new_tokens_per_decode):
                if cur.shape[1] >= max_len:
                    cur = cur[:, -max_len + 1:]
                out = model(cur)
                logits = out.logits[:, -1, :]
                next_token = logits.argmax(dim=-1, keepdim=True)
                cur = torch.cat([cur, next_token], dim=1)

    do_step: Callable[[], None] = (
        _do_prefill if mode == "prefill" else _do_decode
    )

    # ----- Warmup (NOT measured) -------------------------------------
    for _ in range(int(n_warmup)):
        do_step()
    torch.cuda.synchronize(cuda_device)

    # ----- Idle baseline ---------------------------------------------
    sampler.start()
    try:
        # Pure idle: no forward, GPU sits with model loaded.
        idle_start_ns = time.perf_counter_ns()
        time.sleep(float(idle_window_seconds))
        idle_end_ns = time.perf_counter_ns()
        # Brief pause so the idle window and the work window do not
        # share any in-flight sample (NVML reports the most recent
        # value at the moment of query, but trapezoidal integration
        # spans the full interval between two samples).
        time.sleep(0.05)

        # ----- Measurement window ------------------------------------
        torch.cuda.synchronize(cuda_device)
        work_start_ns = time.perf_counter_ns()
        for _ in range(int(n_measure)):
            do_step()
        torch.cuda.synchronize(cuda_device)
        work_end_ns = time.perf_counter_ns()
    finally:
        sampler.stop()

    # ----- Pull samples & integrate ----------------------------------
    all_ts, all_pw = sampler.snapshot()

    idle_ts, idle_pw = _filter_window(
        all_ts, all_pw, idle_start_ns, idle_end_ns,
    )
    work_ts, work_pw = _filter_window(
        all_ts, all_pw, work_start_ns, work_end_ns,
    )

    if len(work_pw) < 2:
        notes.append(
            f"WARN: only {len(work_pw)} power samples taken during "
            f"the measurement window; consider raising n_measure "
            "or lowering sample_rate_hz."
        )

    # Achieved sample rate (work window only).
    work_duration_s = max((work_end_ns - work_start_ns) / 1.0e9, 1.0e-9)
    achieved_rate_hz = (
        len(work_pw) / work_duration_s if work_duration_s > 0 else 0.0
    )

    # Idle stats.
    idle_avg_w = (
        float(sum(idle_pw) / len(idle_pw)) if idle_pw else float("nan")
    )
    idle_window_s = max(
        (idle_end_ns - idle_start_ns) / 1.0e9, 1.0e-9,
    )

    # Work stats.
    avg_power_w = (
        float(sum(work_pw) / len(work_pw)) if work_pw else float("nan")
    )
    max_power_w = float(max(work_pw)) if work_pw else float("nan")
    raw_energy_j = _trapezoid_energy_j(work_ts, work_pw)

    # Above-idle: subtract a constant idle floor from every sample
    # before integrating. Clamp to 0 to avoid negative contributions
    # from sampling jitter.
    if idle_pw:
        adj_pw = [max(p - idle_avg_w, 0.0) for p in work_pw]
    else:
        adj_pw = list(work_pw)
    above_idle_energy_j = _trapezoid_energy_j(work_ts, adj_pw)

    # Tokens.
    if mode == "prefill":
        tokens_per_iter = batch_size * seq_len
        new_tokens_per_decode_report = 0
    else:
        tokens_per_iter = batch_size * int(new_tokens_per_decode)
        new_tokens_per_decode_report = int(new_tokens_per_decode)
    total_tokens = int(tokens_per_iter * n_measure)

    eptj = (
        raw_energy_j / total_tokens
        if total_tokens > 0 else float("nan")
    )
    eptj_above = (
        above_idle_energy_j / total_tokens
        if total_tokens > 0 else float("nan")
    )

    return EnergyMeasurement(
        model_name=str(model_name),
        mode=mode,
        device=str(cuda_device),
        gpu_name=gpu_name,
        sampler=sampler.name,
        sample_rate_hz=float(achieved_rate_hz),
        n_samples=int(len(work_pw)),
        n_warmup=int(n_warmup),
        n_measure=int(n_measure),
        batch_size=batch_size,
        seq_len=seq_len,
        total_tokens=total_tokens,
        new_tokens_per_decode=new_tokens_per_decode_report,
        wall_clock_seconds=float(work_duration_s),
        idle_power_watts=float(idle_avg_w),
        idle_window_seconds=float(idle_window_s),
        avg_power_watts=float(avg_power_w),
        max_power_watts=float(max_power_w),
        power_above_idle_watts=float(
            (avg_power_w - idle_avg_w)
            if (math.isfinite(avg_power_w) and math.isfinite(idle_avg_w))
            else float("nan")
        ),
        total_energy_joules=float(raw_energy_j),
        energy_above_idle_joules=float(above_idle_energy_j),
        energy_per_token_joules=float(eptj),
        energy_per_token_above_idle_joules=float(eptj_above),
        notes=notes,
    )
