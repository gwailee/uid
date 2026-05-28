# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Unit tests for experiments/run_scaling_law.py (v2.1).

Covers:
  - build_model dispatches all VALID_FAMILIES correctly.
  - build_model honours v2.1 toggles (noise_type, noise_tau,
    noise_beta, use_et_symmetric) — in particular:
      * cid_full_no_et       -> all CIDLayer.attn.use_et_symmetric == False
      * cid_full_fft_noise   -> all CIDLayer.noise is FastColoredNoise
      * cid_full             -> default OU + ET symmetric (sanity)
  - save_unified_checkpoint writes the v2.1 schema with all required keys.
  - The checkpoint round-trip rebuilds an architecturally identical
    model that loads the saved state_dict cleanly.
  - count_non_embedding_params returns a positive integer and matches
    the model's own helper when available.
  - estimate_train_flops respects the Chinchilla 6*N*D form.
  - Invalid family / scale arguments raise ValueError.

The tests deliberately use a tiny (256-d, 2-layer, 4-head) configuration
so the entire file runs in well under a minute on CPU.

Run with::

    pytest tests/test_run_scaling_law.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
import torch
import torch.nn as nn

# Import the script under test. We tolerate both layouts:
#   - experiments is a package (preferred):   experiments.run_scaling_law
#   - experiments is sys.path-injected:       run_scaling_law (legacy)
try:
    from experiments.run_scaling_law import (
        SCALE_CONFIGS,
        VALID_FAMILIES,
        build_model,
        count_non_embedding_params,
        estimate_train_flops,
        save_unified_checkpoint,
        _serialize_init_kwargs,
    )
except ImportError:  # pragma: no cover - legacy layout
    import sys
    _EXP_DIR = Path(__file__).resolve().parent.parent / "experiments"
    sys.path.insert(0, str(_EXP_DIR))
    from run_scaling_law import (  # type: ignore[no-redef]
        SCALE_CONFIGS,
        VALID_FAMILIES,
        build_model,
        count_non_embedding_params,
        estimate_train_flops,
        save_unified_checkpoint,
        _serialize_init_kwargs,
    )

from model.known_tricks_baseline import TransformerPlusTricksLM
from model.model_uid import UIDModel
from model.modern_transformer import ModernTransformerLM
from uid_theory.cid.colored_noise import (
    FastColoredNoise,
    OrnsteinUhlenbeckNoise,
)


# ----------------------------------------------------------------------
# Tiny config used across this test module to keep CPU runtime small.
# ----------------------------------------------------------------------
TINY_VOCAB = 256
TINY_SEQ_LEN = 32
TINY_SCALE = "10M"  # smallest entry in SCALE_CONFIGS


@pytest.fixture(autouse=True)
def _deterministic_seeds():
    """Make every test deterministic."""
    torch.manual_seed(0)


# ======================================================================
# 1. Family / scale enumeration
# ======================================================================


class TestFamiliesAndScales:
    """Basic invariants of the build_model dispatch table."""

    def test_valid_families_set_is_canonical(self):
        # The v2.1 README and ablation_suite both depend on these names.
        expected = {
            "transformer",
            "transformer_plus_tricks",
            "cid_full",
            "cid_full_no_et",
            "cid_full_fft_noise",
        }
        assert VALID_FAMILIES == expected, (
            "VALID_FAMILIES drifted from the v2.1 canonical set; "
            "this will break run_ablation.py and downstream scripts."
        )

    def test_scale_configs_have_required_keys(self):
        required_keys = {"hidden_size", "num_layers", "num_heads"}
        for name, cfg in SCALE_CONFIGS.items():
            assert required_keys.issubset(cfg.keys()), (
                f"SCALE_CONFIGS[{name!r}] missing required keys "
                f"{required_keys - cfg.keys()}"
            )
            # Sanity: num_heads must divide hidden_size.
            assert cfg["hidden_size"] % cfg["num_heads"] == 0, (
                f"SCALE_CONFIGS[{name!r}] has hidden_size not divisible "
                "by num_heads — this will crash attention construction."
            )

    @pytest.mark.parametrize("family", sorted({
        "transformer", "transformer_plus_tricks", "cid_full",
        "cid_full_no_et", "cid_full_fft_noise",
    }))
    def test_build_each_family_runs_forward(self, family):
        model = build_model(
            family=family,
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
        )
        x = torch.randint(0, TINY_VOCAB, (2, TINY_SEQ_LEN))
        out = model(x)
        assert out.logits.shape == (2, TINY_SEQ_LEN, TINY_VOCAB)


