# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * Load checkpoints in the v2.1 unified schema (init_kwargs +
#     config_dict + model_state) saved by run_scaling_law.py.
#   * Verdict now CONTRASTS noise-OFF vs noise-ON measurements, not
#     just inspects noise-OFF alone. Small (β,H) difference between
#     ON and OFF -> noise-OFF measurement may be a residual echo and
#     warning is emitted; only large diff + in-range noise-OFF
#     constitutes genuine emergence.
"""
Run rigorous critical-exponent measurement (with noise injection OFF).

Usage:
    python experiments/run_critical_exponents.py \\
        --checkpoint results/scaling_law_v2.1/checkpoints/cid_full_100M_seed42.pt \\
        --data_path ./data/wikitext-2/test.jsonl \\
        --tokenizer_path gpt2 \\
        --output_dir results/critical_exponents_v2.1

This script:
1. Loads a trained model (v2.1 unified checkpoint schema).
2. Disables noise injection (CRITICAL — otherwise circular).
3. Collects hidden states from >=10,000 sequences.
4. Measures Hurst exponent (DFA), spectrum slope β, avalanche τ.
5. Uses Clauset-Shalizi-Newman MLE for power-law fitting.
6. Also runs the SAME measurement with noise injection ON, then
   contrasts the two to detect circular-measurement artifacts.
7. Reports whether emergence is genuine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import torch
from torch.utils.data import DataLoader

from uid_theory.verification.critical_exponents import (
    run_critical_exponent_battery,
)


# ======================================================================
# Unified v2.1 checkpoint loader
# ======================================================================


def _load_model_from_unified_ckpt(ckpt_path: Path, device: str):
    """Rebuild a model from the v2.1 unified checkpoint schema.

    Schema:
        {"schema_version": "v2.1",
         "model_family":   "cid_full" | "transformer" | ...,
         "init_kwargs":    {family, scale, vocab_size, max_seq_len, ...},
         "config_dict":    {UIDConfig.to_dict()} | None,
         "model_state":    state_dict, ...}

    Falls back gracefully to the legacy v0.1 schema for backward
    compatibility (assuming ``ckpt["config"]`` is a plain kwargs dict).
    """
    ckpt = torch.load(ckpt_path, map_location=device)

    # ----- v2.1 schema --------------------------------------------------
    if ckpt.get("schema_version") == "v2.1":
        family = ckpt["model_family"]
        init_kwargs = ckpt["init_kwargs"]
        # Lazy import to avoid hard deps when scripts are run standalone.
        from experiments.run_scaling_law import build_model  # type: ignore
        model = build_model(
            family=init_kwargs["family"],
            scale=init_kwargs["scale"],
            vocab_size=init_kwargs["vocab_size"],
            max_seq_len=init_kwargs["max_seq_len"],
            noise_type=init_kwargs.get("noise_type", "ou"),
            noise_tau=init_kwargs.get("noise_tau", 10.0),
            noise_beta=init_kwargs.get("noise_beta", 1.0),
            use_et_symmetric=init_kwargs.get("use_et_symmetric", True),
        )
        model.load_state_dict(ckpt["model_state"])
        model.to(device)
        return model, family, init_kwargs

    # ----- Legacy fallback (v0.1 / v2.0 ad-hoc) ------------------------
    if "config" in ckpt and "model" in ckpt:
        from model.model_uid import UIDConfig, UIDModel
        cfg_dict = ckpt["config"]
        cfg = UIDConfig(**cfg_dict)
        model = UIDModel(cfg)
        model.load_state_dict(ckpt["model"])
        model.to(device)
        return model, "cid_full", {"legacy": True, "config": cfg_dict}

    raise RuntimeError(
        f"Could not interpret checkpoint at {ckpt_path}; expected "
        "v2.1 schema (with 'schema_version', 'model_family', "
        "'init_kwargs', 'model_state') or legacy schema (with "
        "'config' and 'model')."
    )


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint", type=str, required=True,
        help="Path to trained CID model checkpoint (v2.1 schema).",
    )
    parser.add_argument(
        "--baseline_checkpoint", type=str, default=None,
        help="Optional baseline checkpoint (negative control).",
    )
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument(
        "--max_seq_len", type=int, default=4096,
        help="Use long sequences for proper DFA.",
    )
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--n_sequences", type=int, default=10000)
    parser.add_argument(
        "--output_dir", type=str,
        default="./results/critical_exponents_v2.1",
    )
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load tokenizer and data.
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    from test_uid_on_minimind import PretrainJsonl
    dataset = PretrainJsonl(
        Path(args.data_path), tokenizer, max_length=args.max_seq_len,
    )
    dataloader = DataLoader(
        dataset, batch_size=args.batch_size, shuffle=False,
    )

    # Load CID model.
    print(f"Loading CID model from {args.checkpoint}")
    cid_model, cid_family, cid_init = _load_model_from_unified_ckpt(
        Path(args.checkpoint), device,
    )
    print(f"  model_family = {cid_family}")
    print(f"  init_kwargs  = {cid_init}")

    all_results: Dict[str, Any] = {}

    # ----- TEST 1: CID with noise injection OFF (emergence test) ------
    print("\n" + "=" * 60)
    print("TEST 1: CID with noise injection DISABLED (emergence test)")
    print("=" * 60)
    cid_emergence = run_critical_exponent_battery(
        model=cid_model,
        model_name="cid_full_noise_OFF",
        dataloader=dataloader,
        device=device,
        n_sequences=args.n_sequences,
        disable_noise=True,
    )
    all_results["cid_emergence"] = cid_emergence.to_dict()

    # ----- TEST 2: CID with noise injection ON (sanity check) ---------
    print("\n" + "=" * 60)
    print("TEST 2: CID with noise injection ENABLED (sanity check)")
    print("=" * 60)
    cid_with_noise = run_critical_exponent_battery(
        model=cid_model,
        model_name="cid_full_noise_ON",
        dataloader=dataloader,
        device=device,
        n_sequences=args.n_sequences,
        disable_noise=False,
    )
    all_results["cid_with_noise"] = cid_with_noise.to_dict()

    # ----- TEST 3 (optional): baseline negative control ---------------
    baseline_result = None
    if args.baseline_checkpoint is not None:
        print("\n" + "=" * 60)
        print("TEST 3: Baseline Transformer (negative control)")
        print("=" * 60)
        baseline_model, baseline_family, baseline_init = (
            _load_model_from_unified_ckpt(
                Path(args.baseline_checkpoint), device,
            )
        )
        print(f"  baseline family = {baseline_family}")
        print(f"  init_kwargs     = {baseline_init}")
        baseline_result = run_critical_exponent_battery(
            model=baseline_model,
            model_name="transformer_baseline",
            dataloader=dataloader,
            device=device,
            n_sequences=args.n_sequences,
            # Baseline has no noise injection to disable.
            disable_noise=True,
        )
        all_results["baseline"] = baseline_result.to_dict()

    # ----- Save raw results -------------------------------------------
    output_path = output_dir / "results.json"
    output_path.write_text(
        json.dumps(all_results, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Results saved to {output_path}")

    # ------------------------------------------------------------------
    # VERDICT: contrast noise-OFF vs noise-ON to detect circular echo
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("VERDICT: Is CID's emergence genuine?")
    print("=" * 60)

    b_off = float(cid_emergence.spectrum.beta_mean)
    h_off = float(cid_emergence.hurst.hurst_mean)
    b_on = float(cid_with_noise.spectrum.beta_mean)
    h_on = float(cid_with_noise.hurst.hurst_mean)

    db = abs(b_on - b_off)
    dh = abs(h_on - h_off)

    print(f"\n  {'':25s} {'noise OFF':>12s} {'noise ON':>12s} "
          f"{'|diff|':>10s}")
    print(f"  {'β (spectrum slope)':25s} {b_off:>12.3f} {b_on:>12.3f} "
          f"{db:>10.3f}")
    print(f"  {'H (Hurst exponent)':25s} {h_off:>12.3f} {h_on:>12.3f} "
          f"{dh:>10.3f}")
    print(f"  UID predicts β in [0.7, 1.3], H in [0.6, 0.8].")

    beta_in_range = 0.7 <= b_off <= 1.3
    hurst_in_range = 0.6 <= h_off <= 0.8

    # Heuristic: if noise OFF and noise ON give nearly identical
    # exponents, the noise-OFF measurement is suspect (the model may
    # still be retaining stale noise contributions). A genuine
    # emergence test should show non-trivial difference between the
    # two conditions, with the noise-OFF still falling in range.
    NOISE_DIFF_TOL = 0.05

    print()
    if beta_in_range and hurst_in_range:
        if db < NOISE_DIFF_TOL and dh < NOISE_DIFF_TOL:
            print(
                "  [warn] β and H in range, BUT noise-OFF and noise-ON "
                "are nearly identical "
                f"(|Δβ|={db:.3f}, |ΔH|={dh:.3f} < {NOISE_DIFF_TOL}). "
                "The noise-OFF measurement may be a residual echo of "
                "training-time noise rather than a true intrinsic "
                "signature. Re-run with longer eval or after additional "
                "noise-OFF fine-tuning before claiming emergence."
            )
            verdict = "ambiguous_residual_echo"
        else:
            print(
                "  [ok] EMERGENCE CONFIRMED: critical exponents are in "
                "range with noise injection OFF, AND they differ "
                "meaningfully from the noise-ON case (|Δβ|>= "
                f"{NOISE_DIFF_TOL} or |ΔH|>= {NOISE_DIFF_TOL})."
            )
            verdict = "emergence_confirmed"
    else:
        print(
            "  [fail] EMERGENCE NOT CONFIRMED: critical exponents do "
            "not match UID predictions with noise OFF. This suggests "
            "v0.1's 'verified' status was circular."
        )
        verdict = "emergence_not_confirmed"

    # Append verdict to results.
    all_results["verdict"] = {
        "beta_off": b_off,
        "beta_on": b_on,
        "hurst_off": h_off,
        "hurst_on": h_on,
        "beta_diff": db,
        "hurst_diff": dh,
        "beta_in_range": beta_in_range,
        "hurst_in_range": hurst_in_range,
        "noise_diff_tol": NOISE_DIFF_TOL,
        "verdict": verdict,
    }
    output_path.write_text(
        json.dumps(all_results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
