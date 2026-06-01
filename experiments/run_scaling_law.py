# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-06-01 (resumable, aligned with run_all.py)
#   * --resume now ROBUST: skips any (family, scale, seed) whose unified
#     checkpoint already exists, and reconstructs its ScalingResult from
#     a per-point results sidecar so the final plot/JSON are complete.
#   * Per-point result is written immediately after each run (incremental
#     save) so an interruption never loses a finished point.
#   * results.json is merged across resumed runs (no overwrite).
# UPDATE: 2026-05-28
#   * build_model propagates v2.1 keys; unified checkpoint schema saved
#     per (family, scale, seed) for downstream critical/energy scripts.
"""
The CORE experiment for UID's "parameter efficiency" claim — RESUMABLE.

This script trains families of models at multiple scales:
  - Modern Transformer baseline (10M, 30M, 100M, 300M, 1B*)
  - Transformer + all known tricks (same scales)
  - Full CID (same scales)
  - (optional) CID with §8.5 ET symmetric term disabled
  - (optional) CID with §14.2 OU replaced by FFT noise

For each model, we measure:
  - Non-embedding parameter count
  - Validation loss at equal training-FLOP budget
  - Wall-clock time
  - Saves a unified checkpoint for downstream critical-exponent
    and energy-benchmark scripts.

RESUME BEHAVIOR (--resume):
  * A (family, scale, seed) point is SKIPPED if its unified checkpoint
    already exists. Its ScalingResult is reconstructed from the per-point
    sidecar JSON (checkpoints/<name>.result.json) so plots stay complete.
  * Each finished point is written immediately (checkpoint + sidecar +
    merged results.json), so interruption loses at most the in-flight point.
  * Delete the checkpoint (or the whole output_dir) to force a re-run.

UID's "5-10x parameter efficiency" is operationalized as:
  At a given validation loss level, the horizontal distance between CID's
  curve and the Transformer baseline's curve must be >= log10(5) ~ 0.7.

* The 1B scale requires multi-GPU; use --scales to control which run.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from model.modern_transformer import ModernTransformerLM
from model.known_tricks_baseline import TransformerPlusTricksLM
from model.model_uid import UIDConfig, UIDModel
# from model.mamba_baseline import MambaLM  # optional, if mamba-ssm installed


# Standard scaling-law config: hidden_size, num_layers, num_heads.
SCALE_CONFIGS: Dict[str, Dict[str, int]] = {
    "10M":  dict(hidden_size=256,  num_layers=6,  num_heads=4),
    "30M":  dict(hidden_size=384,  num_layers=8,  num_heads=6),
    "100M": dict(hidden_size=512,  num_layers=12, num_heads=8),
    "300M": dict(hidden_size=768,  num_layers=16, num_heads=12),
    "1B":   dict(hidden_size=1024, num_layers=24, num_heads=16),
}


# Valid model families this script supports.
VALID_FAMILIES = {
    "transformer",
    "transformer_plus_tricks",
    "cid_full",
    "cid_full_no_et",        # v2.1: §8.5 isolation
    "cid_full_fft_noise",    # v2.1: §14.2 isolation
}

# Default families to train for the scaling-law comparison.
DEFAULT_FAMILIES = ["transformer", "transformer_plus_tricks", "cid_full"]


@dataclass
class ScalingResult:
    """Single point on the scaling curve."""
    model_family: str
    scale_name: str
    non_emb_params: int
    train_flops: float
    final_train_loss: float
    final_eval_loss: float
    final_eval_ppl: float
    wall_clock_seconds: float
    seed: int


# ======================================================================
# Model factory
# ======================================================================


def build_model(
    family: str,
    scale: str,
    vocab_size: int,
    max_seq_len: int,
    noise_type: str = "ou",
    noise_tau: float = 10.0,
    noise_beta: float = 1.0,
    use_et_symmetric: bool = True,
) -> nn.Module:
    """Construct a model of the given family/scale with v2.1 keys.

    构造指定 family/scale 的模型，透传 v2.1 关键参数。
    """
    if family not in VALID_FAMILIES:
        raise ValueError(
            f"unknown family '{family}'; valid: {sorted(VALID_FAMILIES)}"
        )
    cfg = SCALE_CONFIGS[scale]
    hidden_size = cfg["hidden_size"]
    num_layers = cfg["num_layers"]
    num_heads = cfg["num_heads"]

    if family == "transformer":
        return ModernTransformerLM(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            max_seq_len=max_seq_len,
        )

    if family == "transformer_plus_tricks":
        return TransformerPlusTricksLM(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            max_seq_len=max_seq_len,
        )

    # CID family variants.
    uid_cfg = UIDConfig(
        vocab_size=vocab_size,
        hidden_size=hidden_size,
        num_hidden_layers=num_layers,
        num_attention_heads=num_heads,
        max_position_embeddings=max_seq_len,
        noise_type=noise_type,
        noise_tau=noise_tau,
        noise_beta=noise_beta,
        use_et_symmetric=use_et_symmetric,
    )
    if family == "cid_full":
        pass  # all defaults on
    elif family == "cid_full_no_et":
        uid_cfg.use_et_symmetric = False
    elif family == "cid_full_fft_noise":
        uid_cfg.noise_type = "fft"
    return UIDModel(uid_cfg)


def _init_kwargs_for(
    family: str,
    scale: str,
    vocab_size: int,
    max_seq_len: int,
    noise_type: str,
    noise_tau: float,
    noise_beta: float,
    use_et_symmetric: bool,
) -> Dict[str, Any]:
    """Plain-kwargs dict that build_model() can consume to rebuild a model."""
    return {
        "family": family,
        "scale": scale,
        "vocab_size": vocab_size,
        "max_seq_len": max_seq_len,
        "noise_type": noise_type,
        "noise_tau": noise_tau,
        "noise_beta": noise_beta,
        "use_et_symmetric": use_et_symmetric,
    }


def count_non_embedding_params(model: nn.Module) -> int:
    """Count parameters excluding token/position embeddings."""
    total = 0
    for name, p in model.named_parameters():
        lname = name.lower()
        if "emb" in lname or "embedding" in lname:
            continue
        total += p.numel()
    return total


# ======================================================================
# Training
# ======================================================================


def train_one(
    model: nn.Module,
    train_loader: DataLoader,
    eval_loader: DataLoader,
    max_steps: int,
    lr: float,
    device: str,
    log_every: int = 100,
) -> tuple[float, float, float]:
    """Train for a fixed step budget; return (train_loss, eval_loss, wall)."""
    model.to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)

    start = time.time()
    model.train()
    running = 0.0
    n_tok = 0
    step = 0
    done = False
    while not done:
        for batch in train_loader:
            if step >= max_steps:
                done = True
                break
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            optim.zero_grad()
            out = model(input_ids=input_ids, labels=labels)
            if out.loss is None or not torch.isfinite(out.loss):
                step += 1
                continue
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()

            ntok = int((labels != -100).sum().item())
            running += float(out.loss.item()) * ntok
            n_tok += ntok
            if step % log_every == 0:
                print(f"    step {step}/{max_steps} "
                      f"loss={float(out.loss.item()):.4f}")
            step += 1
    train_loss = running / max(n_tok, 1)

    # Eval.
    model.eval()
    e_running = 0.0
    e_n = 0
    with torch.no_grad():
        for batch in eval_loader:
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            out = model(input_ids=input_ids, labels=labels)
            if out.loss is None:
                continue
            ntok = int((labels != -100).sum().item())
            e_running += float(out.loss.item()) * ntok
            e_n += ntok
    eval_loss = e_running / max(e_n, 1)
    wall = time.time() - start
    return train_loss, eval_loss, wall


# ======================================================================
# Resume helpers
# ======================================================================


def _ckpt_path(ckpt_dir: Path, family: str, scale: str, seed: int) -> Path:
    return ckpt_dir / f"{family}_{scale}_seed{seed}.pt"


def _sidecar_path(ckpt_dir: Path, family: str, scale: str, seed: int) -> Path:
    """Per-point result sidecar (so resume can rebuild ScalingResult)."""
    return ckpt_dir / f"{family}_{scale}_seed{seed}.result.json"


def _save_point(
    ckpt_dir: Path,
    result: ScalingResult,
    init_kwargs: Dict[str, Any],
    config_dict: Optional[Dict[str, Any]],
    model_state: Dict[str, Any],
) -> None:
    """Save unified checkpoint + sidecar result JSON for one point."""
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    cp = _ckpt_path(ckpt_dir, result.model_family,
                    result.scale_name, result.seed)
    torch.save(
        {
            "schema_version": "v2.1",
            "model_family": result.model_family,
            "scale_name": result.scale_name,
            "init_kwargs": init_kwargs,
            "config_dict": config_dict,
            "model_state": model_state,
            "seed": result.seed,
            "n_params": result.non_emb_params,
            "v21_keys": {
                "noise_type": init_kwargs.get("noise_type"),
                "noise_tau": init_kwargs.get("noise_tau"),
                "use_et_symmetric": init_kwargs.get("use_et_symmetric"),
            },
        },
        cp,
    )
    # Sidecar: enough to reconstruct ScalingResult without retraining.
    sc = _sidecar_path(ckpt_dir, result.model_family,
                       result.scale_name, result.seed)
    sc.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(f"  Checkpoint -> {cp.name}")


def _load_point_result(
    ckpt_dir: Path, family: str, scale: str, seed: int,
) -> Optional[ScalingResult]:
    """Reconstruct a ScalingResult from the sidecar if the checkpoint exists."""
    cp = _ckpt_path(ckpt_dir, family, scale, seed)
    sc = _sidecar_path(ckpt_dir, family, scale, seed)
    if not cp.exists():
        return None
    if sc.exists():
        try:
            d = json.loads(sc.read_text(encoding="utf-8"))
            return ScalingResult(**d)
        except Exception:
            pass
    # Sidecar missing/corrupt but checkpoint exists: rebuild minimal info
    # from the checkpoint payload (loss fields unknown -> NaN, but params ok).
    try:
        ckpt = torch.load(cp, map_location="cpu")
        return ScalingResult(
            model_family=ckpt.get("model_family", family),
            scale_name=ckpt.get("scale_name", scale),
            non_emb_params=int(ckpt.get("n_params", 0)),
            train_flops=float("nan"),
            final_train_loss=float("nan"),
            final_eval_loss=float("nan"),
            final_eval_ppl=float("nan"),
            wall_clock_seconds=float("nan"),
            seed=int(ckpt.get("seed", seed)),
        )
    except Exception:
        return None


def _merge_results_json(
    output_dir: Path, all_results: List[ScalingResult],
) -> None:
    """Write merged results.json from the full ScalingResult list."""
    payload = [asdict(r) for r in all_results]
    (output_dir / "results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ======================================================================
# Scaling experiment (resumable)
# ======================================================================


def run_scaling_experiment(
    families: List[str],
    scales: List[str],
    seeds: List[int],
    data_path: str,
    tokenizer_path: str,
    output_dir: Path,
    max_seq_len: int,
    batch_size: int,
    lr: float,
    target_tokens_per_param: float,
    device: str,
    resume: bool,
) -> List[ScalingResult]:
    """Train every (family, scale, seed); resumable via existing checkpoints."""
    ckpt_dir = output_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # Tokenizer + data.
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    vocab_size = int(max(tokenizer.vocab_size, len(tokenizer)))

    from data_loaders import PretrainJsonl
    full_dataset = PretrainJsonl(
        Path(data_path), tokenizer, max_length=max_seq_len
    )
    n = len(full_dataset)
    train_ds, eval_ds = torch.utils.data.random_split(
        full_dataset, [int(0.9 * n), n - int(0.9 * n)],
        generator=torch.Generator().manual_seed(42),
    )
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    eval_loader = DataLoader(eval_ds, batch_size=batch_size)

    all_results: List[ScalingResult] = []

    total = len(families) * len(scales) * len(seeds)
    done = 0

    for family in families:
        for scale in scales:
            cfg = SCALE_CONFIGS[scale]
            for seed in seeds:
                done += 1
                header = (f"[{done}/{total}] {family} @ {scale} "
                          f"(seed={seed})")

                # ---- RESUME: skip if checkpoint already exists ----
                if resume:
                    existing = _load_point_result(
                        ckpt_dir, family, scale, seed
                    )
                    if existing is not None:
                        print(f"\n{'=' * 60}")
                        print(f"{header}  [resume] SKIP — checkpoint exists")
                        print(f"{'=' * 60}")
                        all_results.append(existing)
                        _merge_results_json(output_dir, all_results)
                        continue

                print(f"\n{'=' * 60}")
                print(f"Training {family} @ {scale} (seed={seed})")
                print(f"{'=' * 60}")

                torch.manual_seed(seed)
                np.random.seed(seed)

                # v2.1 toggles for CID variants.
                noise_type = "ou"
                use_et_symmetric = True
                if family == "cid_full_no_et":
                    use_et_symmetric = False
                elif family == "cid_full_fft_noise":
                    noise_type = "fft"

                init_kwargs = _init_kwargs_for(
                    family=family, scale=scale, vocab_size=vocab_size,
                    max_seq_len=max_seq_len, noise_type=noise_type,
                    noise_tau=10.0, noise_beta=1.0,
                    use_et_symmetric=use_et_symmetric,
                )
                model = build_model(**init_kwargs)

                non_emb = count_non_embedding_params(model)
                print(f"  Non-embedding params: {non_emb:,}")

                # Iso-FLOP budget: tokens = tokens_per_param * params.
                target_tokens = target_tokens_per_param * non_emb
                tokens_per_step = batch_size * max_seq_len
                max_steps = max(1, int(target_tokens / tokens_per_step))
                # 6 * N * D FLOPs (forward+backward).
                target_flops = 6.0 * non_emb * target_tokens
                print(f"  Target tokens={target_tokens:.3e}, "
                      f"max_steps={max_steps}, "
                      f"Target train FLOPs={target_flops:.3e}")
                print(f"  v2.1 toggles: noise_type={noise_type}, "
                      f"use_et_symmetric={use_et_symmetric}")

                train_loss, eval_loss, wall = train_one(
                    model=model,
                    train_loader=train_loader,
                    eval_loader=eval_loader,
                    max_steps=max_steps,
                    lr=lr,
                    device=device,
                )

                result = ScalingResult(
                    model_family=family,
                    scale_name=scale,
                    non_emb_params=non_emb,
                    train_flops=target_flops,
                    final_train_loss=train_loss,
                    final_eval_loss=eval_loss,
                    final_eval_ppl=float(np.exp(eval_loss)),
                    wall_clock_seconds=wall,
                    seed=seed,
                )
                all_results.append(result)

                # config_dict only for UID family (HF-serializable).
                config_dict = None
                if hasattr(model, "config") and isinstance(
                    model.config, UIDConfig
                ):
                    try:
                        config_dict = model.config.to_dict()
                    except Exception:
                        config_dict = None

                # ---- INCREMENTAL SAVE: checkpoint + sidecar + merged json
                _save_point(
                    ckpt_dir=ckpt_dir,
                    result=result,
                    init_kwargs=init_kwargs,
                    config_dict=config_dict,
                    model_state=model.state_dict(),
                )
                _merge_results_json(output_dir, all_results)

                print(f"  Final: train_loss={train_loss:.4f}, "
                      f"eval_loss={eval_loss:.4f}, "
                      f"eval_ppl={float(np.exp(eval_loss)):.2f}")

                del model
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    return all_results


# ======================================================================
# Plotting + analysis
# ======================================================================


def make_scaling_plot(
    results: List[ScalingResult], output_dir: Path,
) -> None:
    """Save Loss-vs-Params scaling curve (one line per family)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"[warn] matplotlib unavailable ({e}); skipping plot.")
        return

    by_family: Dict[str, List[ScalingResult]] = {}
    for r in results:
        by_family.setdefault(r.model_family, []).append(r)

    plt.figure(figsize=(8, 6))
    for family, pts in by_family.items():
        # Average over seeds per (scale).
        by_scale: Dict[str, List[ScalingResult]] = {}
        for p in pts:
            by_scale.setdefault(p.scale_name, []).append(p)
        xs, ys = [], []
        for scale, runs in by_scale.items():
            params = np.mean([r.non_emb_params for r in runs])
            loss = np.mean([
                r.final_eval_loss for r in runs
                if r.final_eval_loss == r.final_eval_loss  # not NaN
            ]) if any(
                r.final_eval_loss == r.final_eval_loss for r in runs
            ) else float("nan")
            if loss == loss:  # not NaN
                xs.append(params)
                ys.append(loss)
        if xs:
            order = np.argsort(xs)
            xs = np.array(xs)[order]
            ys = np.array(ys)[order]
            plt.plot(xs, ys, "o-", label=family)

    plt.xscale("log")
    plt.xlabel("Non-embedding parameters")
    plt.ylabel("Validation loss")
    plt.title("UID Scaling Law (v2.1)")
    plt.legend()
    plt.grid(True, which="both", alpha=0.3)
    out = output_dir / "scaling_curves.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n[ok] Plot saved to {out}")


