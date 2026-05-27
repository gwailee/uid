# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""Shared pytest fixtures."""

from __future__ import annotations

import numpy as np
import pytest
import torch


@pytest.fixture(autouse=True)
def set_random_seeds():
    """Set deterministic seeds for every test."""
    np.random.seed(42)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)


@pytest.fixture
def device() -> str:
    """Compute device (prefer CPU for fast/portable tests)."""
    return "cpu"


@pytest.fixture
def small_config() -> dict:
    """Tiny config for fast tests."""
    return {
        "vocab_size": 256,
        "hidden_size": 64,
        "num_layers": 2,
        "num_heads": 4,
        "max_seq_len": 32,
    }


@pytest.fixture
def small_batch(small_config) -> torch.Tensor:
    """Random batch matching small_config."""
    return torch.randint(
        0, small_config["vocab_size"],
        (2, small_config["max_seq_len"]),
    )


@pytest.fixture
def power_law_samples() -> np.ndarray:
    """Generate 10,000 samples from a known power law (α=2.5, xmin=1)."""
    rng = np.random.default_rng(42)
    n = 10_000
    alpha = 2.5
    xmin = 1.0
    u = rng.uniform(size=n)
    return xmin * (1.0 - u) ** (1.0 / (1.0 - alpha))
