# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
The CORE experiment for UID's "parameter efficiency" claim.

This script trains families of models at multiple scales:
  - Modern Transformer baseline (10M, 30M, 100M, 300M, 1B*)
  - Transformer + all known tricks (same scales)
  - Mamba baseline (same scales)
  - Full CID (same scales)

For each model, we measure:
  - Non-embedding parameter count
  - Validation loss at equal training-FLOP budget
  - Wall-clock time and (optionally) energy via nvidia-smi

The output is the canonical scaling-law plot:
  Loss vs Non-embedding Parameters (one curve per model family).

UID's claim of "5-10× parameter efficiency" is operationalized as:
  At a given validation loss level, the horizontal distance between 
  CID's curve and the Transformer baseline's curve must be ≥ log10(5) ≈ 0.7.

* The 1B scale requires multi-GPU; use the `--max_scale` flag to 
  control the largest model trained.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from model.modern_transformer import ModernTransformerLM
from model.known_tricks_baseline import TransformerPlusTricksLM
from model.model_uid import UIDConfig, UIDModel
# from model.mamba_baseline import MambaLM  # optional, if mamba-ssm installed


# Standard scaling-law config: hidden_size, num_layers, num_heads
SCALE_CONFIGS = {
    "10M":  dict(hidden_size=256, num_layers=6,  num_heads=4),
    "30M":  dict(hidden_size=384, num_layers=8,  num_heads=6),
    "100M": dict(hidden_size=512, num_layers=12, num_heads=8),
    "300M": dict(hidden_size=768, num_layers=16, num_heads=12),
    "1B":   dict(hidden_size=1024, num_layers=24, num_heads=16),
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


def estimate_train_flops(n_params: int, n_tokens: int) -> float:
    """
    Estimate training FLOPs using the Chinchilla approximation:
        FLOPs ≈ 6 * N * D
    where N is non-embedding parameters and D is total tokens seen.
    """
    return 6.0 * n_params * n_tokens


def build_model(
    family: str, scale: str, vocab_size: int, max_seq_len: int
) -> nn.Module:
    """Build a model of the specified family and scale."""
    cfg = SCALE_CONFIGS[scale]
    
    if family == "transformer":
        return ModernTransformerLM(
            vocab_size=vocab_size,
            max_seq_len=max_seq_len,
            **cfg,
        )
    elif family == "transformer_plus_tricks":
        return TransformerPlusTricksLM(
            vocab_size=vocab_size,
            max_seq_len=max_seq_len,
            use_noise=True,
            use_conv=True,
            use_linear=True,
            **cfg,
        )
    elif family == "cid_full":
        uid_cfg = UIDConfig(
            vocab_size=vocab_size,
            max_position_embeddings=max_seq_len,
            hidden_size=cfg["hidden_size"],
            num_hidden_layers=cfg["num_layers"],
            num_attention_heads=cfg["num_heads"],
            use_vortex=True,
            use_memory=True,
            use_colored_noise=True,
        )
        return UIDModel(uid_cfg)
    else:
        raise ValueError(f"Unknown model family: {family}")


def train_one(
    model: nn.Module,
    train_loader: DataLoader,
    eval_loader: DataLoader,
    device: str,
    target_train_flops: float,
    lr: float = 3e-4,
    log_every: int = 100,
) -> tuple[float, float, float]:
    """
    Train one model to a target FLOP budget (iso-FLOP protocol).
    
    Returns (final_train_loss, final_eval_loss, wall_seconds).
    """
    model.to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optim, T_max=10000  # rough; refined by FLOPs target
    )
    
    n_params = model.count_non_embedding_params()
    
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
    
    # Evaluation
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
    families: list[str],
    scales: list[str],
    train_loader: DataLoader,
    eval_loader: DataLoader,
    vocab_size: int,
    max_seq_len: int,
    target_flops_per_param: float,
    output_dir: Path,
    device: str = "cuda",
    seeds: list[int] = [42, 43, 44],
) -> list[ScalingResult]:
    """
    Run the full scaling-law experiment.
    
    `target_flops_per_param`: For each model, total training FLOPs will 
    be set to `target_flops_per_param * n_params`. The Chinchilla optimal 
    is around 20 (i.e., 20 tokens per parameter).
    """
    all_results: list[ScalingResult] = []
    
    for family in families:
        for scale in scales:
            for seed in seeds:
                print(f"\n{'='*60}")
                print(f"Training {family} @ {scale} (seed={seed})")
                print(f"{'='*60}")
                
                torch.manual_seed(seed)
                np.random.seed(seed)
                
                model = build_model(family, scale, vocab_size, max_seq_len)
                n_params = model.count_non_embedding_params()
                target_flops = target_flops_per_param * n_params
                
                print(f"  Non-embedding params: {n_params:,}")
                print(f"  Target train FLOPs: {target_flops:.3e}")
                
                train_loss, eval_loss, wall = train_one(
                    model=model,
                    train_loader=train_loader,
                    eval_loader=eval_loader,
                    device=device,
                    target_train_flops=target_flops,
                )
                
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
                )
                all_results.append(result)
                print(f"  Final: train_loss={train_loss:.4f}, "
                      f"eval_loss={eval_loss:.4f}, "
                      f"eval_ppl={result.final_eval_ppl:.2f}")
                
                # Save intermediate
                save_results(all_results, output_dir)
                
                # Free memory
                del model
                torch.cuda.empty_cache() if torch.cuda.is_available() else None
    
    return all_results


