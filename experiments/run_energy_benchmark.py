# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Run real hardware energy benchmark.

Usage:
    python experiments/run_energy_benchmark.py \\
        --models cid_full,transformer,transformer_plus_all_tricks \\
        --checkpoint_dir ./results/scaling_law_v1.0/checkpoints \\
        --batch_size 16 \\
        --seq_len 1024 \\
        --output_dir ./results/energy_v1.0

Replaces v0.1's theoretical Landauer-limit arithmetic with actual 
nvidia-smi power measurements during inference.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from uid_theory.verification.energy_meter import measure_inference_energy


def load_model_from_checkpoint(
    checkpoint_path: Path, model_family: str, device: str
):
    """Load a model from checkpoint based on family."""
    ckpt = torch.load(checkpoint_path, map_location=device)
    
    if model_family == "cid_full":
        from model.model_uid import UIDConfig, UIDModel
        cfg = UIDConfig(**ckpt["config"])
        model = UIDModel(cfg)
    elif model_family == "transformer":
        from model.modern_transformer import ModernTransformerLM
        model = ModernTransformerLM(**ckpt["config"])
    elif model_family == "transformer_plus_all_tricks":
        from model.known_tricks_baseline import TransformerPlusTricksLM
        model = TransformerPlusTricksLM(**ckpt["config"])
    else:
        raise ValueError(f"Unknown family: {model_family}")
    
    model.load_state_dict(ckpt["model"])
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=str,
                        default="cid_full,transformer,transformer_plus_all_tricks",
                        help="Comma-separated model names")
    parser.add_argument("--checkpoint_dir", type=str, required=True)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--seq_len", type=int, default=1024)
    parser.add_argument("--vocab_size", type=int, default=50257,
                        help="Used to generate random input")
    parser.add_argument("--n_warmup", type=int, default=50)
    parser.add_argument("--n_measure", type=int, default=500)
    parser.add_argument("--output_dir", type=str,
                        default="./results/energy_v1.0")
    args = parser.parse_args()
    
    device = "cuda"
    if not torch.cuda.is_available():
        raise RuntimeError("Energy benchmark requires NVIDIA GPU")
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate input batch
    input_ids = torch.randint(
        0, args.vocab_size,
        (args.batch_size, args.seq_len),
        device=device,
    )
    
    model_names = [m.strip() for m in args.models.split(",")]
    results = {}
    
    for name in model_names:
        ckpt_path = Path(args.checkpoint_dir) / f"{name}.pt"
        if not ckpt_path.exists():
            print(f"[warn] Checkpoint {ckpt_path} not found, skipping")
            continue
        
        print(f"\n{'=' * 60}")
        print(f"Benchmarking: {name}")
        print(f"{'=' * 60}")
        
        model = load_model_from_checkpoint(ckpt_path, name, device)
        
        result = measure_inference_energy(
            model=model,
            model_name=name,
            input_ids=input_ids,
            n_warmup=args.n_warmup,
            n_measure=args.n_measure,
            device=device,
        )
        
        print(f"\n  Average power: {result.avg_power_watts:.2f} W")
        print(f"  Total energy: {result.total_energy_joules:.3f} J")
        print(f"  Energy per token: {result.energy_per_token_joules:.6f} J")
        
        results[name] = result.to_dict()
        
        del model
        torch.cuda.empty_cache()
    
    # Save and analyze
    output_path = output_dir / "results.json"
    output_path.write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Results saved to {output_path}")
    
    # Compute energy ratios
    print("\n" + "=" * 60)
    print("Energy Comparison (lower is better)")
    print("=" * 60)
    if "transformer" in results:
        baseline_energy = results["transformer"]["energy_per_token_joules"]
        print(f"\nBaseline (Transformer): {baseline_energy:.6f} J/token")
        for name in results:
            if name == "transformer":
                continue
            ratio = baseline_energy / results[name]["energy_per_token_joules"]
            print(f"  {name}: {ratio:.2f}× more efficient than baseline")
            
            # UID-specific claim check
            if name == "cid_full":
                if ratio >= 3.0:
                    print(f"    ✓ UID A4 claim met (≥3× efficiency)")
                else:
                    print(f"    ✗ UID A4 claim NOT met "
                          f"(needs ≥3×, got {ratio:.2f}×)")


if __name__ == "__main__":
    main()