# ======================================================================
# 2. v2.1 toggle propagation
# ======================================================================


class TestV21TogglePropagation:
    """The v2.1 fixes (§8.5 ET, §14.2 OU/FFT) MUST really reach the
    underlying CIDLayer modules.  This is the central regression test.
    """

    def _get_cid_layers(self, model):
        # UIDModel exposes the stack of CIDLayer via .backbone.layers.
        assert isinstance(model, UIDModel), (
            "Expected a UIDModel; got "
            f"{type(model).__name__} (test only valid for CID families)."
        )
        layers = model.backbone.layers
        assert len(layers) > 0, "Empty CID backbone"
        return layers

    # ------ §8.5 ET symmetric -----------------------------------------

    def test_cid_full_enables_et_symmetric_everywhere(self):
        model = build_model(
            family="cid_full",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
        )
        for i, layer in enumerate(self._get_cid_layers(model)):
            assert layer.attn.use_et_symmetric is True, (
                f"cid_full layer {i} has ET disabled — §8.5 toggle "
                "did NOT propagate from build_model."
            )

    def test_cid_full_no_et_disables_et_symmetric_everywhere(self):
        model = build_model(
            family="cid_full_no_et",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
        )
        for i, layer in enumerate(self._get_cid_layers(model)):
            assert layer.attn.use_et_symmetric is False, (
                f"cid_full_no_et layer {i} still has ET enabled — the "
                "§8.5 isolation ablation will be a silent no-op."
            )

    def test_global_no_et_flag_overrides_default(self):
        # The CLI exposes --no_et_symmetric; here we exercise the
        # programmatic equivalent.
        model = build_model(
            family="cid_full",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            use_et_symmetric=False,
        )
        for layer in self._get_cid_layers(model):
            assert layer.attn.use_et_symmetric is False

    # ------ §14.2 OU vs FFT noise -------------------------------------

    def test_cid_full_defaults_to_ou_noise(self):
        model = build_model(
            family="cid_full",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
        )
        for i, layer in enumerate(self._get_cid_layers(model)):
            assert isinstance(layer.noise, OrnsteinUhlenbeckNoise), (
                f"cid_full layer {i} uses "
                f"{type(layer.noise).__name__}; expected "
                "OrnsteinUhlenbeckNoise per §14.2."
            )

    def test_cid_full_fft_noise_uses_fft_noise_everywhere(self):
        model = build_model(
            family="cid_full_fft_noise",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
        )
        for i, layer in enumerate(self._get_cid_layers(model)):
            assert isinstance(layer.noise, FastColoredNoise), (
                f"cid_full_fft_noise layer {i} uses "
                f"{type(layer.noise).__name__}; expected "
                "FastColoredNoise — §14.2 isolation broken."
            )

    def test_noise_tau_propagates_to_ou_modules(self):
        custom_tau = 17.5
        model = build_model(
            family="cid_full",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            noise_type="ou",
            noise_tau=custom_tau,
        )
        for layer in self._get_cid_layers(model):
            assert isinstance(layer.noise, OrnsteinUhlenbeckNoise)
            assert layer.noise.tau == pytest.approx(custom_tau), (
                f"OU tau did not propagate (expected {custom_tau}, "
                f"got {layer.noise.tau})."
            )

    def test_noise_beta_propagates_to_fft_modules(self):
        custom_beta = 0.75
        model = build_model(
            family="cid_full_fft_noise",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            noise_beta=custom_beta,
        )
        for layer in self._get_cid_layers(model):
            assert isinstance(layer.noise, FastColoredNoise)
            assert layer.noise.beta == pytest.approx(custom_beta), (
                f"FFT beta did not propagate (expected {custom_beta}, "
                f"got {layer.noise.beta})."
            )

    def test_transformer_plus_tricks_receives_noise_kwargs(self):
        model = build_model(
            family="transformer_plus_tricks",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            noise_type="ou",
            noise_tau=12.3,
        )
        assert isinstance(model, TransformerPlusTricksLM)
        # Inspect the first block's noise module.
        first_block = model.blocks[0]
        # Some implementations gate the noise module behind use_noise.
        assert getattr(first_block, "use_noise", True) is True, (
            "transformer_plus_tricks built without noise — toggles "
            "were silently dropped."
        )
        if hasattr(first_block, "noise"):
            assert isinstance(
                first_block.noise, OrnsteinUhlenbeckNoise
            ), (
                "transformer_plus_tricks did not adopt the OU noise "
                "implementation despite noise_type='ou'."
            )
            assert first_block.noise.tau == pytest.approx(12.3)


