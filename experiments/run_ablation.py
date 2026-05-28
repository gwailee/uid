# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * Now consumes the full 11-variant v2.1 ablation matrix
#     (4 traditional + 2 §8.5/§14.2 isolations + 5 baselines).
#   * Reports THREE critical comparisons, not just one:
#       A. cid_full vs transformer_plus_all_tricks
#          (UID physical framework vs known tricks)
#       B. cid_full vs cid_full_no_et
#          (§8.5 ET symmetric term's engineering contribution)
#       C. cid_full vs cid_full_fft_noise
#          (§14.2 OU vs FFT noise's engineering contribution)
"""
Run the full 11-way ablation suite (v2.1).

Usage:
    python experiments/run_ablation.py \\
        --data_path ./data/wikitext-2/train.jsonl \\
        --tokenizer_path gpt2 \\
        --scale 30M \\
        --epochs 3 \\
        --seeds 42 43 44 \\
        --output_dir ./results/ablation_v2.1

This script runs all 11 ablation variants at a fixed scale, with
multiple seeds, and computes THREE critical comparisons that map
directly to the predictions of Theory §8.5 / §14.2.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    """Train and return (final_train_loss, final_eval_loss, wall_seconds)."""
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
                print(
                    f"    ep{epoch} step{step} "
                    f"loss={float(out.loss.item()):.4f}"
                )
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


def _two_sample_z_score(
    a_mean: float, a_std: float, a_n: int,
    b_mean: float, b_std: float, b_n: int,
) -> float:
    """Approximate two-sample z-score for difference of means.

    Positive z means ``a`` is larger than ``b``.
    """
    a_se = a_std / np.sqrt(max(a_n, 1))
    b_se = b_std / np.sqrt(max(b_n, 1))
    combined_se = float(np.sqrt(a_se ** 2 + b_se ** 2) + 1e-12)
    return float((a_mean - b_mean) / combined_se)


def _print_critical_comparison(
    title: str,
    summary: List[Dict[str, Any]],
    name_a: str,
    name_b: str,
    success_msg: str,
    failure_msg: str,
    z_threshold: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Print one critical comparison between two ablation variants.

    Returns:
        A dict with the comparison fields, or None if either variant
        is missing from the summary.
    """
    a = next((s for s in summary if s["ablation"] == name_a), None)
    b = next((s for s in summary if s["ablation"] == name_b), None)
    if a is None or b is None:
        print(f"\n[skip] {title}: missing variant "
              f"({name_a} -> {'OK' if a else 'MISSING'}, "
              f"{name_b} -> {'OK' if b else 'MISSING'})")
        return None
    advantage = b["eval_loss_mean"] - a["eval_loss_mean"]
    z = _two_sample_z_score(
        b["eval_loss_mean"], b["eval_loss_std"], b["n_seeds"],
        a["eval_loss_mean"], a["eval_loss_std"], a["n_seeds"],
    )

    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(f"  {name_a:35s} eval_loss = {a['eval_loss_mean']:.4f} "
          f"(± {a['eval_loss_std']:.4f}, n={a['n_seeds']})")
    print(f"  {name_b:35s} eval_loss = {b['eval_loss_mean']:.4f} "
          f"(± {b['eval_loss_std']:.4f}, n={b['n_seeds']})")
    print(f"  advantage ({name_a} better by): {advantage:+.4f}")
    print(f"  approximate z-score:            {z:+.2f}")
    if advantage > 0 and abs(z) > z_threshold:
        print(f"  -> {success_msg}")
        verdict = "supported"
    else:
        print(f"  -> {failure_msg}")
        verdict = "falsified"

    return {
        "title": title,
        "name_a": name_a,
        "name_b": name_b,
        "loss_a": a["eval_loss_mean"],
        "loss_b": b["eval_loss_mean"],
        "advantage": advantage,
        "z_score": z,
        "verdict": verdict,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument(
        "--scale", type=str, default="30M",
        choices=["10M", "30M", "100M"],
    )
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
    )
    parser.add_argument("--max_seq_len", type=int, default=1024)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument(
        "--output_dir", type=str,
        default="./results/ablation_v2.1",
    )
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

    # Load tokenizer and data.
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
    train_loader = DataLoader(
        train_ds, batch_size=args.batch_size, shuffle=True,
    )
    eval_loader = DataLoader(eval_ds, batch_size=args.batch_size)

    # Run all ablations.
    configs = get_ablation_configs()
    print(f"\n[info] Running {len(configs)} ablation variants "
          f"x {len(args.seeds)} seeds = "
          f"{len(configs) * len(args.seeds)} total runs")
    all_results: List[Dict[str, Any]] = []

    for config in configs:
        for seed in args.seeds:
            print(f"\n{'=' * 60}")
            print(f"Ablation: {config.name} (seed={seed})")
            print(f"  {config.description}")
            print(f"  v2.1 toggles: noise_type={config.noise_type}, "
                  f"use_et_symmetric={config.use_et_symmetric}")
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
            print(
                f"  Result: train={train_loss:.4f}, eval={eval_loss:.4f}, "
                f"ppl={result['eval_ppl']:.2f}"
            )

            # Save incrementally.
            (output_dir / "results.json").write_text(
                json.dumps(all_results, indent=2), encoding="utf-8"
            )

            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("ABLATION SUMMARY (sorted by eval loss, lower = better)")
    print("=" * 60)

    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for r in all_results:
        by_name.setdefault(r["ablation_name"], []).append(r)

    summary: List[Dict[str, Any]] = []
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
        print(
            f"{s['ablation']:<35} "
            f"{s['eval_loss_mean']:.4f} ± {s['eval_loss_std']:.4f}      "
            f"{s['eval_ppl_mean']:.2f} ± {s['eval_ppl_std']:.2f}"
        )

    # ------------------------------------------------------------------
    # THREE CRITICAL COMPARISONS (v2.1)
    # ------------------------------------------------------------------
    comparisons: List[Dict[str, Any]] = []

    cmp_a = _print_critical_comparison(
        title=(
            "CRITICAL COMPARISON A: cid_full vs transformer_plus_all_tricks\n"
            "  (UID physical framework vs known tricks)"
        ),
        summary=summary,
        name_a="cid_full",
        name_b="transformer_plus_all_tricks",
        success_msg=(
            "CID provides SIGNIFICANT improvement over Transformer + same "
            "tricks. UID's 'physical framework' claim is SUPPORTED."
        ),
        failure_msg=(
            "CID does NOT significantly outperform Transformer + same "
            "tricks at this scale. UID's 'physical framework' claim is "
            "FALSIFIED at this scale; the benefit (if any) comes from "
            "known tricks, not physical organisation."
        ),
    )
    if cmp_a:
        comparisons.append(cmp_a)

    cmp_b = _print_critical_comparison(
        title=(
            "CRITICAL COMPARISON B: cid_full vs cid_full_no_et\n"
            "  (§8.5 ET symmetric term's engineering contribution)"
        ),
        summary=summary,
        name_a="cid_full",
        name_b="cid_full_no_et",
        success_msg=(
            "Disabling ET symmetric term DEGRADES performance. §8.5's "
            "engineering contribution is SUPPORTED."
        ),
        failure_msg=(
            "Disabling ET symmetric term does NOT significantly degrade "
            "performance. §8.5's engineering contribution is UNCLEAR at "
            "this scale (may still matter for Lyapunov stability)."
        ),
    )
    if cmp_b:
        comparisons.append(cmp_b)

    cmp_c = _print_critical_comparison(
        title=(
            "CRITICAL COMPARISON C: cid_full vs cid_full_fft_noise\n"
            "  (§14.2 OU vs FFT noise's engineering contribution)"
        ),
        summary=summary,
        name_a="cid_full",
        name_b="cid_full_fft_noise",
        success_msg=(
            "OU noise OUTPERFORMS FFT noise. §14.2's preference for OU "
            "as the default is SUPPORTED."
        ),
        failure_msg=(
            "OU noise does NOT significantly outperform FFT noise. "
            "§14.2's OU preference is UNCLEAR at this scale (may still "
            "matter for honest emergence measurement; see "
            "run_critical_exponents.py)."
        ),
    )
    if cmp_c:
        comparisons.append(cmp_c)

    # Save summary + comparisons.
    (output_dir / "summary.json").write_text(
        json.dumps(
            {"summary": summary, "critical_comparisons": comparisons},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[ok] Summary saved to {output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
