# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-06-01 (resumable)
#   * --resume: skip families whose results already exist in results.json,
#     and skip the whole stage if all requested families are present.
#     Results are MERGED (not overwritten), so an interrupted run continues
#     from where it stopped (per-family granularity).
# UPDATE: 2026-05-28 (v2.1 batch 4)
#   * Print all new EnergyMeasurement fields; raw + above-idle ratios;
#     --mode {prefill,decode}; reproducibility metadata block.
"""
Run real hardware energy benchmark (v2.1 unified checkpoint schema,
energy_meter v2.1 batch 4) — RESUMABLE.

Usage:
    python experiments/run_energy_benchmark.py \\
        --families cid_full transformer transformer_plus_all_tricks \\
        --checkpoint_dir ./results/scaling_law_v2.1/checkpoints \\
        --scale 100M \\
        --seeds 42 \\
        --mode decode --new_tokens_per_decode 64 \\
        --batch_size 16 --seq_len 1024 \\
        --output_dir ./results/energy_v2.1 \\
        --resume

RESUME BEHAVIOR (--resume):
  * Families already present in <output_dir>/results.json are skipped.
  * If ALL requested families are present, the stage is skipped entirely.
  * New family results are merged into the existing results.json.
  * Delete results.json (or output_dir) to force a full re-run.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from uid_theory.verification.energy_meter import (
    EnergyMeasurement,
    measure_inference_energy,
)


# ======================================================================
# Unified v2.1 checkpoint loader
# ======================================================================


def _load_model_from_unified_ckpt(ckpt_path: Path, device: str):
    """Rebuild a model from the v2.1 unified checkpoint schema."""
    ckpt = torch.load(ckpt_path, map_location=device)

    if ckpt.get("schema_version") == "v2.1":
        init_kwargs = ckpt["init_kwargs"]
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
        return model, ckpt["model_family"]

    # Legacy fallback.
    if "config" in ckpt and "model" in ckpt:
        name = ckpt_path.stem
        if name.startswith("cid"):
            from model.model_uid import UIDConfig, UIDModel
            cfg = UIDConfig(**ckpt["config"])
            model = UIDModel(cfg)
        elif name.startswith("transformer_plus"):
            from model.known_tricks_baseline import (
                TransformerPlusTricksLM,
            )
            model = TransformerPlusTricksLM(**ckpt["config"])
        else:
            from model.modern_transformer import ModernTransformerLM
            model = ModernTransformerLM(**ckpt["config"])
        model.load_state_dict(ckpt["model"])
        model.to(device)
        return model, name.split("_seed")[0]

    raise RuntimeError(
        f"Could not interpret checkpoint at {ckpt_path}; expected "
        "v2.1 unified schema or legacy {'config', 'model'} schema."
    )


def _find_checkpoint(
    ckpt_dir: Path,
    family: str,
    scale: str,
    seed_preference: List[int],
) -> Optional[Path]:
    """Locate `{family}_{scale}_seed{seed}.pt` preferring earlier seeds."""
    for seed in seed_preference:
        candidate = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
        if candidate.exists():
            return candidate
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    if matches:
        return matches[0]
    legacy = ckpt_dir / f"{family}.pt"
    return legacy if legacy.exists() else None


# ======================================================================
# Resume helpers
# ======================================================================


def _load_existing_output(output_path: Path) -> Dict[str, Any]:
    """Load an existing results.json output blob (or an empty skeleton)."""
    if not output_path.exists():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[resume] WARNING: could not parse {output_path} ({e}); "
              f"starting fresh.")
        return {}


# ======================================================================
# Pretty printing
# ======================================================================


def _print_measurement(em: EnergyMeasurement) -> None:
    """Print a v2.1 EnergyMeasurement in a human-readable layout."""
    print()
    print(f"  --- {em.model_name} ({em.mode}) ---")
    print(f"  Sampler            : {em.sampler}")
    print(f"  GPU                : {em.gpu_name} ({em.device})")
    print(
        f"  Sampling rate      : {em.sample_rate_hz:.1f} Hz "
        f"({em.n_samples} samples in {em.wall_clock_seconds:.3f} s)"
    )
    print(
        f"  Warmup / measure   : {em.n_warmup} / {em.n_measure} "
        f"(batch={em.batch_size}, seq_len={em.seq_len}, "
        f"new_tokens={em.new_tokens_per_decode})"
    )
    print(
        f"  Idle baseline      : {em.idle_power_watts:>7.2f} W "
        f"({em.idle_window_seconds:.2f} s window)"
    )
    print(
        f"  Avg power (work)   : {em.avg_power_watts:>7.2f} W "
        f"  (peak {em.max_power_watts:>7.2f} W)"
    )
    print(f"  Above-idle power   : {em.power_above_idle_watts:>7.2f} W")
    print(
        f"  Total energy       : {em.total_energy_joules:>10.4f} J  "
        f"(above idle: {em.energy_above_idle_joules:>10.4f} J)"
    )
    print(f"  Total tokens       : {em.total_tokens:,}")
    print(
        f"  Energy / token     : {em.energy_per_token_joules*1e3:>10.4f} mJ"
        f"  (above idle: "
        f"{em.energy_per_token_above_idle_joules*1e3:>10.4f} mJ)"
    )
    if em.notes:
        print("  Notes:")
        for n in em.notes:
            print(f"    - {n}")


def _print_comparison(results: Dict[str, Dict[str, Any]]) -> None:
    """Print energy-comparison table; warn loudly on idle-dominated runs."""
    if "transformer" not in results:
        print(
            "\n[warn] No 'transformer' baseline in results; skipping "
            "energy comparison (need a key named exactly 'transformer')."
        )
        return

    baseline = results["transformer"]
    baseline_eptj = baseline["energy_per_token_joules"]
    baseline_eptj_above = baseline["energy_per_token_above_idle_joules"]

    print()
    print("=" * 70)
    print("Energy Comparison (lower energy per token is better)")
    print("=" * 70)
    print(
        f"\nBaseline (transformer):\n"
        f"  raw          = {baseline_eptj*1e3:.4f} mJ/token\n"
        f"  above-idle   = {baseline_eptj_above*1e3:.4f} mJ/token"
    )

    if baseline_eptj > 0:
        idle_frac = 1.0 - (baseline_eptj_above / baseline_eptj)
        if idle_frac > 0.30:
            print(
                f"  [warn] idle floor accounts for {idle_frac*100:.1f}% "
                "of baseline total energy. Prefer the ABOVE-IDLE column "
                "for cross-model comparisons."
            )

    print()
    print(
        f"  {'Family':35s}  {'raw ratio':>10s}  "
        f"{'above-idle ratio':>16s}  {'verdict':>16s}"
    )
    print("  " + "-" * 80)
    for name, r in results.items():
        if name == "transformer":
            continue
        eptj = r["energy_per_token_joules"]
        eptj_above = r["energy_per_token_above_idle_joules"]
        if eptj <= 0 or eptj_above <= 0:
            print(
                f"  {name:35s}  {'n/a':>10s}  {'n/a':>16s}  "
                f"{'invalid':>16s}"
            )
            continue
        raw_ratio = baseline_eptj / eptj
        above_ratio = baseline_eptj_above / eptj_above

        if name == "cid_full":
            verdict = (
                "PASS A4 (>=3x)" if above_ratio >= 3.0
                else f"FAIL A4 ({above_ratio:.2f}x)"
            )
        else:
            verdict = (
                f"{above_ratio:.2f}x faster"
                if above_ratio >= 1.0
                else f"{1.0/above_ratio:.2f}x slower"
            )

        print(
            f"  {name:35s}  {raw_ratio:>8.2f}x  "
            f"{above_ratio:>14.2f}x  {verdict:>16s}"
        )

    print()
    print(
        "Note: README prediction 5 (>= 3x energy efficiency) is "
        "evaluated against the above-idle ratio."
    )


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families", nargs="+",
        default=[
            "cid_full", "transformer", "transformer_plus_all_tricks",
        ],
        help="Model families to benchmark.",
    )
    parser.add_argument(
        "--checkpoint_dir", type=str, required=True,
        help="Directory containing v2.1 unified checkpoints.",
    )
    parser.add_argument(
        "--scale", type=str, default="100M",
        help="Which scale to load (must match scaling_law output).",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
        help="Seed preference order when picking a checkpoint.",
    )
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--seq_len", type=int, default=1024)
    parser.add_argument(
        "--vocab_size", type=int, default=50257,
        help="Used to generate random input tokens.",
    )
    parser.add_argument("--n_warmup", type=int, default=50)
    parser.add_argument("--n_measure", type=int, default=500)
    parser.add_argument(
        "--mode", type=str, default="prefill",
        choices=["prefill", "decode"],
        help="prefill: one full forward per iteration; "
             "decode: token-by-token greedy decode.",
    )
    parser.add_argument(
        "--new_tokens_per_decode", type=int, default=32,
        help="New tokens per decode iteration (ignored in prefill mode).",
    )
    parser.add_argument(
        "--sample_rate_hz", type=float, default=25.0,
        help="Power sampling rate; pynvml ~100 Hz, nvidia-smi ~10 Hz.",
    )
    parser.add_argument(
        "--idle_window_seconds", type=float, default=2.0,
        help="Duration of the idle baseline measurement window.",
    )
    parser.add_argument(
        "--sampler_preference", type=str, default="auto",
        choices=["auto", "pynvml", "nvidia_smi"],
        help="Force a specific power sampler backend.",
    )
    parser.add_argument(
        "--output_dir", type=str, default="./results/energy_v2.1",
    )
    # ---- Resume support (for run_all.py end-to-end resume) ----
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip families already in results.json; merge new results. "
             "Skip the whole stage if all requested families are present. "
             "Delete results.json (or output_dir) to force a re-run.",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Energy benchmark requires NVIDIA GPU; "
            "torch.cuda.is_available() == False."
        )
    device = "cuda"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "results.json"

    # ---- RESUME: load existing results & decide what to skip ----
    existing_blob = _load_existing_output(output_path) if args.resume else {}
    existing_results: Dict[str, Dict[str, Any]] = (
        existing_blob.get("results", {}) if existing_blob else {}
    )
    if args.resume and existing_results:
        present = set(existing_results.keys())
        requested = set(args.families)
        if requested.issubset(present):
            print(f"[resume] All requested families already in "
                  f"{output_path.name} ({sorted(present)}); "
                  f"nothing to do. Delete it to re-run.")
            # Still print the comparison from existing results.
            _print_comparison(existing_results)
            return
        else:
            todo = requested - present
            print(f"[resume] {len(present)} families already done "
                  f"({sorted(present)}); will run remaining: {sorted(todo)}")

    # Generate input batch.
    input_ids = torch.randint(
        0, args.vocab_size,
        (args.batch_size, args.seq_len),
        device=device,
    )

    ckpt_dir = Path(args.checkpoint_dir)
    # Start from existing results (merge), or empty.
    results: Dict[str, Dict[str, Any]] = dict(existing_results)

    print(f"\nEnergy benchmark v2.1 batch 4 (resume={args.resume})")
    print(f"  mode          = {args.mode}")
    if args.mode == "decode":
        print(f"  new_tokens    = {args.new_tokens_per_decode} per iter")
    print(f"  sampler_pref  = {args.sampler_preference}")
    print(f"  sample_rate   = {args.sample_rate_hz} Hz")
    print(f"  idle_window   = {args.idle_window_seconds} s")
    print(f"  batch x seq   = {args.batch_size} x {args.seq_len}")
    print(f"  warmup/measur = {args.n_warmup} / {args.n_measure}")

    for name in args.families:
        # ---- RESUME: skip families already measured ----
        if args.resume and name in results:
            print(f"\n[resume] skip family '{name}' — already in results.json")
            continue

        ckpt_path = _find_checkpoint(
            ckpt_dir, family=name, scale=args.scale,
            seed_preference=args.seeds,
        )
        if ckpt_path is None:
            print(
                f"\n[warn] No checkpoint for family='{name}' scale="
                f"'{args.scale}' under {ckpt_dir}; skipping"
            )
            continue

        print(f"\n{'=' * 70}")
        print(f"Benchmarking: {name}  ({ckpt_path.name})")
        print("=" * 70)

        model, loaded_family = _load_model_from_unified_ckpt(
            ckpt_path, device,
        )

        em = measure_inference_energy(
            model=model,
            model_name=name,
            input_ids=input_ids,
            n_warmup=args.n_warmup,
            n_measure=args.n_measure,
            device=device,
            mode=args.mode,
            new_tokens_per_decode=args.new_tokens_per_decode,
            sample_rate_hz=args.sample_rate_hz,
            idle_window_seconds=args.idle_window_seconds,
            sampler_preference=args.sampler_preference,
        )

        _print_measurement(em)

        results[name] = {
            **em.to_dict(),
            "checkpoint": str(ckpt_path),
            "loaded_family": loaded_family,
        }

        # ---- INCREMENTAL SAVE after each family (resume-safe) ----
        output = {
            "schema_version": "energy_v2.1_batch4",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "metadata": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "torch_version": torch.__version__,
                "cuda_version": (
                    torch.version.cuda if torch.cuda.is_available() else None
                ),
                "device_name": torch.cuda.get_device_name(0)
                if torch.cuda.is_available() else None,
                "cli_args": vars(args),
            },
            "results": results,
        }
        output_path.write_text(
            json.dumps(output, indent=2), encoding="utf-8"
        )
        print(f"  [save] results.json updated "
              f"({len(results)} families so far)")

        del model
        torch.cuda.empty_cache()

    # ----- Final save (ensures metadata present even if loop empty) ----
    output = {
        "schema_version": "energy_v2.1_batch4",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "torch_version": torch.__version__,
            "cuda_version": (
                torch.version.cuda if torch.cuda.is_available() else None
            ),
            "device_name": torch.cuda.get_device_name(0)
            if torch.cuda.is_available() else None,
            "cli_args": vars(args),
        },
        "results": results,
    }
    output_path.write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Results saved to {output_path}")

    # ----- Cross-model comparison ------------------------------------
    _print_comparison(results)


if __name__ == "__main__":
    main()
