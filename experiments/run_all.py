# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * Fix checkpoint path assumption: run_scaling_law.py now writes
#     `{family}_{scale}_seed{seed}.pt` files; this script discovers
#     the first matching checkpoint instead of guessing a fixed name.
#   * Loudly warn (not silently skip) when downstream experiments
#     cannot find their input artifacts.
#   * v2.1 default output dirs.
"""
Run the complete v2.1 validation suite end-to-end.

Usage:
    python experiments/run_all.py \\
        --data_path ./data/wikitext-2/train.jsonl \\
        --tokenizer_path gpt2

This runs the full pipeline:
1. Scaling-law experiment (parameter efficiency) — also writes
   unified checkpoints under `<output_root>/scaling_law_v2.1/checkpoints/`.
2. Ablation suite (11-way component contribution).
3. Critical-exponent measurement (true emergence test).
4. Energy benchmark (real hardware).

Then writes a `run_all_summary.json` with the verdict on each step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional


def run_script(script_path: str, args: List[str], cwd: Path) -> int:
    """Run a Python script and stream output."""
    cmd = [sys.executable, script_path] + args
    print(f"\n>>> Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def find_checkpoint(
    ckpt_dir: Path,
    family: str,
    scale: str,
    seed_preference: List[int],
) -> Optional[Path]:
    """Locate a checkpoint produced by run_scaling_law.py (v2.1 schema).

    Pattern: `{family}_{scale}_seed{seed}.pt` — try preferred seeds first.
    """
    for seed in seed_preference:
        candidate = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
        if candidate.exists():
            return candidate
    # Fallback: any matching `{family}_{scale}_seed*.pt`.
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument("--output_root", type=str, default="./results")
    parser.add_argument("--scale", type=str, default="30M")
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
    )
    parser.add_argument("--skip_scaling", action="store_true")
    parser.add_argument("--skip_ablation", action="store_true")
    parser.add_argument("--skip_critical", action="store_true")
    parser.add_argument("--skip_energy", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    # v2.1 output sub-directories.
    scaling_dir = output_root / "scaling_law_v2.1"
    ablation_dir = output_root / "ablation_v2.1"
    critical_dir = output_root / "critical_exponents_v2.1"
    energy_dir = output_root / "energy_v2.1"
    ckpt_dir = scaling_dir / "checkpoints"

    summary = {
        "experiments_run": [],
        "experiments_skipped": [],
        "warnings": [],
    }

    # --------------------- 1. Scaling law ---------------------------
    if not args.skip_scaling:
        rc = run_script(
            "experiments/run_scaling_law.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scales", "10M", "30M", "100M",
                "--seeds", *[str(s) for s in args.seeds],
                "--output_dir", str(scaling_dir),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append({
            "name": "scaling_law", "exit_code": rc,
        })
    else:
        summary["experiments_skipped"].append("scaling_law")

    # --------------------- 2. Ablation ------------------------------
    if not args.skip_ablation:
        rc = run_script(
            "experiments/run_ablation.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scale", args.scale,
                "--seeds", *[str(s) for s in args.seeds],
                "--output_dir", str(ablation_dir),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append({
            "name": "ablation", "exit_code": rc,
        })
    else:
        summary["experiments_skipped"].append("ablation")

    # --------------------- 3. Critical exponents --------------------
    if not args.skip_critical:
        cid_ckpt = find_checkpoint(
            ckpt_dir, family="cid_full", scale=args.scale,
            seed_preference=args.seeds,
        )
        baseline_ckpt = find_checkpoint(
            ckpt_dir, family="transformer", scale=args.scale,
            seed_preference=args.seeds,
        )
        if cid_ckpt is None:
            msg = (
                f"[warn] No CID checkpoint matching "
                f"'cid_full_{args.scale}_seed*.pt' in {ckpt_dir}; "
                "skipping critical-exponents experiment. Did "
                "run_scaling_law.py finish for the requested scale?"
            )
            print("\n" + msg)
            summary["warnings"].append(msg)
            summary["experiments_skipped"].append("critical_exponents")
        else:
            cli_args = [
                "--checkpoint", str(cid_ckpt),
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--output_dir", str(critical_dir),
            ]
            if baseline_ckpt is not None:
                cli_args += [
                    "--baseline_checkpoint", str(baseline_ckpt),
                ]
            else:
                msg = (
                    "[warn] No Transformer baseline checkpoint found; "
                    "critical-exponents will run without negative control."
                )
                print("\n" + msg)
                summary["warnings"].append(msg)
            rc = run_script(
                "experiments/run_critical_exponents.py",
                cli_args,
                cwd=project_root,
            )
            summary["experiments_run"].append({
                "name": "critical_exponents",
                "exit_code": rc,
                "cid_checkpoint": str(cid_ckpt),
                "baseline_checkpoint": (
                    str(baseline_ckpt) if baseline_ckpt else None
                ),
            })
    else:
        summary["experiments_skipped"].append("critical_exponents")

    # --------------------- 4. Energy benchmark ----------------------
    if not args.skip_energy:
        if not ckpt_dir.exists() or not any(ckpt_dir.glob("*.pt")):
            msg = (
                f"[warn] No checkpoints found in {ckpt_dir}; "
                "skipping energy benchmark."
            )
            print("\n" + msg)
            summary["warnings"].append(msg)
            summary["experiments_skipped"].append("energy")
        else:
            rc = run_script(
                "experiments/run_energy_benchmark.py",
                [
                    "--checkpoint_dir", str(ckpt_dir),
                    "--scale", args.scale,
                    "--seeds", *[str(s) for s in args.seeds],
                    "--output_dir", str(energy_dir),
                ],
                cwd=project_root,
            )
            summary["experiments_run"].append({
                "name": "energy", "exit_code": rc,
            })
    else:
        summary["experiments_skipped"].append("energy")

    # --------------------- Final summary ----------------------------
    (output_root / "run_all_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("ALL EXPERIMENTS COMPLETE")
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    print(f"\nResults: {output_root}")


if __name__ == "__main__":
    main()
