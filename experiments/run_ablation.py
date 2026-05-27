# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Run the full 9-way ablation suite.

Usage:
    python experiments/run_ablation.py \\
        --data_path ./data/wikitext-2/train.jsonl \\
        --tokenizer_path gpt2 \\
        --scale 30M \\
        --epochs 3 \\
        --seeds 42 43 44 \\
        --output_dir ./results/ablation_v1.0

This script runs all 9 ablation variants (4 CID + 5 Transformer-based) 
at a fixed scale, with multiple seeds, and computes the critical 
comparison: cid_full vs transformer_plus_all_tricks.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader

from uid_theory.verification.ablation_suite import (
    AblationConfig, build_ablation_model, get_ablation_configs,
)


def train_and_eval(
    model: nn.Module,
    train_loader: DataLoader,
    eval_loader: DataLoader,
    epochs: int,
    lr: float,
    device: str,
    log_every: int = 100,
) -> tuple[float, float, float]:
    """Train a model and return (final_train_loss, final_eval_loss, wall_time)."""
    model.to(device)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    
    start = time.time()
    for epoch in range(epochs):
        model.train()
        running = 0.0
        n_tok = 0
        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            optim.zero_grad()
            out = model(input_ids=input_ids, labels=labels)
            if out.loss is None or not torch.isfinite(out.loss):
                continue
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            
            ntok = int((labels != -100).sum().item())
            running += float(out.loss.item()) * ntok
            n_tok += ntok
            
            if step % log_every == 0:
                print(f"    ep{epoch} step{step} loss={float(out.loss.item()):.4f}")
        train_loss = running / max(n_tok, 1)
    
    # Eval
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument("--scale", type=str, default="30M",
                        choices=["10M", "30M", "100M"])
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--max_seq_len", type=int, default=1024)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--output_dir", type=str,
                        default="./results/ablation_v1.0")
    args = parser.parse_args()
    
    SCALE_CONFIGS = {
        "10M":  dict(hidden_size=256, num_layers=6,  num_heads=4),
        "30M":  dict(hidden_size=384, num_layers=8,  num_heads=6),
        "100M": dict(hidden_size=512, num_layers=12, num_heads=8),
    }
    cfg = SCALE_CONFIGS[args.scale]
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load tokenizer and data
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    from test_uid_on_minimind import PretrainJsonl
    full_dataset = PretrainJsonl(
        Path(args.data_path), tokenizer, max_length=args.max_seq_len
    )
    n = len(full_dataset)
    train_ds, eval_ds = torch.utils.data.random_split(
        full_dataset, [int(0.9 * n), n - int(0.9 * n)],
        generator=torch.Generator().manual_seed(42),
    )
    train_loader = DataLoader(train_ds, batch_size=args.batch_size,
                               shuffle=True)
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size)
    
    # Run all ablations
    configs = get_ablation_configs()
    all_results = []
    
    for config in configs:
        for seed in args.seeds:
            print(f"\n{'=' * 60}")
            print(f"Ablation: {config.name} (seed={seed})")
            print(f"  {config.description}")
            print(f"{'=' * 60}")
            
            torch.manual_seed(seed)
            np.random.seed(seed)
            
            model = build_ablation_model(
                config=config,
                vocab_size=tokenizer.vocab_size,
                hidden_size=cfg["hidden_size"],
                num_layers=cfg["num_layers"],
                num_heads=cfg["num_heads"],
                max_seq_len=args.max_seq_len,
            )
            
            n_params = sum(p.numel() for p in model.parameters())
            print(f"  Params: {n_params:,}")
            
            train_loss, eval_loss, wall = train_and_eval(
                model=model,
                train_loader=train_loader,
                eval_loader=eval_loader,
                epochs=args.epochs,
                lr=args.lr,
                device=device,
            )
            
            result = {
                "ablation_name": config.name,
                "description": config.description,
                "config": asdict(config),
                "scale": args.scale,
                "seed": seed,
                "n_params": n_params,
                "train_loss": train_loss,
                "eval_loss": eval_loss,
                "eval_ppl": float(np.exp(eval_loss)),
                "wall_seconds": wall,
            }
            all_results.append(result)
            print(f"  Result: train={train_loss:.4f}, eval={eval_loss:.4f}, "
                  f"ppl={result['eval_ppl']:.2f}")
            
            # Save incrementally
            (output_dir / "results.json").write_text(
                json.dumps(all_results, indent=2), encoding="utf-8"
            )
            
            del model
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
    
    # Final analysis
    print("\n" + "=" * 60)
    print("ABLATION ANALYSIS")
    print("=" * 60)
    
    # Group by ablation name
    by_name: dict = {}
    for r in all_results:
        by_name.setdefault(r["ablation_name"], []).append(r)
    
    summary = []
    for name, runs in by_name.items():
        losses = [r["eval_loss"] for r in runs]
        ppls = [r["eval_ppl"] for r in runs]
        summary.append({
            "ablation": name,
            "n_seeds": len(runs),
            "eval_loss_mean": float(np.mean(losses)),
            "eval_loss_std": float(np.std(losses)),
            "eval_ppl_mean": float(np.mean(ppls)),
            "eval_ppl_std": float(np.std(ppls)),
        })
    
    summary.sort(key=lambda x: x["eval_loss_mean"])
    
    print(f"\n{'Ablation':<35} {'Loss (mean±std)':<25} {'PPL (mean±std)':<25}")
    print("-" * 85)
    for s in summary:
        print(f"{s['ablation']:<35} "
              f"{s['eval_loss_mean']:.4f} ± {s['eval_loss_std']:.4f}      "
              f"{s['eval_ppl_mean']:.2f} ± {s['eval_ppl_std']:.2f}")
    
    # The CRITICAL comparison
    print("\n" + "=" * 60)
    print("CRITICAL COMPARISON: cid_full vs transformer_plus_all_tricks")
    print("=" * 60)
    cid_full = next((s for s in summary if s["ablation"] == "cid_full"), None)
    trans_tricks = next(
        (s for s in summary if s["ablation"] == "transformer_plus_all_tricks"),
        None,
    )
    if cid_full and trans_tricks:
        cid_loss = cid_full["eval_loss_mean"]
        trans_loss = trans_tricks["eval_loss_mean"]
        improvement = trans_loss - cid_loss
        # Statistical significance via simple two-sample t-test approximation
        cid_se = cid_full["eval_loss_std"] / np.sqrt(cid_full["n_seeds"])
        trans_se = trans_tricks["eval_loss_std"] / np.sqrt(trans_tricks["n_seeds"])
        combined_se = np.sqrt(cid_se ** 2 + trans_se ** 2)
        z_score = improvement / (combined_se + 1e-12)
        
        print(f"\n  cid_full eval loss:                  {cid_loss:.4f}")
        print(f"  transformer_plus_all_tricks loss:    {trans_loss:.4f}")
        print(f"  CID advantage:                       {improvement:+.4f}")
        print(f"  Approximate z-score:                 {z_score:.2f}")
        
        if improvement > 0 and abs(z_score) > 2.0:
            print("\n  ✓ CID provides SIGNIFICANT improvement over "
                  "Transformer + same tricks")
            print("    → UID's 'physical framework' contribution is supported")
        else:
            print("\n  ✗ CID does NOT significantly outperform "
                  "Transformer + same tricks")
            print("    → UID's 'physical framework' claim is FALSIFIED at "
                  f"this scale ({args.scale})")
            print("    → The benefit (if any) comes from the known tricks, "
                  "not the physical organization")
    
    # Save summary
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Summary saved to {output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