# ======================================================================
# 3. Input validation
# ======================================================================


class TestInputValidation:
    def test_unknown_family_raises(self):
        with pytest.raises(ValueError, match="Unknown model family"):
            build_model(
                family="bogus",
                scale=TINY_SCALE,
                vocab_size=TINY_VOCAB,
                max_seq_len=TINY_SEQ_LEN,
            )

    def test_unknown_scale_raises(self):
        with pytest.raises(ValueError, match="Unknown scale"):
            build_model(
                family="cid_full",
                scale="42M",
                vocab_size=TINY_VOCAB,
                max_seq_len=TINY_SEQ_LEN,
            )


# ======================================================================
# 4. count_non_embedding_params & FLOP estimator
# ======================================================================


class TestCountNonEmbeddingParams:
    def test_returns_positive_int_for_each_family(self):
        for family in sorted(VALID_FAMILIES):
            model = build_model(
                family=family,
                scale=TINY_SCALE,
                vocab_size=TINY_VOCAB,
                max_seq_len=TINY_SEQ_LEN,
            )
            n = count_non_embedding_params(model)
            assert isinstance(n, int) and n > 0, (
                f"count_non_embedding_params({family}) returned {n!r}"
            )

    def test_matches_model_helper_when_present(self):
        # Modern Transformer / TransformerPlusTricksLM both expose
        # count_non_embedding_params(); generic fallback must agree.
        for family in ("transformer", "transformer_plus_tricks"):
            model = build_model(
                family=family,
                scale=TINY_SCALE,
                vocab_size=TINY_VOCAB,
                max_seq_len=TINY_SEQ_LEN,
            )
            assert hasattr(model, "count_non_embedding_params")
            n_self = model.count_non_embedding_params()
            n_generic = count_non_embedding_params(model)
            assert n_self == n_generic, (
                f"{family}: own helper says {n_self}, generic helper "
                f"says {n_generic}"
            )


class TestFlopEstimator:
    @pytest.mark.parametrize("n,d", [
        (1, 1),
        (10**6, 10**9),
        (123_456_789, 1_000_000),
    ])
    def test_chinchilla_6nd_formula(self, n, d):
        assert estimate_train_flops(n, d) == pytest.approx(6.0 * n * d)


# ======================================================================
# 5. Unified checkpoint schema (v2.1)
# ======================================================================