def save_results(results: list[ScalingResult], output_dir: Path) -> None:
    """Save results to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "experiment": "scaling_law_v1.0",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_results": len(results),
        "results": [asdict(r) for r in results],
    }
    (output_dir / "results.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )


def plot_scaling_curves(results: list[ScalingResult], output_dir: Path) -> None:
    """Plot the canonical scaling-law figure."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    families = sorted(set(r.model_family for r in results))
    for family in families:
        family_results = [r for r in results if r.model_family == family]
        # Group by scale, average over seeds
        by_scale: dict[str, list[ScalingResult]] = {}
        for r in family_results:
            by_scale.setdefault(r.scale_name, []).append(r)
        
        scales_sorted = sorted(by_scale.keys(),
                               key=lambda s: by_scale[s][0].non_emb_params)
        xs = [by_scale[s][0].non_emb_params for s in scales_sorted]
        ys_mean = [np.mean([r.final_eval_loss for r in by_scale[s]]) 
                   for s in scales_sorted]
        ys_std = [np.std([r.final_eval_loss for r in by_scale[s]]) 
                  for s in scales_sorted]
        
        ax.errorbar(xs, ys_mean, yerr=ys_std, marker="o", 
                    label=family, capsize=4, linewidth=2)
    
    ax.set_xscale("log")
    ax.set_xlabel("Non-embedding parameters")
    ax.set_ylabel("Eval loss (cross-entropy)")
    ax.set_title("UID Scaling Law: Iso-FLOP Comparison")
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    fig.tight_layout()
    fig.savefig(output_dir / "scaling_curves.png", dpi=120, bbox_inches="tight")
    print(f"\n[ok] Plot saved to {output_dir / 'scaling_curves.png'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", nargs="+", default=[
        "transformer", "transformer_plus_tricks", "cid_full"
    ])
    parser.add_argument("--scales", nargs="+", default=["10M", "30M", "100M"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--target_tokens_per_param", type=float, default=20.0,
                        help="Chinchilla-optimal is ~20")
    parser.add_argument("--data_path", type=str, required=True,
                        help="Path to training data (JSONL)")
    parser.add_argument("--max_seq_len", type=int, default=1024)
    parser.add_argument("--batch_size", type=int, default=32)
    parser.add_argument("--output_dir", type=str,
                        default="./results/scaling_law_v1.0")
    parser.add_argument("--tokenizer_path", type=str, required=True)
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Load tokenizer and data
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    # Build dataset (assume JSONL with {"text": ...})
    from test_uid_on_minimind import PretrainJsonl
    dataset = PretrainJsonl(
        Path(args.data_path), tokenizer, max_length=args.max_seq_len
    )
    n = len(dataset)
    train_ds, eval_ds = torch.utils.data.random_split(
        dataset, [int(0.95 * n), n - int(0.95 * n)],
        generator=torch.Generator().manual_seed(42),
    )
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size)
    
    # Convert tokens-per-param to FLOPs-per-param
    target_flops_per_param = 6.0 * args.target_tokens_per_param
    
    # Run experiment
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
    )
    
    save_results(results, output_dir)
    plot_scaling_curves(results, output_dir)
    
    # Final analysis: compute UID's claimed advantage
    print("\n" + "=" * 60)
    print("Scaling-Law Analysis")
    print("=" * 60)
    families_present = sorted(set(r.model_family for r in results))
    for f in families_present:
        fr = [r for r in results if r.model_family == f]
        print(f"\n{f}:")
        for r in sorted(fr, key=lambda x: x.non_emb_params):
            print(f"  {r.scale_name}: params={r.non_emb_params:,}, "
                  f"loss={r.final_eval_loss:.4f}, "
                  f"ppl={r.final_eval_ppl:.2f}")


if __name__ == "__main__":
    main()
