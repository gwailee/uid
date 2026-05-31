# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-31 (final)
#   * Auto-detect vocab_size from tokenizer and pass to energy benchmark
#     (fixes device-side assert from token-id out of range).
#   * Per-scale batch_size auto-scaling to avoid OOM on big models.
#   * Set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True to reduce
#     fragmentation.
#   * Add --target_tokens_per_param to control scaling-law training budget
#     (default 200 for full convergence; Chinchilla-optimal is 20).
#   * Scaling-law defaults to a SAFE scale list; only adds bigger scales
#     when explicitly requested.
#   * Report exit codes clearly; do not let one failure mask others.
"""
Run the complete v2.1 validation suite end-to-end.

Usage (4090 / GPU optimized):
    python experiments/run_all.py \\
        --data_path data/minimind/pretrain.jsonl \\
        --tokenizer_path tokenizers/bert-base-chinese/tiansz/bert-base-chinese \\
        --scale 10M \\
        --seeds 42 43 44 \\
        --batch_size 64 \\
        --max_seq_len 512 \\
        --target_tokens_per_param 200 \\
        --output_root ./output/minimind_full

This runs the full pipeline:
1. Scaling-law experiment (parameter efficiency) — also writes
   unified checkpoints under `<output_root>/scaling_law_v2.1/checkpoints/`.
2. Ablation suite (11-way component contribution).
3. Critical-exponent measurement (true emergence test).
4. Energy benchmark (real hardware; requires NVIDIA GPU).

Then writes a `run_all_summary.json` with the verdict on each step.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Reduce CUDA fragmentation BEFORE importing torch.
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True"
)

import torch


# ----------------------------------------------------------------------
# Per-scale batch_size ceilings for a 24 GB GPU (RTX 4090) @ seq_len 512.
# 各规模在 24GB 显存下的安全 batch_size 上限（seq_len=512）。
# ----------------------------------------------------------------------
SAFE_BATCH_BY_SCALE: Dict[str, int] = {
    "10M": 64,
    "30M": 24,
    "100M": 8,
    "300M": 4,
    "1B": 1,
}


def safe_batch_size(scale: str, requested: int) -> int:
    """Clamp the requested batch_size to a scale-safe ceiling."""
    ceiling = SAFE_BATCH_BY_SCALE.get(scale, 8)
    return max(1, min(requested, ceiling))


def detect_vocab_size(tokenizer_path: str) -> int:
    """Read the real vocab size from the tokenizer.

    从 tokenizer 读取真实词表大小（修复能量测试 token 越界）。
    """
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(tokenizer_path)
        # vocab_size sometimes excludes added tokens; use len() to be safe.
        return int(max(tok.vocab_size, len(tok)))
    except Exception as e:
        print(f"[warn] Could not read vocab_size from tokenizer "
              f"({e}); defaulting to 21128 (bert-base-chinese).")
        return 21128


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
    """Locate a checkpoint produced by run_scaling_law.py (v2.1 schema)."""
    for seed in seed_preference:
        candidate = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
        if candidate.exists():
            return candidate
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument(
        "--output_root", "--output_dir",
        dest="output_root", type=str, default="./results",
        help="Output root directory (alias: --output_dir).",
    )
    parser.add_argument("--scale", type=str, default="10M")
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
    )
    parser.add_argument(
        "--batch_size", type=int, default=16,
        help="Base batch size; auto-clamped per scale to avoid OOM.",
    )
    parser.add_argument("--max_seq_len", type=int, default=512)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--target_tokens_per_param", type=float, default=200.0,
        help="Training budget for scaling law (tokens per parameter). "
             "Chinchilla-optimal is 20; use 200+ for full convergence on "
             "small datasets. Default 200.",
    )
    parser.add_argument(
        "--scaling_scales", type=str, nargs="+", default=None,
        help="Override scaling-law scales. Default: only --scale "
             "(safe). Provide explicitly e.g. --scaling_scales 10M 30M.",
    )
    parser.add_argument("--skip_scaling", action="store_true")
    parser.add_argument("--skip_ablation", action="store_true")
    parser.add_argument("--skip_critical", action="store_true")
    parser.add_argument("--skip_energy", action="store_true")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Device report.
    # ------------------------------------------------------------------
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"\n[device] ✓ GPU detected: {gpu_name} ({gpu_mem:.1f} GB)")
        has_gpu = True
    else:
        print("\n[device] ⚠ No CUDA GPU — running on CPU; energy skipped.")
        has_gpu = False

    # ------------------------------------------------------------------
    # Detect vocab_size ONCE (critical for energy benchmark token range).
    # ------------------------------------------------------------------
    vocab_size = detect_vocab_size(args.tokenizer_path)
    print(f"[info] Detected vocab_size = {vocab_size}")
    print(f"[info] base batch_size = {args.batch_size}, "
          f"max_seq_len = {args.max_seq_len}, scale = {args.scale}")
    print(f"[info] target_tokens_per_param = {args.target_tokens_per_param}")

    project_root = Path(__file__).parent.parent
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    scaling_dir = output_root / "scaling_law_v2.1"
    ablation_dir = output_root / "ablation_v2.1"
    critical_dir = output_root / "critical_exponents_v2.1"
    energy_dir = output_root / "energy_v2.1"
    ckpt_dir = scaling_dir / "checkpoints"

    summary = {
        "device": "cuda" if has_gpu else "cpu",
        "vocab_size": vocab_size,
        "base_batch_size": args.batch_size,
        "max_seq_len": args.max_seq_len,
        "scale": args.scale,
        "seeds": args.seeds,
        "target_tokens_per_param": args.target_tokens_per_param,
        "experiments_run": [],
        "experiments_skipped": [],
        "warnings": [],
    }

    # ---------------------------------------------------------------
    # Determine scaling scales (SAFE by default: only --scale).
    # 缩放规模（默认安全：只跑 --scale，需要更大请显式指定）。
    # ---------------------------------------------------------------
    if args.scaling_scales is not None:
        scaling_scales = args.scaling_scales
    else:
        # Default: just the requested scale (so critical/energy find it).
        scaling_scales = [args.scale]

    # Make sure --scale is included so downstream can find checkpoints.
    if args.scale not in scaling_scales:
        scaling_scales.append(args.scale)

    # --------------------- 1. Scaling law ---------------------------
    if not args.skip_scaling:
        # Use the SMALLEST safe batch among the requested scales so a
        # single run won't OOM on the biggest model.
        scaling_bs = min(
            safe_batch_size(s, args.batch_size) for s in scaling_scales
        )
        print(f"\n[scaling] scales={scaling_scales}, "
              f"batch_size={scaling_bs} (auto-clamped), "
              f"tokens_per_param={args.target_tokens_per_param}")
        rc = run_script(
            "experiments/run_scaling_law.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scales", *scaling_scales,
                "--seeds", *[str(s) for s in args.seeds],
                "--batch_size", str(scaling_bs),
                "--max_seq_len", str(args.max_seq_len),
                "--target_tokens_per_param", str(args.target_tokens_per_param),
                "--output_dir", str(scaling_dir),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append(
            {"name": "scaling_law", "exit_code": rc}
        )
        if rc != 0:
            summary["warnings"].append(
                f"[warn] scaling_law exited with code {rc}; "
                "downstream critical/energy may be skipped."
            )
    else:
        summary["experiments_skipped"].append("scaling_law")

    # --------------------- 2. Ablation ------------------------------
    if not args.skip_ablation:
        abl_bs = safe_batch_size(args.scale, args.batch_size)
        print(f"\n[ablation] scale={args.scale}, "
              f"batch_size={abl_bs} (auto-clamped), epochs={args.epochs}")
        rc = run_script(
            "experiments/run_ablation.py",
            [
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--scale", args.scale,
                "--epochs", str(args.epochs),
                "--lr", str(args.lr),
                "--seeds", *[str(s) for s in args.seeds],
                "--batch_size", str(abl_bs),
                "--max_seq_len", str(args.max_seq_len),
                "--output_dir", str(ablation_dir),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append(
            {"name": "ablation", "exit_code": rc}
        )
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
                f"[warn] No CID checkpoint 'cid_full_{args.scale}_seed*.pt' "
                f"in {ckpt_dir}; skipping critical-exponents. "
                "Did scaling_law finish for this scale?"
            )
            print("\n" + msg)
            summary["warnings"].append(msg)
            summary["experiments_skipped"].append("critical_exponents")
        else:
            # Critical exponents wants long sequences; use small batch.
            crit_bs = max(1, min(4, args.batch_size))
            print(f"\n[critical] batch_size={crit_bs}")
            cli_args = [
                "--checkpoint", str(cid_ckpt),
                "--data_path", args.data_path,
                "--tokenizer_path", args.tokenizer_path,
                "--max_seq_len", str(args.max_seq_len),
                "--batch_size", str(crit_bs),
                "--output_dir", str(critical_dir),
            ]
            if baseline_ckpt is not None:
                cli_args += ["--baseline_checkpoint", str(baseline_ckpt)]
            else:
                msg = (
                    "[warn] No Transformer baseline checkpoint found; "
                    "critical-exponents runs without negative control."
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
    if args.skip_energy:
        summary["experiments_skipped"].append("energy")
    elif not has_gpu:
        msg = "[warn] Energy benchmark requires GPU; skipping."
        print("\n" + msg)
        summary["warnings"].append(msg)
        summary["experiments_skipped"].append("energy")
    elif not ckpt_dir.exists() or not any(ckpt_dir.glob("*.pt")):
        msg = (
            f"[warn] No checkpoints in {ckpt_dir}; skipping energy."
        )
        print("\n" + msg)
        summary["warnings"].append(msg)
        summary["experiments_skipped"].append("energy")
    else:
        # Energy benchmark: small batch + correct vocab_size (KEY FIX).
        energy_bs = max(1, min(8, args.batch_size))
        print(f"\n[energy] batch_size={energy_bs}, vocab_size={vocab_size}")
        rc = run_script(
            "experiments/run_energy_benchmark.py",
            [
                "--checkpoint_dir", str(ckpt_dir),
                "--scale", args.scale,
                "--seeds", *[str(s) for s in args.seeds],
                "--batch_size", str(energy_bs),
                "--seq_len", str(args.max_seq_len),
                # KEY FIX: match the model's real vocab to avoid
                # token-id out-of-range device-side asserts.
                "--vocab_size", str(vocab_size),
                "--output_dir", str(energy_dir),
            ],
            cwd=project_root,
        )
        summary["experiments_run"].append(
            {"name": "energy", "exit_code": rc}
        )

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
