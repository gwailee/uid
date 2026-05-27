# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""Tests for the ablation-suite configuration."""

from __future__ import annotations

import pytest
import torch

from uid_theory.verification.ablation_suite import (
    AblationConfig,
    build_ablation_model,
    get_ablation_configs,
)


class TestAblationConfigs:
    def test_minimum_9_variants(self):
        """v2.0 must have at least 9 ablation variants."""
        configs = get_ablation_configs()
        assert len(configs) >= 9, \
            f"Expected ≥9 ablation variants, got {len(configs)}"

    def test_has_cid_no_memory(self):
        """cid_no_memory was missing in v0.1 — must be present in v2.0."""
        configs = get_ablation_configs()
        names = [c.name for c in configs]
        assert "cid_no_memory" in names, \
            "cid_no_memory ablation is required (was missing in v0.1)"

    def test_has_full_cid(self):
        configs = get_ablation_configs()
        names = [c.name for c in configs]
        assert "cid_full" in names

    def test_has_critical_baseline(self):
        """transformer_plus_all_tricks is the critical comparison."""
        configs = get_ablation_configs()
        names = [c.name for c in configs]
        assert "transformer_plus_all_tricks" in names

    def test_all_names_unique(self):
        configs = get_ablation_configs()
        names = [c.name for c in configs]
        assert len(names) == len(set(names)), "Duplicate ablation names"


class TestBuildAblationModel:
    @pytest.fixture
    def model_kwargs(self):
        return dict(
            vocab_size=256,
            hidden_size=64,
            num_layers=2,
            num_heads=4,
            max_seq_len=32,
        )

    def test_build_all_variants(self, model_kwargs):
        """Every config should build a working model."""
        configs = get_ablation_configs()
        for config in configs:
            model = build_ablation_model(config=config, **model_kwargs)
            x = torch.randint(0, 256, (1, 16))
            out = model(x)
            assert out.logits.shape == (1, 16, 256), \
                f"Failed for {config.name}"

    def test_unknown_family_raises(self, model_kwargs):
        config = AblationConfig(
            name="bogus", description="invalid", family="unknown_family"
        )
        with pytest.raises(ValueError, match="Unknown family"):
            build_ablation_model(config=config, **model_kwargs)
