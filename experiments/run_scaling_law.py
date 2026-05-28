# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * build_model: propagate v2.1 keys (noise_type, noise_tau,
#     use_et_symmetric) all the way to model factories.
#   * Save unified checkpoints per (family, scale, seed) so
#     run_critical_exponents.py and run_energy_benchmark.py can
#     actually load them.
#   * Unified checkpoint schema:
#         {"model_family": str,
#          "scale_name":   str,
#          "init_kwargs":  dict,     # plain Python kwargs to ctor
#          "config_dict":  dict|None,# UIDConfig.to_dict() if applicable
#          "model_state":  state_dict,
#          "seed":         int,
#          "n_params":     int,
#          "v21_keys":     {...}}    # records v2.1 toggles used
"""
The CORE experiment for UID's "parameter efficiency" claim.

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

The output is the canonical scaling-law plot:
  Loss vs Non-embedding Parameters (one curve per model family).

UID's claim of "5-10x parameter efficiency" is operationalized as:
  At a given validation loss level, the horizontal distance between
  CID's curve and the Transformer baseline's curve must be >= log10(5)
  approx 0.7.

* The 1B scale requires multi-GPU; use the `--scales` flag to control
  which scales are trained.
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
    # v2.1: which toggles were used (for reproducibility).
    v21_keys: Dict[str, Any]


# ======================================================================
# Helpers
# ======================================================================


def estimate_train_flops(n_params: int, n_tokens: int) -> float:
    """Chinchilla approximation: FLOPs ~= 6 * N * D."""
    return 6.0 * n_params * n_tokens


def count_non_embedding_params(model: nn.Module) -> int:
    """Generic non-embedding parameter counter for all model families.

    Each baseline / CID model exposes its own embedding via
    ``tok_emb`` (tied with lm_head). We subtract the embedding count
    only once (because of weight tying).
    """
    if hasattr(model, "count_non_embedding_params"):
        return int(model.count_non_embedding_params())
    # Generic fallback.
    total = sum(p.numel() for p in model.parameters())
    if hasattr(model, "tok_emb") and hasattr(model.tok_emb, "weight"):
        total -= int(model.tok_emb.weight.numel())
    return int(total)


def build_model(
    family: str,
    scale: str,
    vocab_size: int,
    max_seq_len: int,
    *,
    noise_type: str = "ou",
    noise_tau: float = 10.0,
    noise_beta: float = 1.0,
    use_et_symmetric: bool = True,
) -> nn.Module:
    """Build a model of the specified family and scale.

    All v2.1 toggles are explicit keyword arguments so the caller can
    sweep them in a scaling study (e.g., compare CID-with-ET vs
    CID-without-ET at every scale).
    """
    if family not in VALID_FAMILIES:
        raise ValueError(
            f"Unknown model family: {family!r}; "
            f"expected one of {sorted(VALID_FAMILIES)}"
        )
    if scale not in SCALE_CONFIGS:
        raise ValueError(
            f"Unknown scale: {scale!r}; "
            f"expected one of {sorted(SCALE_CONFIGS)}"
        )
    cfg = SCALE_CONFIGS[scale]

    if family == "transformer":
        return ModernTransformerLM(
            vocab_size=vocab_size,
            max_seq_len=max_seq_len,
            **cfg,
        )

    if family == "transformer_plus_tricks":
        return TransformerPlusTricksLM(
            vocab_size=vocab_size,
            max_seq_len=max_seq_len,
            use_noise=True,
            use_conv=True,
            use_linear=True,
            noise_type=noise_type,
            noise_tau=noise_tau,
            noise_beta=noise_beta,
            **cfg,
        )

    # All CID-family variants share the same backbone, only toggles differ.
    cid_kwargs = dict(
        use_vortex=True,
        use_memory=True,
        use_colored_noise=True,
        noise_type=noise_type,
        noise_tau=noise_tau,
        noise_beta=noise_beta,
        use_et_symmetric=use_et_symmetric,
    )
    if family == "cid_full":
        pass
    elif family == "cid_full_no_et":
        cid_kwargs["use_et_symmetric"] = False
    elif family == "cid_full_fft_noise":
        cid_kwargs["noise_type"] = "fft"

    uid_cfg = UIDConfig(
        vocab_size=vocab_size,
        max_position_embeddings=max_seq_len,
        hidden_size=cfg["hidden_size"],
        num_hidden_layers=cfg["num_layers"],
        num_attention_heads=cfg["num_heads"],
        **cid_kwargs,
    )
    return UIDModel(uid_cfg)


def _serialize_init_kwargs(
    family: str,
    scale: str,
    vocab_size: int,
    max_seq_len: int,
    *,
    noise_type: str,
    noise_tau: float,
    noise_beta: float,
    use_et_symmetric: bool,
) -> Dict[str, Any]:
    """Plain-Python kwargs that reproduce build_model() exactly.

    保存在 checkpoint 中，使 run_critical_exponents.py 与
    run_energy_benchmark.py 可以无依赖地重建相同模型。
    """
    return {
        "family": family,
        "scale": scale,
        "vocab_size": int(vocab_size),
        "max_seq_len": int(max_seq_len),
        "noise_type": noise_type,
        "noise_tau": float(noise_tau),
        "noise_beta": float(noise_beta),
        "use_et_symmetric": bool(use_et_symmetric),
    }


def save_unified_checkpoint(
    ckpt_dir: Path,
    family: str,
    scale: str,
    seed: int,
    model: nn.Module,
    init_kwargs: Dict[str, Any],
    n_params: int,
) -> Path:
    """Save a checkpoint in the canonical v2.1 schema.

    File name pattern:  ``{family}_{scale}_seed{seed}.pt``
    """
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    # If the model is a UIDModel, also persist UIDConfig.to_dict() for
    # HuggingFace-style round-trips (no kwargs lost).
    config_dict: Optional[Dict[str, Any]] = None
    if isinstance(model, UIDModel):
        config_dict = model.config.to_dict()

    payload = {
        "schema_version": "v2.1",
        "model_family": family,
        "scale_name": scale,
        "init_kwargs": init_kwargs,
        "config_dict": config_dict,
        "model_state": model.state_dict(),
        "seed": int(seed),
        "n_params": int(n_params),
        "v21_keys": {
            "noise_type": init_kwargs["noise_type"],
            "noise_tau": init_kwargs["noise_tau"],
            "noise_beta": init_kwargs["noise_beta"],
            "use_et_symmetric": init_kwargs["use_et_symmetric"],
        },
    }
    out_path = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
    torch.save(payload, out_path)
    return out_path


# ======================================================================
# Train loop
# ======================================================================


def train_one(
    model: nn.Module,
    train_loader: DataLoader,
    eval_loader: DataLoader,
    device: str,
    target_train_flops: float,
    lr: float = 3e-4,
    log_every: int = 100,
) -> tuple[float, float, float]:
    """Train one model to a target FLOP budget (iso-FLOP protocol)."""
    model.to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optim, T_max=10000  # rough; refined by FLOPs target
    )

    n_params = count_non_embedding_params(model)

    start = time.time()
    tokens_seen = 0
    train_loss_sum = 0.0
    train_loss_n = 0
    step = 0

    model.train()
    done = False
    while not done:
        for batch in train_loader:
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)

            optim.zero_grad()
            out = model(input_ids=input_ids, labels=labels)
            loss = out.loss
            if loss is None or not torch.isfinite(loss):
                continue
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            scheduler.step()

            ntok = int((labels != -100).sum().item())
            tokens_seen += ntok
            train_loss_sum += float(loss.item()) * ntok
            train_loss_n += ntok
            step += 1

            current_flops = estimate_train_flops(n_params, tokens_seen)

            if step % log_every == 0:
                print(
                    f"  step={step} tokens={tokens_seen} "
                    f"FLOPs={current_flops:.2e}/{target_train_flops:.2e} "
                    f"loss={float(loss.item()):.4f}"
                )

            if current_flops >= target_train_flops:
                done = True
                break

    train_loss = train_loss_sum / max(train_loss_n, 1)

    # Evaluation.
    model.eval()
    eval_loss_sum = 0.0
    eval_loss_n = 0
    with torch.no_grad():
        for batch in eval_loader:
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            out = model(input_ids=input_ids, labels=labels)
            if out.loss is None:
                continue
            ntok = int((labels != -100).sum().item())
            eval_loss_sum += float(out.loss.item()) * ntok
            eval_loss_n += ntok
    eval_loss = eval_loss_sum / max(eval_loss_n, 1)

    wall = time.time() - start
    return train_loss, eval_loss, wall


def run_scaling_experiment(
    families: List[str],
    scales: List[str],
    train_loader: DataLoader,
    eval_loader: DataLoader,
    vocab_size: int,
    max_seq_len: int,
    target_flops_per_param: float,
    output_dir: Path,
    *,
    noise_type: str,
    noise_tau: float,
    noise_beta: float,
    use_et_symmetric: bool,
    device: str = "cuda",
    seeds: List[int] = (42, 43, 44),
) -> List[ScalingResult]:
    """Run the full scaling-law experiment.

    ``target_flops_per_param`` : For each model, total training FLOPs
    will be set to ``target_flops_per_param * n_params``. The Chinchilla
    optimal is around 20 (i.e., 20 tokens per parameter, FLOPs/param
    = 6 * 20 = 120).
    """
    all_results: List[ScalingResult] = []
    ckpt_dir = output_dir / "checkpoints"

    for family in families:
        for scale in scales:
            for seed in seeds:
                print(f"\n{'=' * 60}")
                print(f"Training {family} @ {scale} (seed={seed})")
                print(f"{'=' * 60}")

                torch.manual_seed(seed)
                np.random.seed(seed)

                init_kwargs = _serialize_init_kwargs(
                    family=family,
                    scale=scale,
                    vocab_size=vocab_size,
                    max_seq_len=max_seq_len,
                    noise_type=noise_type,
                    noise_tau=noise_tau,
                    noise_beta=noise_beta,
                    use_et_symmetric=use_et_symmetric,
                )

                model = build_model(
                    family=family,
                    scale=scale,
                    vocab_size=vocab_size,
                    max_seq_len=max_seq_len,
                    noise_type=noise_type,
                    noise_tau=noise_tau,
                    noise_beta=noise_beta,
                    use_et_symmetric=use_et_symmetric,
                )
                n_params = count_non_embedding_params(model)
                target_flops = target_flops_per_param * n_params

                print(f"  Non-embedding params: {n_params:,}")
                print(f"  Target train FLOPs: {target_flops:.3e}")
                print(
                    f"  v2.1 toggles: noise_type={noise_type}, "
                    f"use_et_symmetric={use_et_symmetric}"
                )

                train_loss, eval_loss, wall = train_one(
                    model=model,
                    train_loader=train_loader,
                    eval_loader=eval_loader,
                    device=device,
                    target_train_flops=target_flops,
                )

                # CRITICAL v2.1 fix: actually save a checkpoint so that
                # downstream scripts (critical exponents, energy) can
                # load this model.
                ckpt_path = save_unified_checkpoint(
                    ckpt_dir=ckpt_dir,
                    family=family,
                    scale=scale,
                    seed=seed,
                    model=model,
                    init_kwargs=init_kwargs,
                    n_params=n_params,
                )
                print(f"  Checkpoint -> {ckpt_path}")

                result = ScalingResult(
                    model_family=family,
                    scale_name=scale,
                    non_emb_params=n_params,
                    train_flops=target_flops,
                    final_train_loss=train_loss,
                    final_eval_loss=eval_loss,
                    final_eval_ppl=float(np.exp(eval_loss)),
                    wall_clock_seconds=wall,
                    seed=seed,
                    v21_keys=init_kwargs,
                )
                all_results.append(result)
                print(
                    f"  Final: train_loss={train_loss:.4f}, "
                    f"eval_loss={eval_loss:.4f}, "
                    f"eval_ppl={result.final_eval_ppl:.2f}"
                )

                # Save intermediate.
                save_results(all_results, output_dir)

                # Free memory.
                del model
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    return all_results


def save_results(results: List[ScalingResult], output_dir: Path) -> None:
    """Save results to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "experiment": "scaling_law_v2.1",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_results": len(results),
        "results": [asdict(r) for r in results],
    }
    (output_dir / "results.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )


def plot_scaling_curves(
    results: List[ScalingResult], output_dir: Path
) -> None:
    """Plot the canonical scaling-law figure."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return

    fig, ax = plt.subplots(figsize=(10, 7))

    families = sorted(set(r.model_family for r in results))
    for family in families:
        family_results = [r for r in results if r.model_family == family]
        # Group by scale, average over seeds.
        by_scale: Dict[str, List[ScalingResult]] = {}
        for r in family_results:
            by_scale.setdefault(r.scale_name, []).append(r)

        scales_sorted = sorted(
            by_scale.keys(),
            key=lambda s: by_scale[s][0].non_emb_params,
        )
        xs = [by_scale[s][0].non_emb_params for s in scales_sorted]
        ys_mean = [
            float(np.mean([r.final_eval_loss for r in by_scale[s]]))
            for s in scales_sorted
        ]
        ys_std = [
            float(np.std([r.final_eval_loss for r in by_scale[s]]))
            for s in scales_sorted
        ]

        ax.errorbar(
            xs, ys_mean, yerr=ys_std, marker="o",
            label=family, capsize=4, linewidth=2,
        )

    ax.set_xscale("log")
    ax.set_xlabel("Non-embedding parameters")
    ax.set_ylabel("Eval loss (cross-entropy)")
    ax.set_title("UID Scaling Law (v2.1): Iso-FLOP Comparison")
    ax.legend()
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path = output_dir / "scaling_curves.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"\n[ok] Plot saved to {out_path}")


# ======================================================================
# CLI
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families", nargs="+",
        default=["transformer", "transformer_plus_tricks", "cid_full"],
        choices=sorted(VALID_FAMILIES),
        help="Model families to compare. v2.1 adds cid_full_no_et "
             "(isolates §8.5 ET) and cid_full_fft_noise (isolates "
             "§14.2 OU).",
    )
    parser.add_argument(
        "--scales", nargs="+", default=["10M", "30M", "100M"],
        choices=sorted(SCALE_CONFIGS),
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
    )
    parser.add_argument(
        "--target_tokens_per_param", type=float, default=20.0,
        help="Chinchilla-optimal is ~20.",
    )
    parser.add_argument(
        "--data_path", type=str, required=True,
        help="Path to training data (JSONL).",
    )
    parser.add_argument("--max_seq_len", type=int, default=1024)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument(
        "--output_dir", type=str,
        default="./results/scaling_law_v2.1",
    )
    parser.add_argument("--tokenizer_path", type=str, required=True)

    # ----- v2.1 toggles (apply uniformly across all CID variants) -----
    parser.add_argument(
        "--noise_type", type=str, default="ou", choices=["ou", "fft"],
        help="Default colored-noise implementation for CID and "
             "transformer_plus_tricks (v2.1 default: 'ou').",
    )
    parser.add_argument(
        "--noise_tau", type=float, default=10.0,
        help="OU relaxation time (used when noise_type='ou').",
    )
    parser.add_argument(
        "--noise_beta", type=float, default=1.0,
        help="FFT spectral slope (used when noise_type='fft').",
    )
    parser.add_argument(
        "--no_et_symmetric", action="store_true",
        help="Disable §8.5 ET symmetric attention term globally "
             "(use with caution; ablations should use the dedicated "
             "'cid_full_no_et' family instead).",
    )

    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"

    # Load tokenizer and data.
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Build dataset (assume JSONL with {"text": ...}).
    from test_uid_on_minimind import PretrainJsonl
    dataset = PretrainJsonl(
        Path(args.data_path), tokenizer, max_length=args.max_seq_len
    )
    n = len(dataset)
    train_ds, eval_ds = torch.utils.data.random_split(
        dataset, [int(0.95 * n), n - int(0.95 * n)],
        generator=torch.Generator().manual_seed(42),
    )
    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
    )
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size)

    # Convert tokens-per-param to FLOPs-per-param.
    target_flops_per_param = 6.0 * args.target_tokens_per_param

    # Run experiment.
    output_dir = Path(args.output_dir)
    results = run_scaling_experiment(
        families=args.families,
        scales=args.scales,
        train_loader=train_loader,
        eval_loader=eval_loader,
        vocab_size=tokenizer.vocab_size,
        max_seq_len=args.max_seq_len,
        target_flops_per_param=target_flops_per_param,
        output_dir=output_dir,
        device=device,
        seeds=args.seeds,
        noise_type=args.noise_type,
        noise_tau=args.noise_tau,
        noise_beta=args.noise_beta,
        use_et_symmetric=not args.no_et_symmetric,
    )

    save_results(results, output_dir)
    plot_scaling_curves(results, output_dir)

    # Final analysis: print compact summary.
    print("\n" + "=" * 60)
    print("Scaling-Law Analysis (v2.1)")
    print("=" * 60)
    families_present = sorted(set(r.model_family for r in results))
    for f in families_present:
        fr = [r for r in results if r.model_family == f]
        print(f"\n{f}:")
        for r in sorted(fr, key=lambda x: x.non_emb_params):
            print(
                f"  {r.scale_name}: params={r.non_emb_params:,}, "
                f"loss={r.final_eval_loss:.4f}, "
                f"ppl={r.final_eval_ppl:.2f}"
            )


if __name__ == "__main__":
    main()
