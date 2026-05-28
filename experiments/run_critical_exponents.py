# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28 (v2.1 batch 3)
#   * Add eta (Fisher anisotropy, Theory §6.1 / README prediction 4)
#     to the verdict block. eta is now contrasted noise-OFF vs noise-ON
#     in the same spirit as beta and Hurst.
#   * The "emergence_confirmed" verdict now requires beta, H AND eta
#     to all pass — but if the eta estimate is rank-deficient
#     (seq_len < hidden_size), eta is ABSTAINED (treated as
#     uninformative) rather than counted as a pass.
#   * Emit a clear data-quality note when the user accidentally ran
#     with max_seq_len < hidden_size, which is the only way to get
#     a rank-deficient eta.
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
4. Measures Hurst exponent (DFA), spectrum slope beta, avalanche tau,
   AND Fisher anisotropy eta (Theory §6.1 / README prediction 4).
5. Uses Clauset-Shalizi-Newman MLE for power-law fitting.
6. Also runs the SAME measurement with noise injection ON, then
   contrasts the two to detect circular-measurement artifacts.
7. Reports whether emergence is genuine.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import torch
from torch.utils.data import DataLoader

from uid_theory.verification.critical_exponents import (
    EtaResult,
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
# Verdict helpers
# ======================================================================


def _fmt_eta(e: Optional[EtaResult]) -> str:
    if e is None:
        return f"{'N/A':>12s}"
    return f"{e.eta_mean:>12.3f}"


def _eta_verdict(
    eta_off: Optional[EtaResult],
    eta_threshold: float = 0.5,
) -> str:
    """Classify the eta result into one of three verdicts.

    Returns one of:
        "pass"             — eta_off > threshold and not rank-deficient
        "fail"             — eta_off <= threshold
        "abstain_rd"       — rank-deficient (seq_len < hidden_size)
        "abstain_missing"  — eta not computed
    """
    if eta_off is None:
        return "abstain_missing"
    if eta_off.rank_deficient:
        return "abstain_rd"
    return "pass" if eta_off.eta_mean > eta_threshold else "fail"


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
        help="Use long sequences for proper DFA AND non-rank-deficient eta.",
    )
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--n_sequences", type=int, default=10000)
    parser.add_argument(
        "--eta_threshold", type=float, default=0.5,
        help="Theory §6.1 prediction threshold (default 0.5).",
    )
    parser.add_argument(
        "--eta_max_samples", type=int, default=256,
        help="Cap on the number of sequences used for eta estimation.",
    )
    parser.add_argument(
        "--noise_diff_tol", type=float, default=0.05,
        help="Minimum |noise_ON - noise_OFF| difference required to "
             "trust the noise-OFF emergence signature.",
    )
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
        include_eta=True,
        eta_threshold=args.eta_threshold,
        eta_max_samples=args.eta_max_samples,
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
        include_eta=True,
        eta_threshold=args.eta_threshold,
        eta_max_samples=args.eta_max_samples,
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
            include_eta=True,
            eta_threshold=args.eta_threshold,
            eta_max_samples=args.eta_max_samples,
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

    # ----- Scalar extracts -------------------------------------------
    b_off = float(cid_emergence.spectrum.beta_mean)
    h_off = float(cid_emergence.hurst.hurst_mean)
    b_on = float(cid_with_noise.spectrum.beta_mean)
    h_on = float(cid_with_noise.hurst.hurst_mean)

    eta_off_obj = cid_emergence.eta
    eta_on_obj = cid_with_noise.eta
    e_off = (
        float(eta_off_obj.eta_mean)
        if eta_off_obj is not None else float("nan")
    )
    e_on = (
        float(eta_on_obj.eta_mean)
        if eta_on_obj is not None else float("nan")
    )

    db = abs(b_on - b_off)
    dh = abs(h_on - h_off)
    de = (
        abs(e_on - e_off)
        if eta_off_obj is not None and eta_on_obj is not None
        else float("nan")
    )

    # ----- Print the contrast table ----------------------------------
    print(
        f"\n  {'':30s} {'noise OFF':>12s} {'noise ON':>12s} "
        f"{'|diff|':>10s}"
    )
    print(
        f"  {'beta (spectrum slope)':30s} {b_off:>12.3f} {b_on:>12.3f} "
        f"{db:>10.3f}"
    )
    print(
        f"  {'H (Hurst exponent)':30s} {h_off:>12.3f} {h_on:>12.3f} "
        f"{dh:>10.3f}"
    )
    print(
        f"  {'eta (Fisher anisotropy)':30s} "
        f"{_fmt_eta(eta_off_obj)} {_fmt_eta(eta_on_obj)} "
        f"{(de if de == de else float('nan')):>10.3f}"
    )
    print()
    print(
        f"  UID predicts: beta in [0.7, 1.3], H in [0.6, 0.8], "
        f"eta > {args.eta_threshold}."
    )

    # ----- Per-prediction passes -------------------------------------
    beta_in_range = 0.7 <= b_off <= 1.3
    hurst_in_range = 0.6 <= h_off <= 0.8
    eta_state = _eta_verdict(eta_off_obj, args.eta_threshold)

    # ----- Data-quality flags ----------------------------------------
    rank_deficient = bool(
        eta_off_obj is not None and eta_off_obj.rank_deficient
    )
    if rank_deficient:
        # Make this LOUD because it usually means the user
        # accidentally ran with max_seq_len < hidden_size.
        print(
            "\n  [data-quality WARNING] eta was estimated on a "
            "rank-deficient covariance (seq_len < hidden_size).\n"
            "  eta values from this run are biased upward toward 1.0 "
            "and should NOT be counted as a pass.\n"
            f"  Re-run with --max_seq_len >= hidden_size "
            f"(currently --max_seq_len={args.max_seq_len}, "
            f"hidden_size={eta_off_obj.hidden_size})."
        )

    # ----- Combined verdict ------------------------------------------
    NOISE_DIFF_TOL = float(args.noise_diff_tol)

    # When eta is rank-deficient or missing, we ABSTAIN — i.e. require
    # beta and H to carry the verdict alone (and do not count eta as
    # a free pass).
    eta_passes = eta_state == "pass"
    eta_abstains = eta_state in ("abstain_rd", "abstain_missing")

    print()
    if not (beta_in_range and hurst_in_range):
        print(
            "  [fail] EMERGENCE NOT CONFIRMED: beta and/or H out of "
            "the UID-predicted ranges with noise OFF. "
            "v0.1's 'verified' claim was likely circular."
        )
        verdict = "emergence_not_confirmed"
    elif (not eta_passes) and (not eta_abstains):
        print(
            f"  [fail] EMERGENCE NOT CONFIRMED: eta = {e_off:.3f} <= "
            f"threshold {args.eta_threshold:.2f}. "
            "README prediction 4 (Theory §6.1) is FALSIFIED at this "
            "scale; the trained representation is not anisotropic enough."
        )
        verdict = "emergence_not_confirmed_eta"
    elif db < NOISE_DIFF_TOL and dh < NOISE_DIFF_TOL:
        print(
            "  [warn] beta and H in range, BUT noise-OFF and noise-ON "
            "are nearly identical "
            f"(|d_beta|={db:.3f}, |d_H|={dh:.3f} < {NOISE_DIFF_TOL}). "
            "The noise-OFF measurement may be a residual echo of "
            "training-time noise rather than a true intrinsic "
            "signature. Re-run with longer eval or after additional "
            "noise-OFF fine-tuning before claiming emergence."
        )
        verdict = "ambiguous_residual_echo"
    else:
        if eta_abstains:
            extra = (
                " (eta ABSTAINED: "
                + ("rank-deficient" if eta_state == "abstain_rd"
                   else "not measured")
                + ")"
            )
        else:
            extra = f" (eta = {e_off:.3f} > {args.eta_threshold:.2f})"
        print(
            "  [ok] EMERGENCE CONFIRMED: critical exponents are in "
            "range with noise injection OFF, AND they differ "
            f"meaningfully from the noise-ON case "
            f"(|d_beta|>= {NOISE_DIFF_TOL} or |d_H|>= {NOISE_DIFF_TOL})."
            + extra
        )
        verdict = (
            "emergence_confirmed"
            if not eta_abstains
            else "emergence_confirmed_eta_abstained"
        )

    # ----- Append verdict to results ---------------------------------
    all_results["verdict"] = {
        "beta_off": b_off,
        "beta_on": b_on,
        "hurst_off": h_off,
        "hurst_on": h_on,
        "eta_off": e_off,
        "eta_on": e_on,
        "beta_diff": db,
        "hurst_diff": dh,
        "eta_diff": de,
        "beta_in_range": beta_in_range,
        "hurst_in_range": hurst_in_range,
        "eta_state": eta_state,
        "eta_threshold": args.eta_threshold,
        "eta_rank_deficient": rank_deficient,
        "noise_diff_tol": NOISE_DIFF_TOL,
        "verdict": verdict,
    }
    output_path.write_text(
        json.dumps(all_results, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
