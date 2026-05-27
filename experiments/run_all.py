# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
Run the complete v2.0 validation suite end-to-end.

Usage:
    python experiments/run_all.py \\
        --data_path ./data/wikitext-2/train.jsonl \\
        --tokenizer_path gpt2

This runs the full pipeline:
1. Scaling-law experiment (parameter efficiency)
2. Ablation suite (component contribution)
3. Critical-exponent measurement (true emergence test)
4. Energy benchmark (real hardware)

Then generates a final report.json with the verdict on each UID claim.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_script(script_path: str, args: list[str], cwd: Path) -> int:
    """Run a Python script and stream output."""
    cmd = [sys.executable, script_path] + args
    print(f"\n>>> Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument("--output_root", type=str, default="./results")
    parser.add_argument("--scale", type=str, default="30M")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--skip_scaling", action="store_true")
    parser.add_argument("--skip_ablation", action="store_true")
    parser.add_argument("--skip_critical", action="store_true")
    parser.add_argument("--skip_energy", action="store_true")
    args = parser.parse_args()
    
    project_root = Path(__file__).parent.parent
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    
    summary = {"experiments_run": [], "experiments_skipped": []}
    
    # 1. Scaling law
    if not args.skip_scaling:
        rc = run_script(
            "experiments/run_scaling_law.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scales", "10M", "30M", "100M",
                "--seeds", *[str(s) for s in args.seeds],
                "--output_dir", str(output_root / "scaling_law_v1.0"),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append({
            "name": "scaling_law", "exit_code": rc
        })
    else:
        summary["experiments_skipped"].append("scaling_law")
    
    # 2. Ablation
    if not args.skip_ablation:
        rc = run_script(
            "experiments/run_ablation.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scale", args.scale,
                "--seeds", *[str(s) for s in args.seeds],
                "--output_dir", str(output_root / "ablation_v1.0"),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append({
            "name": "ablation", "exit_code": rc
        })
    else:
        summary["experiments_skipped"].append("ablation")
    
    # 3. Critical exponents (requires trained model)
    if not args.skip_critical:
        ckpt = output_root / "scaling_law_v1.0" / "checkpoints" / \
            f"cid_full_{args.scale}.pt"
        if not ckpt.exists():
            print(f"\n[warn] {ckpt} not found, skipping critical-exponents")
            summary["experiments_skipped"].append("critical_exponents")
        else:
            rc = run_script(
                "experiments/run_critical_exponents.py",
                [
                    "--checkpoint", str(ckpt),
                    "--data_path", args.data_path,
                    "--tokenizer_path", args.tokenizer_path,
                    "--output_dir", str(output_root / "critical_exponents_v1.0"),
                ],
                cwd=project_root,
            )
            summary["experiments_run"].append({
                "name": "critical_exponents", "exit_code": rc
            })
    else:
        summary["experiments_skipped"].append("critical_exponents")
    
    # 4. Energy benchmark
    if not args.skip_energy:
        ckpt_dir = output_root / "scaling_law_v1.0" / "checkpoints"
        if not ckpt_dir.exists():
            print(f"\n[warn] {ckpt_dir} not found, skipping energy benchmark")
            summary["experiments_skipped"].append("energy")
        else:
            rc = run_script(
                "experiments/run_energy_benchmark.py",
                [
                    "--checkpoint_dir", str(ckpt_dir),
                    "--output_dir", str(output_root / "energy_v1.0"),
                ],
                cwd=project_root,
            )
            summary["experiments_run"].append({
                "name": "energy", "exit_code": rc
            })
    else:
        summary["experiments_skipped"].append("energy")
    
    # Final summary
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