class TestUnifiedCheckpoint:
    """save_unified_checkpoint -> torch.load round-trip must preserve
    every field that run_critical_exponents.py / run_energy_benchmark.py
    rely on.
    """

    REQUIRED_TOP_LEVEL_KEYS = {
        "schema_version",
        "model_family",
        "scale_name",
        "init_kwargs",
        "config_dict",
        "model_state",
        "seed",
        "n_params",
        "v21_keys",
    }

    REQUIRED_INIT_KWARGS = {
        "family",
        "scale",
        "vocab_size",
        "max_seq_len",
        "noise_type",
        "noise_tau",
        "noise_beta",
        "use_et_symmetric",
    }

    REQUIRED_V21_KEYS = {
        "noise_type",
        "noise_tau",
        "noise_beta",
        "use_et_symmetric",
    }

    def _build_and_save(
        self, tmp_path: Path, family: str = "cid_full",
        **overrides,
    ) -> tuple[Dict[str, Any], Path, Any]:
        init_kwargs = _serialize_init_kwargs(
            family=family,
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            noise_type=overrides.get("noise_type", "ou"),
            noise_tau=overrides.get("noise_tau", 10.0),
            noise_beta=overrides.get("noise_beta", 1.0),
            use_et_symmetric=overrides.get("use_et_symmetric", True),
        )
        model = build_model(
            family=init_kwargs["family"],
            scale=init_kwargs["scale"],
            vocab_size=init_kwargs["vocab_size"],
            max_seq_len=init_kwargs["max_seq_len"],
            noise_type=init_kwargs["noise_type"],
            noise_tau=init_kwargs["noise_tau"],
            noise_beta=init_kwargs["noise_beta"],
            use_et_symmetric=init_kwargs["use_et_symmetric"],
        )
        n_params = count_non_embedding_params(model)
        out_path = save_unified_checkpoint(
            ckpt_dir=tmp_path / "ckpts",
            family=family,
            scale=TINY_SCALE,
            seed=42,
            model=model,
            init_kwargs=init_kwargs,
            n_params=n_params,
        )
        ckpt = torch.load(out_path, map_location="cpu")
        return ckpt, out_path, model

    def test_filename_pattern(self, tmp_path):
        _, out_path, _ = self._build_and_save(tmp_path)
        assert out_path.name == "cid_full_10M_seed42.pt", (
            f"Checkpoint filename is {out_path.name!r}; "
            "run_all.py and run_energy_benchmark.py expect the "
            "{family}_{scale}_seed{seed}.pt pattern."
        )
        assert out_path.exists()

    def test_top_level_schema(self, tmp_path):
        ckpt, _, _ = self._build_and_save(tmp_path)
        missing = self.REQUIRED_TOP_LEVEL_KEYS - set(ckpt.keys())
        assert not missing, (
            f"v2.1 checkpoint is missing top-level keys: {sorted(missing)}"
        )
        assert ckpt["schema_version"] == "v2.1"
        assert ckpt["model_family"] == "cid_full"
        assert ckpt["scale_name"] == TINY_SCALE
        assert ckpt["seed"] == 42
        assert ckpt["n_params"] > 0
        assert isinstance(ckpt["model_state"], dict) and ckpt["model_state"]

    def test_init_kwargs_complete(self, tmp_path):
        ckpt, _, _ = self._build_and_save(tmp_path)
        init = ckpt["init_kwargs"]
        missing = self.REQUIRED_INIT_KWARGS - set(init.keys())
        assert not missing, (
            f"init_kwargs missing keys: {sorted(missing)} — "
            "downstream scripts will fail to rebuild the model."
        )

    def test_v21_keys_record_toggles(self, tmp_path):
        ckpt, _, _ = self._build_and_save(
            tmp_path,
            noise_type="fft",
            noise_beta=0.85,
            use_et_symmetric=False,
        )
        v21 = ckpt["v21_keys"]
        missing = self.REQUIRED_V21_KEYS - set(v21.keys())
        assert not missing, (
            f"v21_keys missing entries: {sorted(missing)}"
        )
        assert v21["noise_type"] == "fft"
        assert v21["noise_beta"] == pytest.approx(0.85)
        assert v21["use_et_symmetric"] is False

    def test_config_dict_present_for_cid_model(self, tmp_path):
        ckpt, _, _ = self._build_and_save(tmp_path, family="cid_full")
        cfg = ckpt["config_dict"]
        assert cfg is not None and isinstance(cfg, dict), (
            "config_dict should hold UIDConfig.to_dict() for CID models"
        )
        # Critical v2.1 fields must survive the HF round-trip.
        for key in ("noise_type", "noise_tau", "use_et_symmetric"):
            assert key in cfg, (
                f"UIDConfig.to_dict() is missing v2.1 field {key!r} — "
                "HuggingFace save_pretrained/from_pretrained will drop it."
            )

    def test_config_dict_none_for_non_cid_model(self, tmp_path):
        # For ModernTransformerLM there is no HF-style config to serialise,
        # so config_dict should be None (and downstream loaders fall back
        # to init_kwargs).
        ckpt, _, _ = self._build_and_save(tmp_path, family="transformer")
        assert ckpt["config_dict"] is None

    def test_round_trip_state_dict_loads_cleanly(self, tmp_path):
        ckpt, _, orig_model = self._build_and_save(tmp_path)
        # Rebuild a fresh model from the saved init_kwargs and load state.
        init = ckpt["init_kwargs"]
        rebuilt = build_model(
            family=init["family"],
            scale=init["scale"],
            vocab_size=init["vocab_size"],
            max_seq_len=init["max_seq_len"],
            noise_type=init["noise_type"],
            noise_tau=init["noise_tau"],
            noise_beta=init["noise_beta"],
            use_et_symmetric=init["use_et_symmetric"],
        )
        missing, unexpected = rebuilt.load_state_dict(
            ckpt["model_state"], strict=False,
        )
        # Tied weights (lm_head <-> tok_emb) sometimes show up as
        # missing/unexpected depending on torch version; tolerate them.
        for key_list, label in (
            (missing, "missing"),
            (unexpected, "unexpected"),
        ):
            unexplained = [
                k for k in key_list
                if not k.endswith(("lm_head.weight", "tok_emb.weight"))
            ]
            assert not unexplained, (
                f"Unexplained {label} keys after round-trip: "
                f"{unexplained}"
            )

    def test_round_trip_preserves_forward_output_shape(self, tmp_path):
        ckpt, _, _ = self._build_and_save(tmp_path)
        init = ckpt["init_kwargs"]
        rebuilt = build_model(
            family=init["family"],
            scale=init["scale"],
            vocab_size=init["vocab_size"],
            max_seq_len=init["max_seq_len"],
            noise_type=init["noise_type"],
            noise_tau=init["noise_tau"],
            noise_beta=init["noise_beta"],
            use_et_symmetric=init["use_et_symmetric"],
        )
        rebuilt.load_state_dict(ckpt["model_state"], strict=False)
        rebuilt.eval()
        x = torch.randint(
            0, init["vocab_size"], (2, init["max_seq_len"]),
        )
        out = rebuilt(x)
        assert out.logits.shape == (
            2, init["max_seq_len"], init["vocab_size"],
        )

    def test_round_trip_preserves_v21_toggles_through_model(self, tmp_path):
        """The toggles must survive the save/load cycle and still be
        visible on the rebuilt CID layers.
        """
        ckpt, _, _ = self._build_and_save(
            tmp_path,
            family="cid_full_no_et",
            noise_type="fft",
            noise_beta=0.9,
            use_et_symmetric=False,
        )
        init = ckpt["init_kwargs"]
        rebuilt = build_model(
            family=init["family"],
            scale=init["scale"],
            vocab_size=init["vocab_size"],
            max_seq_len=init["max_seq_len"],
            noise_type=init["noise_type"],
            noise_tau=init["noise_tau"],
            noise_beta=init["noise_beta"],
            use_et_symmetric=init["use_et_symmetric"],
        )
        # Sanity: rebuilt model is still §8.5-disabled and FFT-noise.
        for layer in rebuilt.backbone.layers:
            assert layer.attn.use_et_symmetric is False, (
                "Round-trip lost the §8.5 ET-off toggle"
            )
            assert isinstance(layer.noise, FastColoredNoise), (
                "Round-trip lost the FFT noise selection"
            )


# ======================================================================
# 6. JSON-safety of init_kwargs (run_all.py writes it verbatim)
# ======================================================================


class TestInitKwargsJsonSafety:
    def test_serialise_to_json_and_back(self):
        kw = _serialize_init_kwargs(
            family="cid_full_no_et",
            scale=TINY_SCALE,
            vocab_size=TINY_VOCAB,
            max_seq_len=TINY_SEQ_LEN,
            noise_type="fft",
            noise_tau=10.0,
            noise_beta=0.85,
            use_et_symmetric=False,
        )
        # Must be JSON-serialisable for run_all_summary.json.
        as_str = json.dumps(kw)
        restored = json.loads(as_str)
        assert restored == kw, (
            "init_kwargs lost or mutated information during JSON "
            "round-trip — run_all.py's summary file will be corrupted."
        )
