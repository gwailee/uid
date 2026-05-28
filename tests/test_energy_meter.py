# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Unit tests for uid_theory/verification/energy_meter.py (v2.1).

These tests cover the parts of the module that DO NOT require an
actual GPU:

  * _trapezoid_energy_j numerical correctness on synthetic data.
  * _filter_window timestamp boundary semantics.
  * _build_sampler dispatch logic (auto / pynvml / nvidia_smi).
  * EnergyMeasurement.to_dict() schema completeness.
  * measure_inference_energy() argument validation.
  * measure_inference_energy() CPU-platform refusal contract.
  * _PowerSampler background-thread lifecycle via a synthetic
    in-memory subclass (no NVML, no nvidia-smi).

A full end-to-end GPU benchmark test (marked ``@pytest.mark.gpu``) is
included but auto-skipped when no CUDA-capable device is available, so
this file is portable to CI.

Run with::

    pytest tests/test_energy_meter.py -v

To force the GPU test on a CUDA box::

    pytest tests/test_energy_meter.py -v -m gpu
"""

from __future__ import annotations

import math
import time
from typing import List

import pytest
import torch
import torch.nn as nn

from uid_theory.verification.energy_meter import (
    EnergyMeasurement,
    _build_sampler,
    _filter_window,
    _NvidiaSmiSampler,
    _PowerSampler,
    _PyNvmlSampler,
    _trapezoid_energy_j,
    measure_inference_energy,
)


# ======================================================================
# Trapezoidal integration
# ======================================================================


class TestTrapezoidEnergy:
    def test_constant_power_integrates_to_p_times_t(self):
        """Constant 100 W over 2 s = 200 J."""
        # 21 samples at 100 Hz over 2 s.
        n = 21
        ts = [int(i * 1.0e8) for i in range(n)]  # 0.1 s steps
        pw = [100.0] * n
        # Total interval = 20 * 0.1 s = 2.0 s; expected = 200 J.
        e = _trapezoid_energy_j(ts, pw)
        assert e == pytest.approx(200.0, rel=1e-6)

    def test_linear_ramp_integrates_correctly(self):
        """Linear ramp from 0 W to 100 W over 10 s -> 500 J (triangle)."""
        n = 1001
        ts = [int(i * 1.0e7) for i in range(n)]  # 0.01 s steps -> 10 s total
        pw = [100.0 * i / (n - 1) for i in range(n)]
        e = _trapezoid_energy_j(ts, pw)
        assert e == pytest.approx(500.0, rel=1e-3)

    def test_fewer_than_two_samples_returns_zero(self):
        assert _trapezoid_energy_j([], []) == 0.0
        assert _trapezoid_energy_j([0], [50.0]) == 0.0

    def test_mismatched_lengths_raise(self):
        with pytest.raises(ValueError, match="same length"):
            _trapezoid_energy_j([0, 1, 2], [1.0, 2.0])

    def test_zero_or_negative_dt_segments_skipped(self):
        """Duplicate timestamps must not corrupt the result."""
        ts = [0, 0, int(1.0e9), int(1.0e9)]
        pw = [10.0, 10.0, 10.0, 10.0]
        # Two real segments: 0 -> 1s with avg 10W = 10 J.
        e = _trapezoid_energy_j(ts, pw)
        assert e == pytest.approx(10.0, rel=1e-6)


# ======================================================================
# Window filtering
# ======================================================================


class TestFilterWindow:
    def test_inclusive_boundaries(self):
        ts = [100, 200, 300, 400, 500]
        pw = [1.0, 2.0, 3.0, 4.0, 5.0]
        keep_ts, keep_pw = _filter_window(ts, pw, 200, 400)
        assert keep_ts == [200, 300, 400]
        assert keep_pw == [2.0, 3.0, 4.0]

    def test_empty_window_returns_empty(self):
        ts = [100, 200, 300]
        pw = [1.0, 2.0, 3.0]
        keep_ts, keep_pw = _filter_window(ts, pw, 1000, 2000)
        assert keep_ts == []
        assert keep_pw == []

    def test_handles_empty_input(self):
        keep_ts, keep_pw = _filter_window([], [], 0, 100)
        assert keep_ts == []
        assert keep_pw == []


# ======================================================================
# Synthetic sampler (no NVML / nvidia-smi needed)
# ======================================================================


class _SyntheticSampler(_PowerSampler):
    """In-memory sampler that returns a synthetic ramp.

    Useful for testing the background-thread lifecycle without any
    GPU drivers.
    """

    def __init__(self, sample_rate_hz: float = 100.0) -> None:
        super().__init__(device_index=0, sample_rate_hz=sample_rate_hz)
        self._counter = 0

    @property
    def name(self) -> str:
        return "synthetic"

    def _read_power_watts(self) -> float:
        self._counter += 1
        # Return a deterministic ramp: 10, 20, 30, ... W
        return float(10 * self._counter)


class TestPowerSamplerLifecycle:
    def test_start_collects_samples(self):
        s = _SyntheticSampler(sample_rate_hz=100.0)
        s.start()
        try:
            time.sleep(0.3)  # collect ~30 samples at 100 Hz
        finally:
            s.stop()
        ts, pw = s.snapshot()
        assert len(ts) > 5, (
            f"Expected at least 5 samples at 100Hz over 0.3s, got {len(ts)}"
        )
        # Power readings should be the increasing synthetic ramp.
        assert pw == sorted(pw)

    def test_double_start_raises(self):
        s = _SyntheticSampler(sample_rate_hz=50.0)
        s.start()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                s.start()
        finally:
            s.stop()

    def test_stop_without_start_is_noop(self):
        s = _SyntheticSampler()
        # Should not raise.
        s.stop()

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="sample_rate_hz must be"):
            _SyntheticSampler(sample_rate_hz=0.0)


# ======================================================================
# _build_sampler dispatch
# ======================================================================


def _have_pynvml() -> bool:
    try:
        import pynvml  # noqa: F401
        return True
    except ImportError:
        return False


def _have_nvidia_smi() -> bool:
    import shutil
    return shutil.which("nvidia-smi") is not None


class TestSamplerDispatch:
    def test_invalid_prefer_raises(self):
        with pytest.raises(ValueError, match="prefer must be one of"):
            _build_sampler(device_index=0, requested_rate_hz=10.0,
                           prefer="something_else")

    def test_force_pynvml_when_missing_raises(self):
        """Forcing pynvml on a machine without it must raise."""
        if _have_pynvml():
            pytest.skip("pynvml is installed; cannot test the missing case")
        with pytest.raises(RuntimeError, match="pynvml is not available"):
            _build_sampler(device_index=0, requested_rate_hz=10.0,
                           prefer="pynvml")

    def test_force_nvidia_smi_when_missing_raises(self):
        if _have_nvidia_smi():
            pytest.skip("nvidia-smi is installed; cannot test the missing case")
        with pytest.raises(RuntimeError, match="nvidia-smi not found"):
            _build_sampler(device_index=0, requested_rate_hz=10.0,
                           prefer="nvidia_smi")

    def test_auto_picks_pynvml_when_available(self):
        if not _have_pynvml():
            pytest.skip("pynvml not installed; skipping")
        # NOTE: this may still fail on a machine with pynvml but no
        # actual NVIDIA GPU (nvmlInit raises). Treat that as a skip
        # condition.
        try:
            s = _build_sampler(device_index=0, requested_rate_hz=10.0,
                               prefer="auto")
        except Exception as exc:
            pytest.skip(f"pynvml install present but unusable: {exc}")
        assert isinstance(s, _PyNvmlSampler)

    def test_auto_falls_back_to_nvidia_smi(self):
        if _have_pynvml():
            pytest.skip("pynvml is present; auto will choose it, "
                        "cannot test fallback path")
        if not _have_nvidia_smi():
            pytest.skip("nvidia-smi missing; cannot test fallback path")
        s = _build_sampler(device_index=0, requested_rate_hz=10.0,
                           prefer="auto")
        assert isinstance(s, _NvidiaSmiSampler)


# ======================================================================
# EnergyMeasurement dataclass schema
# ======================================================================


class TestEnergyMeasurementSchema:
    REQUIRED_KEYS = {
        "model_name", "mode", "device", "gpu_name", "sampler",
        "sample_rate_hz", "n_samples", "n_warmup", "n_measure",
        "batch_size", "seq_len", "total_tokens",
        "new_tokens_per_decode", "wall_clock_seconds",
        "idle_power_watts", "idle_window_seconds",
        "avg_power_watts", "max_power_watts",
        "power_above_idle_watts",
        "total_energy_joules", "energy_above_idle_joules",
        "energy_per_token_joules",
        "energy_per_token_above_idle_joules",
        "notes",
    }

    def test_to_dict_has_all_required_keys(self):
        em = EnergyMeasurement(
            model_name="dummy", mode="prefill", device="cuda:0",
            gpu_name="fake", sampler="synthetic",
            sample_rate_hz=25.0, n_samples=10, n_warmup=0,
            n_measure=1, batch_size=1, seq_len=8, total_tokens=8,
            new_tokens_per_decode=0,
            wall_clock_seconds=0.1, idle_power_watts=50.0,
            idle_window_seconds=2.0,
            avg_power_watts=100.0, max_power_watts=120.0,
            power_above_idle_watts=50.0,
            total_energy_joules=10.0, energy_above_idle_joules=5.0,
            energy_per_token_joules=1.25,
            energy_per_token_above_idle_joules=0.625,
        )
        d = em.to_dict()
        missing = self.REQUIRED_KEYS - set(d.keys())
        assert not missing, (
            f"EnergyMeasurement.to_dict() missing keys: {sorted(missing)}"
        )
        assert d["mode"] == "prefill"
        assert d["notes"] == []


# ======================================================================
# measure_inference_energy: argument validation
# ======================================================================


class _DummyModel(nn.Module):
    """Tiny LM-shaped module sufficient for argument-validation tests."""

    def __init__(self, vocab: int = 32, hidden: int = 16):
        super().__init__()
        self.tok_emb = nn.Embedding(vocab, hidden)
        self.lm_head = nn.Linear(hidden, vocab, bias=False)

    def forward(self, input_ids):  # noqa: D401
        x = self.tok_emb(input_ids)
        logits = self.lm_head(x)
        # Return an object with a ``.logits`` attribute so decode mode
        # works without HuggingFace dependencies.
        class _Out:  # noqa: D401
            pass
        out = _Out()
        out.logits = logits
        return out


class TestArgumentValidation:
    """All argument-validation cases run BEFORE the CUDA gate, so they
    must raise the expected error even on CPU."""

    def test_input_ids_must_be_tensor(self):
        model = _DummyModel()
        with pytest.raises(TypeError, match="must be a torch.Tensor"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=[1, 2, 3],  # type: ignore[arg-type]
            )

    def test_input_ids_must_be_2d(self):
        model = _DummyModel()
        with pytest.raises(ValueError, match="shape \\(B, S\\)"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(8, dtype=torch.long),
            )

    def test_n_measure_must_be_positive(self):
        model = _DummyModel()
        with pytest.raises(ValueError, match="n_warmup"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                n_warmup=0, n_measure=0,
            )

    def test_bad_mode_raises(self):
        model = _DummyModel()
        with pytest.raises(ValueError, match="mode must be"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                mode="speculative",
            )

    def test_decode_requires_positive_new_tokens(self):
        model = _DummyModel()
        with pytest.raises(ValueError, match="new_tokens_per_decode"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                mode="decode", new_tokens_per_decode=0,
            )

    def test_idle_window_must_be_positive(self):
        model = _DummyModel()
        with pytest.raises(ValueError, match="idle_window_seconds"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                idle_window_seconds=0.0,
            )


# ======================================================================
# CPU-platform refusal contract
# ======================================================================


class TestCpuPlatformRefusal:
    def test_cpu_device_raises_runtime_error(self):
        model = _DummyModel()
        with pytest.raises(RuntimeError, match="requires an NVIDIA GPU"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                device="cpu",
            )

    def test_cuda_unavailable_raises_runtime_error(self):
        if torch.cuda.is_available():
            pytest.skip("CUDA is available; cannot test the negative path")
        model = _DummyModel()
        with pytest.raises(RuntimeError, match="CUDA-capable hardware"):
            measure_inference_energy(
                model=model, model_name="x",
                input_ids=torch.zeros(1, 4, dtype=torch.long),
                device="cuda",
            )


# ======================================================================
# End-to-end GPU smoke (only when CUDA is available)
# ======================================================================


_GPU_AVAILABLE = (
    torch.cuda.is_available()
    and (_have_pynvml() or _have_nvidia_smi())
)


@pytest.mark.gpu
@pytest.mark.skipif(
    not _GPU_AVAILABLE,
    reason="Requires CUDA + (pynvml or nvidia-smi)",
)
class TestEndToEndGPU:
    def test_prefill_runs_and_reports_sane_numbers(self):
        model = _DummyModel(vocab=128, hidden=64)
        input_ids = torch.randint(0, 128, (2, 32))
        em = measure_inference_energy(
            model=model, model_name="dummy_prefill",
            input_ids=input_ids,
            n_warmup=10, n_measure=50,
            device="cuda",
            mode="prefill",
            sample_rate_hz=25.0,
            idle_window_seconds=1.0,
        )
        assert em.mode == "prefill"
        assert em.batch_size == 2
        assert em.seq_len == 32
        assert em.total_tokens == 2 * 32 * 50
        assert em.wall_clock_seconds > 0.0
        assert em.avg_power_watts > 0.0
        assert math.isfinite(em.energy_per_token_joules)
        # Energy must be roughly avg_power * wall_clock.
        rough_e = em.avg_power_watts * em.wall_clock_seconds
        assert em.total_energy_joules == pytest.approx(
            rough_e, rel=0.3
        ), (
            f"total_energy {em.total_energy_joules:.3f} J inconsistent "
            f"with avg_power*wall_clock = {rough_e:.3f} J"
        )

    def test_decode_runs_and_reports_sane_numbers(self):
        model = _DummyModel(vocab=128, hidden=64)
        # Give the dummy model a max_position_embeddings hint.
        class _Cfg:  # noqa: D401
            max_position_embeddings = 96
        model.config = _Cfg()  # type: ignore[attr-defined]

        input_ids = torch.randint(0, 128, (2, 8))
        em = measure_inference_energy(
            model=model, model_name="dummy_decode",
            input_ids=input_ids,
            n_warmup=5, n_measure=10,
            device="cuda",
            mode="decode",
            new_tokens_per_decode=8,
            sample_rate_hz=20.0,
            idle_window_seconds=1.0,
        )
        assert em.mode == "decode"
        assert em.new_tokens_per_decode == 8
        # total_tokens for decode = B * new_tokens_per_decode * n_measure
        assert em.total_tokens == 2 * 8 * 10
        assert em.avg_power_watts > 0.0
        assert em.energy_per_token_joules > 0.0