def print_analysis(results: List[ScalingResult]) -> None:
    """Print a per-family scaling-law summary table."""
    print("\n" + "=" * 60)
    print("Scaling-Law Analysis (v2.1)")
    print("=" * 60)

    by_family: Dict[str, List[ScalingResult]] = {}
    for r in results:
        by_family.setdefault(r.model_family, []).append(r)

    for family, pts in by_family.items():
        print(f"\n{family}:")
        for p in sorted(pts, key=lambda r: (r.scale_name, r.seed)):
            print(f"  {p.scale_name}: params={p.non_emb_params:,}, "
                  f"loss={p.final_eval_loss:.4f}, "
                  f"ppl={p.final_eval_ppl:.2f}")


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument(
        "--scales", type=str, nargs="+",
        default=["10M", "30M", "100M"],
    )
    parser.add_argument(
        "--families", type=str, nargs="+",
        default=DEFAULT_FAMILIES,
        help="Model families to train (default: transformer, "
             "transformer_plus_tricks, cid_full).",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
    )
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--max_seq_len", type=int, default=1024)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--target_tokens_per_param", type=float, default=20.0,
        help="Iso-FLOP training budget (tokens per parameter). "
             "Chinchilla-optimal ~20; use 200+ for full convergence on "
             "small datasets.",
    )
    parser.add_argument(
        "--output_dir", type=str,
        default="./results/scaling_law_v2.1",
    )
    # ---- Resume support (for run_all.py end-to-end resume) ----
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip (family, scale, seed) points whose checkpoint already "
             "exists; reconstruct their results from sidecar JSON. Delete "
             "the checkpoint (or output_dir) to force a re-run.",
    )
    args = parser.parse_args()

    # Validate families.
    for f in args.families:
        if f not in VALID_FAMILIES:
            raise ValueError(
                f"unknown family '{f}'; valid: {sorted(VALID_FAMILIES)}"
            )
    # Validate scales.
    for s in args.scales:
        if s not in SCALE_CONFIGS:
            raise ValueError(
                f"unknown scale '{s}'; valid: {sorted(SCALE_CONFIGS)}"
            )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda":
        print(f"[device] ✓ GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("[device] ⚠ CPU (scaling law on CPU is slow)")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[info] families={args.families}")
    print(f"[info] scales={args.scales}, seeds={args.seeds}")
    print(f"[info] batch_size={args.batch_size}, "
          f"max_seq_len={args.max_seq_len}, "
          f"tokens_per_param={args.target_tokens_per_param}")
    print(f"[info] resume={args.resume}")

    results = run_scaling_experiment(
        families=args.families,
        scales=args.scales,
        seeds=args.seeds,
        data_path=args.data_path,
        tokenizer_path=args.tokenizer_path,
        output_dir=output_dir,
        max_seq_len=args.max_seq_len,
        batch_size=args.batch_size,
        lr=args.lr,
        target_tokens_per_param=args.target_tokens_per_param,
        device=device,
        resume=args.resume,
    )

    # Final merged results, plot, analysis.
    _merge_results_json(output_dir, results)
    make_scaling_plot(results, output_dir)
    print_analysis(results)

    print(f"\n[ok] Results saved to {output_dir / 'results.json'}")
    print(f"[ok] Checkpoints in {output_dir / 'checkpoints'}")
    if args.resume:
        print("[resume] Re-run the SAME command to continue any remaining "
              "(family, scale, seed) points.")


if __name__ == "__main__":
    main()
