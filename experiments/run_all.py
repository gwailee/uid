# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-06-21b (critical-stage guards)
#   * Critical-exponents stage no longer uses run_critical_exponents.py's
#     default --n_sequences=10000, which collects a multi-GB hidden-state
#     tensor and runs single-thread DFA -> OOM/swap/"hang" on small boxes.
#     New CLI --critical_n_sequences (default 2000) is passed through.
#   * Critical stage now reads hidden_size from the CID checkpoint and picks
#     a seq_len >= hidden_size where possible (eta is rank-deficient and
#     biased toward 1.0 when seq_len < hidden_size); it warns loudly when the
#     trained positional limit is below hidden_size so eta cannot be valid.
# UPDATE: 2026-06-21 (v2.2 — wire iso-performance energy through run_all)
#   * Energy stage passes the NEW run_energy_benchmark.py v2.2 flags:
#       --families cid_full transformer transformer_plus_tricks
#       --mode decode --new_tokens_per_decode <N>
#       --scaling_law_json <scaling_dir>/results.json   (when present)
#       --target_ppl <--energy_target_ppl>              (when provided)
#     so the DECISIVE iso-performance C13 column can actually run.
#   * Energy stage treats an OLD-schema energy/results.json
#     (schema_version != energy_v2.2_*) as STALE and re-runs it.
#   * CLI: --energy_target_ppl, --energy_new_tokens.
# UPDATE: 2026-06-02 (resumable, all 4 stages pass --resume)
#   * ALL four sub-stages receive --resume so results.json / sidecars are
#     never overwritten on restart.
#   * Each completed stage drops a `.done_<stage>` marker.
#   * --force / --force_stage / --fresh to override resume.
"""
Run the complete v2.1/v2.2 validation suite end-to-end — RESUMABLE.

Usage (4090 / GPU optimized):
    python experiments/run_all.py \\
        --data_path data/minimind/pretrain.jsonl \\
        --tokenizer_path tokenizers/bert-base-chinese/tiansz/bert-base-chinese \\
        --scale 10M --seeds 42 43 44 \\
        --batch_size 64 --max_seq_len 512 \\
        --target_tokens_per_param 200 \\
        --output_root ./output/minimind_full

Multi-scale (to test the T2 5-10x parameter-efficiency claim) — note you
MUST force the scaling+energy stages when adding scales, because the
.done_scaling marker would otherwise short-circuit the new scales:
    python experiments/run_all.py ... \\
        --scale 10M --scaling_scales 10M 30M 100M \\
        --energy_target_ppl 31.0 \\
        --force_stage scaling energy

RESUME: re-run the SAME command to continue. Delete output_root (or use
--fresh) for a clean start; --force / --force_stage to override markers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

# Reduce CUDA fragmentation BEFORE importing torch.
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True"
)

import torch


# ----------------------------------------------------------------------
# Per-scale batch_size ceilings.
# 4090 24GB defaults. For scaling-law iso-FLOP comparability across
# 10M..1B on A100 80GB, set them all equal (e.g. all 8).
# ----------------------------------------------------------------------
SAFE_BATCH_BY_SCALE: Dict[str, int] = {
    "10M": 64,
    "30M": 24,
    "100M": 8,
    "300M": 4,
    "1B": 1,
}

# Fallback hidden_size per scale (used if the checkpoint lacks the field).
HIDDEN_BY_SCALE: Dict[str, int] = {
    "10M": 256,
    "30M": 384,
    "100M": 512,
    "300M": 768,
    "1B": 1024,
}

STAGE_SCALING = "scaling_law"
STAGE_ABLATION = "ablation"
STAGE_CRITICAL = "critical"
STAGE_ENERGY = "energy"
ALL_STAGES = [STAGE_SCALING, STAGE_ABLATION, STAGE_CRITICAL, STAGE_ENERGY]

EXPECTED_ABLATION_VARIANTS = 11
SCALING_FAMILIES = ["cid_full", "transformer", "transformer_plus_tricks"]

# The energy results.json must carry this schema prefix to be considered
# up-to-date; anything else (e.g. the old energy_v2.1_batch4) is STALE.
ENERGY_SCHEMA_PREFIX = "energy_v2.2"


def safe_batch_size(scale: str, requested: int) -> int:
    """Clamp the requested batch_size to a scale-safe ceiling."""
    ceiling = SAFE_BATCH_BY_SCALE.get(scale, 8)
    return max(1, min(requested, ceiling))


def detect_vocab_size(tokenizer_path: str) -> int:
    """Read the real vocab size from the tokenizer."""
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(tokenizer_path)
        return int(max(tok.vocab_size, len(tok)))
    except Exception as e:
        print(f"[warn] Could not read vocab_size from tokenizer "
              f"({e}); defaulting to 21128 (bert-base-chinese).")
        return 21128


def run_script(script_path: str, args: List[str], cwd: Path) -> int:
    """Run a Python script and stream its output."""
    cmd = [sys.executable, script_path] + args
    print(f"\n>>> Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


def find_checkpoint(
    ckpt_dir: Path, family: str, scale: str, seed_preference: List[int],
) -> Optional[Path]:
    """Locate a checkpoint produced by run_scaling_law.py (v2.1 schema)."""
    for seed in seed_preference:
        candidate = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
        if candidate.exists():
            return candidate
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    return matches[0] if matches else None


def read_hidden_size(ckpt_path: Optional[Path], scale: str) -> Optional[int]:
    """Best-effort: read hidden_size from a v2.1 checkpoint so we can pick a
    non-rank-deficient seq_len for the eta estimate. Falls back to the
    per-scale table when the checkpoint does not carry the field."""
    if ckpt_path is not None and ckpt_path.exists():
        try:
            blob = torch.load(ckpt_path, map_location="cpu")
            ik = blob.get("init_kwargs", {}) or {}
            for k in ("hidden_size", "d_model", "n_embd", "hidden"):
                if k in ik and ik[k]:
                    return int(ik[k])
            cfg = blob.get("config", {}) or {}
            for k in ("hidden_size", "d_model", "n_embd", "hidden"):
                if k in cfg and cfg[k]:
                    return int(cfg[k])
        except Exception:
            pass
    return HIDDEN_BY_SCALE.get(scale)


# ======================================================================
# Resume helpers
# ======================================================================

def _done_marker(output_root: Path, stage: str) -> Path:
    return output_root / f".done_{stage}"


def _mark_done(output_root: Path, stage: str, info: Dict) -> None:
    marker = _done_marker(output_root, stage)
    marker.write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"[resume] stage '{stage}' marked DONE -> {marker.name}")


def _is_done(output_root: Path, stage: str) -> bool:
    return _done_marker(output_root, stage).exists()


def _load_results(results_file: Path) -> List[Dict]:
    if not results_file.exists():
        return []
    try:
        return json.loads(results_file.read_text(encoding="utf-8"))
    except Exception:
        return []


def _ablation_completed_pairs(results_file: Path) -> Set[tuple]:
    pairs: Set[tuple] = set()
    for rec in _load_results(results_file):
        name = rec.get("ablation_name")
        seed = rec.get("seed")
        if name is not None and seed is not None:
            pairs.add((name, int(seed)))
    return pairs


def _ablation_is_complete(results_file: Path, seeds: List[int]) -> bool:
    pairs = _ablation_completed_pairs(results_file)
    if not pairs:
        return False
    variants = {name for (name, _s) in pairs}
    seeds_seen = {s for (_n, s) in pairs}
    return (
        len(variants) >= EXPECTED_ABLATION_VARIANTS
        and set(seeds).issubset(seeds_seen)
        and len(pairs) >= EXPECTED_ABLATION_VARIANTS * len(seeds)
    )


def _scaling_is_complete(
    ckpt_dir: Path, scales: List[str], seeds: List[int],
) -> bool:
    if not ckpt_dir.exists():
        return False
    for fam in SCALING_FAMILIES:
        for sc in scales:
            for sd in seeds:
                if not (ckpt_dir / f"{fam}_{sc}_seed{sd}.pt").exists():
                    return False
    return True


def _stage_result_exists(stage_dir: Path) -> bool:
    rf = stage_dir / "results.json"
    return rf.exists() and rf.stat().st_size > 0


def _critical_is_complete(stage_dir: Path) -> bool:
    """Critical stage is complete when results.json has a 'verdict' block."""
    rf = stage_dir / "results.json"
    if not (rf.exists() and rf.stat().st_size > 0):
        return False
    try:
        blob = json.loads(rf.read_text(encoding="utf-8"))
    except Exception:
        return False
    return isinstance(blob, dict) and bool(blob.get("verdict"))


def _energy_result_is_current(stage_dir: Path) -> bool:
    """A v2.2 energy results.json that already contains the baseline
    'transformer' family is considered current/complete. An old-schema or
    single-family file is treated as STALE so the stage re-runs."""
    rf = stage_dir / "results.json"
    if not (rf.exists() and rf.stat().st_size > 0):
        return False
    try:
        blob = json.loads(rf.read_text(encoding="utf-8"))
    except Exception:
        return False
    schema = str(blob.get("schema_version", ""))
    results = blob.get("results", {})
    if not schema.startswith(ENERGY_SCHEMA_PREFIX):
        print(f"[resume] energy: results.json schema '{schema}' is STALE "
              f"(want '{ENERGY_SCHEMA_PREFIX}*'); will re-run.")
        return False
    if "transformer" not in results:
        print("[resume] energy: results.json lacks the 'transformer' "
              "baseline; will re-run so the comparison can be computed.")
        return False
    return True


# ======================================================================
# Main
# ======================================================================

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
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--max_seq_len", type=int, default=512)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--target_tokens_per_param", type=float, default=200.0,
    )
    parser.add_argument(
        "--scaling_scales", type=str, nargs="+", default=None,
        help="Override scaling-law scales. Default: only --scale. "
             "When you add scales, also pass --force_stage scaling energy.",
    )
    # ---- critical-exponents controls ----
    parser.add_argument(
        "--critical_n_sequences", type=int, default=2000,
        help="Sequences for the critical-exponent battery. The sub-script's "
             "own default (10000) collects a multi-GB hidden-state tensor and "
             "runs single-thread DFA, which OOM/swaps ('hangs') on small "
             "machines. 2000 is plenty for stable Hurst/beta estimates.",
    )
    # ---- energy / iso-performance controls ----
    parser.add_argument(
        "--energy_target_ppl", type=float, default=None,
        help="Target perplexity for the DECISIVE iso-performance energy "
             "comparison (C13). Only meaningful once the transformer scaling "
             "curve actually reaches it within the measured range; otherwise "
             "the energy script will report 'out of range' (no extrapolation).",
    )
    parser.add_argument(
        "--energy_new_tokens", type=int, default=64,
        help="New tokens per decode iteration in the energy benchmark.",
    )
    parser.add_argument("--skip_scaling", action="store_true")
    parser.add_argument("--skip_ablation", action="store_true")
    parser.add_argument("--skip_critical", action="store_true")
    parser.add_argument("--skip_energy", action="store_true")
    parser.add_argument(
        "--force", action="store_true",
        help="Ignore ALL .done markers and re-run every non-skipped stage.",
    )
    parser.add_argument(
        "--force_stage", type=str, nargs="+", default=[],
        choices=ALL_STAGES,
        help="Re-run specific stage(s) even if marked done.",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="DANGER: delete output_root before running (clean start).",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    output_root = Path(args.output_root)

    if args.fresh and output_root.exists():
        import shutil
        print(f"[fresh] Deleting output_root: {output_root}")
        shutil.rmtree(output_root)

    output_root.mkdir(parents=True, exist_ok=True)

    # Device report.
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"\n[device] ✓ GPU: {gpu_name} ({gpu_mem:.1f} GB)")
        has_gpu = True
    else:
        print("\n[device] ⚠ No CUDA GPU — running on CPU; energy skipped.")
        has_gpu = False

    vocab_size = detect_vocab_size(args.tokenizer_path)
    print(f"[info] vocab_size={vocab_size}, batch_size={args.batch_size}, "
          f"max_seq_len={args.max_seq_len}, scale={args.scale}")
    print(f"[info] target_tokens_per_param={args.target_tokens_per_param}")

    scaling_dir = output_root / "scaling_law_v2.1"
    ablation_dir = output_root / "ablation_v2.1"
    critical_dir = output_root / "critical_exponents_v2.1"
    energy_dir = output_root / "energy_v2.1"
    ckpt_dir = scaling_dir / "checkpoints"

    def should_run(stage: str, user_skip: bool) -> bool:
        if user_skip:
            print(f"[resume] stage '{stage}' SKIPPED by --skip flag.")
            return False
        if args.force or (stage in args.force_stage):
            print(f"[resume] stage '{stage}' FORCED to run.")
            return True
        if _is_done(output_root, stage):
            print(f"[resume] stage '{stage}' already DONE — skipping. "
                  f"(delete {_done_marker(output_root, stage).name} to re-run)")
            return False
        return True

    summary = {
        "device": "cuda" if has_gpu else "cpu",
        "vocab_size": vocab_size,
        "base_batch_size": args.batch_size,
        "max_seq_len": args.max_seq_len,
        "scale": args.scale,
        "seeds": args.seeds,
        "target_tokens_per_param": args.target_tokens_per_param,
        "critical_n_sequences": args.critical_n_sequences,
        "energy_target_ppl": args.energy_target_ppl,
        "energy_new_tokens": args.energy_new_tokens,
        "resume": {
            "force": bool(args.force),
            "force_stage": list(args.force_stage),
            "fresh": bool(args.fresh),
        },
        "stages": {},
        "experiments_run": [],
        "experiments_skipped": [],
        "warnings": [],
    }

    # Determine scaling scales (default: only --scale).
    if args.scaling_scales is not None:
        scaling_scales = list(args.scaling_scales)
    else:
        scaling_scales = [args.scale]
    if args.scale not in scaling_scales:
        scaling_scales.append(args.scale)

    # ================================================================
    # 1. Scaling law (sub-script resumes via checkpoints + sidecars)
    # ================================================================
    if should_run(STAGE_SCALING, args.skip_scaling):
        if _scaling_is_complete(ckpt_dir, scaling_scales, args.seeds):
            print("[resume] scaling_law: all checkpoints present — done.")
            _mark_done(output_root, STAGE_SCALING,
                       {"status": "already_complete",
                        "scales": scaling_scales, "seeds": args.seeds})
            summary["stages"][STAGE_SCALING] = "already_complete"
        else:
            scaling_bs = min(
                safe_batch_size(s, args.batch_size) for s in scaling_scales
            )
            print(f"\n[scaling] scales={scaling_scales}, "
                  f"batch_size={scaling_bs}, "
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
                    "--target_tokens_per_param",
                    str(args.target_tokens_per_param),
                    "--output_dir", str(scaling_dir),
                    "--resume",
                ],
                cwd=project_root,
            )
            summary["experiments_run"].append(
                {"name": "scaling_law", "exit_code": rc}
            )
            if rc == 0 and _scaling_is_complete(
                ckpt_dir, scaling_scales, args.seeds
            ):
                _mark_done(output_root, STAGE_SCALING,
                           {"status": "completed", "exit_code": rc,
                            "scales": scaling_scales, "seeds": args.seeds})
                summary["stages"][STAGE_SCALING] = "completed"
            else:
                summary["stages"][STAGE_SCALING] = f"incomplete(rc={rc})"
                summary["warnings"].append(
                    f"[warn] scaling_law incomplete (rc={rc}); re-run to "
                    "resume remaining seeds/scales."
                )
    else:
        summary["experiments_skipped"].append(STAGE_SCALING)
        summary["stages"][STAGE_SCALING] = "skipped_or_done"

    # ================================================================
    # 2. Ablation (sub-script resumes via results.json)
    # ================================================================
    if should_run(STAGE_ABLATION, args.skip_ablation):
        results_file = ablation_dir / "results.json"
        if _ablation_is_complete(results_file, args.seeds):
            print("[resume] ablation: results.json already complete — done.")
            _mark_done(output_root, STAGE_ABLATION,
                       {"status": "already_complete",
                        "n_records": len(_load_results(results_file))})
            summary["stages"][STAGE_ABLATION] = "already_complete"
        else:
            done_pairs = _ablation_completed_pairs(results_file)
            if done_pairs:
                print(f"[resume] ablation: {len(done_pairs)} (variant,seed) "
                      f"already done; run_ablation.py will append the rest.")
            abl_bs = safe_batch_size(args.scale, args.batch_size)
            print(f"\n[ablation] scale={args.scale}, batch_size={abl_bs}, "
                  f"epochs={args.epochs}")
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
                    "--resume",
                ],
                cwd=project_root,
            )
            summary["experiments_run"].append(
                {"name": "ablation", "exit_code": rc}
            )
            if rc == 0 and _ablation_is_complete(results_file, args.seeds):
                _mark_done(output_root, STAGE_ABLATION,
                           {"status": "completed", "exit_code": rc,
                            "n_records": len(_load_results(results_file))})
                summary["stages"][STAGE_ABLATION] = "completed"
            else:
                summary["stages"][STAGE_ABLATION] = f"incomplete(rc={rc})"
                summary["warnings"].append(
                    f"[warn] ablation incomplete (rc={rc}); re-run to resume."
                )
    else:
        summary["experiments_skipped"].append(STAGE_ABLATION)
        summary["stages"][STAGE_ABLATION] = "skipped_or_done"

    # ================================================================
    # 3. Critical exponents (memory/quality guarded)
    # ================================================================
    if should_run(STAGE_CRITICAL, args.skip_critical):
        if _critical_is_complete(critical_dir):
            print("[resume] critical: results.json has a verdict — done.")
            _mark_done(output_root, STAGE_CRITICAL,
                       {"status": "already_complete"})
            summary["stages"][STAGE_CRITICAL] = "already_complete"
        else:
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
                    f"in {ckpt_dir}; skipping critical-exponents."
                )
                print("\n" + msg)
                summary["warnings"].append(msg)
                summary["experiments_skipped"].append(STAGE_CRITICAL)
                summary["stages"][STAGE_CRITICAL] = "skipped_no_checkpoint"
            else:
                crit_bs = max(1, min(4, args.batch_size))

                # ---- memory/quality guards ----
                # n_sequences: small to avoid multi-GB hidden states + slow
                #   single-thread DFA swapping ("hang").
                # seq_len: must be >= hidden_size or eta's covariance is
                #   rank-deficient (biased toward 1.0). We cannot exceed the
                #   trained positional limit (args.max_seq_len), so warn when
                #   hidden_size > max_seq_len.
                crit_hidden = read_hidden_size(cid_ckpt, args.scale)
                crit_seq_len = args.max_seq_len
                if crit_hidden is not None and crit_hidden > args.max_seq_len:
                    msg = (f"[warn] critical: hidden_size={crit_hidden} > "
                           f"max_seq_len={args.max_seq_len}; eta will be "
                           f"RANK-DEFICIENT (biased toward 1.0) and must NOT "
                           f"be counted as a pass at scale={args.scale}. "
                           f"Use longer eval sequences for a valid eta here.")
                    print("\n" + msg)
                    summary["warnings"].append(msg)

                print(f"\n[critical] batch_size={crit_bs}, "
                      f"seq_len={crit_seq_len}, "
                      f"hidden_size={crit_hidden}, "
                      f"n_sequences={args.critical_n_sequences}")
                cli_args = [
                    "--checkpoint", str(cid_ckpt),
                    "--data_path", args.data_path,
                    "--tokenizer_path", args.tokenizer_path,
                    "--max_seq_len", str(crit_seq_len),
                    "--batch_size", str(crit_bs),
                    "--n_sequences", str(args.critical_n_sequences),
                    "--output_dir", str(critical_dir),
                    "--resume",
                ]
                if baseline_ckpt is not None:
                    cli_args += ["--baseline_checkpoint", str(baseline_ckpt)]
                else:
                    msg = ("[warn] No Transformer baseline checkpoint; "
                           "critical-exponents runs without negative control.")
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
                    "n_sequences": args.critical_n_sequences,
                    "seq_len": crit_seq_len,
                    "hidden_size": crit_hidden,
                })
                if rc == 0 and _critical_is_complete(critical_dir):
                    _mark_done(output_root, STAGE_CRITICAL,
                               {"status": "completed", "exit_code": rc})
                    summary["stages"][STAGE_CRITICAL] = "completed"
                else:
                    summary["stages"][STAGE_CRITICAL] = f"incomplete(rc={rc})"
                    summary["warnings"].append(
                        f"[warn] critical incomplete (rc={rc}); re-run to "
                        "retry (delete results.json to force a clean pass)."
                    )
    else:
        summary["experiments_skipped"].append(STAGE_CRITICAL)
        summary["stages"][STAGE_CRITICAL] = "skipped_or_done"

    # ================================================================
    # 4. Energy benchmark (v2.2: iso-performance aware)
    #    Resumes per-family; treats old-schema / single-family
    #    results.json as STALE so the comparison can actually be built.
    # ================================================================
    if args.skip_energy:
        summary["experiments_skipped"].append(STAGE_ENERGY)
        summary["stages"][STAGE_ENERGY] = "skipped_by_flag"
    elif not should_run(STAGE_ENERGY, False):
        summary["experiments_skipped"].append(STAGE_ENERGY)
        summary["stages"][STAGE_ENERGY] = "skipped_or_done"
    elif not has_gpu:
        msg = "[warn] Energy benchmark requires GPU; skipping."
        print("\n" + msg)
        summary["warnings"].append(msg)
        summary["experiments_skipped"].append(STAGE_ENERGY)
        summary["stages"][STAGE_ENERGY] = "skipped_no_gpu"
    elif not ckpt_dir.exists() or not any(ckpt_dir.glob("*.pt")):
        msg = f"[warn] No checkpoints in {ckpt_dir}; skipping energy."
        print("\n" + msg)
        summary["warnings"].append(msg)
        summary["experiments_skipped"].append(STAGE_ENERGY)
        summary["stages"][STAGE_ENERGY] = "skipped_no_checkpoint"
    elif _energy_result_is_current(energy_dir):
        print("[resume] energy: current v2.2 results.json present — done.")
        _mark_done(output_root, STAGE_ENERGY, {"status": "already_complete"})
        summary["stages"][STAGE_ENERGY] = "already_complete"
    else:
        energy_bs = max(1, min(8, args.batch_size))
        scaling_results_json = scaling_dir / "results.json"

        # decode guard: starting seq_len + new_tokens must fit the trained
        # positional limit (max_seq_len). Clamp the energy seq_len so the
        # transformer baseline (which enforces a hard max) does not overflow.
        energy_seq_len = args.max_seq_len
        budget = args.max_seq_len - args.energy_new_tokens
        if budget < 1:
            raise RuntimeError(
                f"--energy_new_tokens={args.energy_new_tokens} >= "
                f"max_seq_len={args.max_seq_len}; reduce --energy_new_tokens.")
        if energy_seq_len > budget:
            print(f"[energy] clamping decode seq_len {energy_seq_len} -> "
                  f"{budget} so seq_len + new_tokens "
                  f"({args.energy_new_tokens}) <= max_seq_len "
                  f"({args.max_seq_len}).")
            energy_seq_len = budget

        print(f"\n[energy] batch_size={energy_bs}, vocab_size={vocab_size}, "
              f"mode=decode, seq_len={energy_seq_len}, "
              f"new_tokens={args.energy_new_tokens}")

        energy_cli = [
            "--families", "cid_full", "transformer",
            "transformer_plus_tricks",
            "--checkpoint_dir", str(ckpt_dir),
            "--scale", args.scale,
            "--seeds", *[str(s) for s in args.seeds],
            "--batch_size", str(energy_bs),
            "--seq_len", str(energy_seq_len),
            "--vocab_size", str(vocab_size),
            "--mode", "decode",
            "--new_tokens_per_decode", str(args.energy_new_tokens),
            "--output_dir", str(energy_dir),
            "--resume",
        ]

        if scaling_results_json.exists():
            energy_cli += ["--scaling_law_json", str(scaling_results_json)]
            if args.energy_target_ppl is not None:
                energy_cli += ["--target_ppl", str(args.energy_target_ppl)]
            else:
                msg = ("[warn] energy: --energy_target_ppl not set; the "
                       "iso-performance (C13) column will be SKIPPED. Set it "
                       "to a perplexity reachable by ALL families to get the "
                       "energy-efficiency verdict.")
                print("\n" + msg)
                summary["warnings"].append(msg)
        else:
            msg = (f"[warn] energy: {scaling_results_json} not found; "
                   "iso-performance column unavailable (only neutral "
                   "iso-parameter views will be printed).")
            print("\n" + msg)
            summary["warnings"].append(msg)

        rc = run_script(
            "experiments/run_energy_benchmark.py",
            energy_cli,
            cwd=project_root,
        )
        summary["experiments_run"].append(
            {"name": "energy", "exit_code": rc}
        )
        if rc == 0 and _energy_result_is_current(energy_dir):
            _mark_done(output_root, STAGE_ENERGY,
                       {"status": "completed", "exit_code": rc})
            summary["stages"][STAGE_ENERGY] = "completed"
        else:
            summary["stages"][STAGE_ENERGY] = f"incomplete(rc={rc})"
            summary["warnings"].append(
                f"[warn] energy incomplete (rc={rc}) or results not current; "
                "re-run to resume (it merges per-family)."
            )

    # --------------------- Final summary ----------------------------
    (output_root / "run_all_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print("PIPELINE FINISHED (resumable)")
    print("=" * 60)
    print(json.dumps(summary["stages"], indent=2, ensure_ascii=False))
    if summary["warnings"]:
        print("\nWarnings:")
        for w in summary["warnings"]:
            print(" ", w)
    print(f"\nResults: {output_root}")
    print("Re-run the SAME command to resume; delete output_root or use "
          "--fresh for a clean start.")


if __name__ == "__main__":
    main()
