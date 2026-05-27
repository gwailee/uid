# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
Run rigorous critical-exponent measurement (with noise injection OFF).

Usage:
    python experiments/run_critical_exponents.py \\
        --checkpoint results/scaling_law_v1.0/checkpoints/cid_full_100M.pt \\
        --data_path ./data/wikitext-2/test.jsonl \\
        --tokenizer_path gpt2 \\
        --output_dir results/critical_exponents_v1.0

This script:
1. Loads a trained model
2. Disables noise injection (CRITICAL — otherwise circular)
3. Collects hidden states from ≥10,000 sequences
4. Measures Hurst exponent (DFA), spectrum slope β, avalanche τ
5. Uses Clauset-Shalizi-Newman MLE for power-law fitting
6. Compares against a baseline model
7. Reports whether emergence is genuine
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from uid_theory.verification.critical_exponents import (
    run_critical_exponent_battery,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=str, required=True,
                        help="Path to trained CID model checkpoint")
    parser.add_argument("--baseline_checkpoint", type=str, default=None,
                        help="Optional baseline (e.g. trained Transformer)")
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--tokenizer_path", type=str, required=True)
    parser.add_argument("--max_seq_len", type=int, default=4096,
                        help="Use long sequences for proper DFA")
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--n_sequences", type=int, default=10000)
    parser.add_argument("--output_dir", type=str,
                        default="./results/critical_exponents_v1.0")
    args = parser.parse_args()
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load tokenizer and data
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer_path)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    
    from test_uid_on_minimind import PretrainJsonl
    dataset = PretrainJsonl(
        Path(args.data_path), tokenizer, max_length=args.max_seq_len
    )
    dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)
    
    # Load CID model
    print(f"Loading CID model from {args.checkpoint}")
    cid_ckpt = torch.load(args.checkpoint, map_location=device)
    from model.model_uid import UIDConfig, UIDModel
    cid_cfg = UIDConfig(**cid_ckpt["config"])
    cid_model = UIDModel(cid_cfg)
    cid_model.load_state_dict(cid_ckpt["model"])
    cid_model.to(device)
    
    all_results = {}
    
    # CRITICAL TEST 1: CID with noise injection OFF (true emergence test)
    print("\n" + "=" * 60)
    print("TEST 1: CID with noise injection DISABLED (emergence test)")
    print("=" * 60)
    cid_emergence = run_critical_exponent_battery(
        model=cid_model,
        model_name="cid_full_noise_OFF",
        dataloader=dataloader,
        device=device,
        n_sequences=args.n_sequences,
        disable_noise=True,
    )
    all_results["cid_emergence"] = cid_emergence.to_dict()
    
    # CONTROL TEST 2: CID with noise injection ON (should mirror injected pattern)
    print("\n" + "=" * 60)
    print("TEST 2: CID with noise injection ENABLED (sanity check)")
    print("=" * 60)
    cid_with_noise = run_critical_exponent_battery(
        model=cid_model,
        model_name="cid_full_noise_ON",
        dataloader=dataloader,
        device=device,
        n_sequences=args.n_sequences,
        disable_noise=False,
    )
    all_results["cid_with_noise"] = cid_with_noise.to_dict()
    
    # CONTROL TEST 3: Baseline (if provided)
    if args.baseline_checkpoint is not None:
        print("\n" + "=" * 60)
        print("TEST 3: Baseline Transformer (negative control)")
        print("=" * 60)
        from model.modern_transformer import ModernTransformerLM
        baseline_ckpt = torch.load(args.baseline_checkpoint, map_location=device)
        baseline = ModernTransformerLM(**baseline_ckpt["config"])
        baseline.load_state_dict(baseline_ckpt["model"])
        baseline.to(device)
        
        baseline_result = run_critical_exponent_battery(
            model=baseline,
            model_name="transformer_baseline",
            dataloader=dataloader,
            device=device,
            n_sequences=args.n_sequences,
            disable_noise=True,  # baseline has no noise injection anyway
        )
        all_results["baseline"] = baseline_result.to_dict()
    
    # Save results
    output_path = output_dir / "results.json"
    output_path.write_text(
        json.dumps(all_results, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Results saved to {output_path}")
    
    # Final verdict
    print("\n" + "=" * 60)
    print("VERDICT: Is CID's emergence genuine?")
    print("=" * 60)
    emerg_beta = cid_emergence.spectrum.beta_mean
    emerg_hurst = cid_emergence.hurst.hurst_mean
    print(f"\nCID with noise OFF (emergence test):")
    print(f"  β = {emerg_beta:.3f}   (UID predicts: 0.7-1.3)")
    print(f"  H = {emerg_hurst:.3f}  (UID predicts: 0.6-0.8)")
    
    beta_pass = 0.7 <= emerg_beta <= 1.3
    hurst_pass = 0.6 <= emerg_hurst <= 0.8
    
    if beta_pass and hurst_pass:
        print("\n  ✓ EMERGENCE CONFIRMED: critical exponents survive "
              "noise-off test")
    else:
        print("\n  ✗ EMERGENCE NOT CONFIRMED: critical exponents do not "
              "match UID predictions with noise OFF")
        print("  This suggests v0.1's 'verified' status was circular.")


if __name__ == "__main__":
    main()
