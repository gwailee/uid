# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-05-28
#   * Load checkpoints in the v2.1 unified schema produced by
#     run_scaling_law.py (init_kwargs + config_dict + model_state).
#   * Accept --scale / --seeds and auto-discover matching checkpoints
#     instead of relying on legacy `{family}.pt` filenames.
"""
Run real hardware energy benchmark (v2.1 unified checkpoint schema).

Usage:
    python experiments/run_energy_benchmark.py \\
        --families cid_full transformer transformer_plus_all_tricks \\
        --checkpoint_dir ./results/scaling_law_v2.1/checkpoints \\
        --scale 100M \\
        --seeds 42 \\
        --batch_size 16 \\
        --seq_len 1024 \\
        --output_dir ./results/energy_v2.1

Replaces v0.1's theoretical Landauer-limit arithmetic with actual
nvidia-smi power measurements during inference.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

from uid_theory.verification.energy_meter import measure_inference_energy


# ======================================================================
# Unified v2.1 checkpoint loader (mirrors run_critical_exponents.py)
# ======================================================================


def _load_model_from_unified_ckpt(ckpt_path: Path, device: str):
    """Rebuild a model from the v2.1 unified checkpoint schema."""
    ckpt = torch.load(ckpt_path, map_location=device)

    if ckpt.get("schema_version") == "v2.1":
        init_kwargs = ckpt["init_kwargs"]
        from experiments.run_scaling_law import build_model  # type: ignore
        model = build_model(
            family=init_kwargs["family"],
            scale=init_kwargs["scale"],
            vocab_size=init_kwargs["vocab_size"],
            max_seq_len=init_kwargs["max_seq_len"],
            noise_type=init_kwargs.get("noise_type", "ou"),
            noise_tau=init_kwargs.get("noise_tau", 10.0),
            noise_beta=init_kwargs.get("noise_beta", 1.0),
            use_et_symmetric=init_kwargs.get("use_et_symmetric", True),
        )
        model.load_state_dict(ckpt["model_state"])
        model.to(device)
        return model, ckpt["model_family"]

    # Legacy fallback.
    if "config" in ckpt and "model" in ckpt:
        # Heuristic: infer family from filename prefix.
        name = ckpt_path.stem
        if name.startswith("cid"):
            from model.model_uid import UIDConfig, UIDModel
            cfg = UIDConfig(**ckpt["config"])
            model = UIDModel(cfg)
        elif name.startswith("transformer_plus"):
            from model.known_tricks_baseline import TransformerPlusTricksLM
            model = TransformerPlusTricksLM(**ckpt["config"])
        else:
            from model.modern_transformer import ModernTransformerLM
            model = ModernTransformerLM(**ckpt["config"])
        model.load_state_dict(ckpt["model"])
        model.to(device)
        return model, name.split("_seed")[0]

    raise RuntimeError(
        f"Could not interpret checkpoint at {ckpt_path}; expected "
        "v2.1 unified schema or legacy {'config', 'model'} schema."
    )


def _find_checkpoint(
    ckpt_dir: Path,
    family: str,
    scale: str,
    seed_preference: List[int],
) -> Optional[Path]:
    """Locate `{family}_{scale}_seed{seed}.pt` preferring earlier seeds."""
    for seed in seed_preference:
        candidate = ckpt_dir / f"{family}_{scale}_seed{seed}.pt"
        if candidate.exists():
            return candidate
    # Fallback: any matching `{family}_{scale}_seed*.pt`.
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    if matches:
        return matches[0]
    # Last resort: legacy `{family}.pt`.
    legacy = ckpt_dir / f"{family}.pt"
    return legacy if legacy.exists() else None


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families", nargs="+",
        default=[
            "cid_full", "transformer", "transformer_plus_all_tricks",
        ],
        help="Model families to benchmark.",
    )
    parser.add_argument(
        "--checkpoint_dir", type=str, required=True,
        help="Directory containing v2.1 unified checkpoints.",
    )
    parser.add_argument(
        "--scale", type=str, default="100M",
        help="Which scale to load (must match scaling_law output).",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44],
        help="Seed preference order when picking a checkpoint.",
    )
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--seq_len", type=int, default=1024)
    parser.add_argument(
        "--vocab_size", type=int, default=50257,
        help="Used to generate random input tokens.",
    )
    parser.add_argument("--n_warmup", type=int, default=50)
    parser.add_argument("--n_measure", type=int, default=500)
    parser.add_argument(
        "--output_dir", type=str, default="./results/energy_v2.1",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("Energy benchmark requires NVIDIA GPU")
    device = "cuda"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate input batch.
    input_ids = torch.randint(
        0, args.vocab_size,
        (args.batch_size, args.seq_len),
        device=device,
    )

    ckpt_dir = Path(args.checkpoint_dir)
    results: Dict[str, Any] = {}

    for name in args.families:
        ckpt_path = _find_checkpoint(
            ckpt_dir, family=name, scale=args.scale,
            seed_preference=args.seeds,
        )
        if ckpt_path is None:
            print(
                f"[warn] No checkpoint for family='{name}' scale="
                f"'{args.scale}' under {ckpt_dir}; skipping"
            )
            continue

        print(f"\n{'=' * 60}")
        print(f"Benchmarking: {name}  ({ckpt_path.name})")
        print(f"{'=' * 60}")

        model, loaded_family = _load_model_from_unified_ckpt(
            ckpt_path, device,
        )

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
        print(
            f"  Energy per token: "
            f"{result.energy_per_token_joules:.6f} J"
        )

        results[name] = {
            **result.to_dict(),
            "checkpoint": str(ckpt_path),
            "loaded_family": loaded_family,
        }

        del model
        torch.cuda.empty_cache()

    # Save and analyse.
    output_path = output_dir / "results.json"
    output_path.write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"\n[ok] Results saved to {output_path}")

    # Compute energy ratios.
    print("\n" + "=" * 60)
    print("Energy Comparison (lower is better)")
    print("=" * 60)
    if "transformer" in results:
        baseline_energy = results["transformer"]["energy_per_token_joules"]
        print(f"\nBaseline (transformer): {baseline_energy:.6f} J/token")
        for name in results:
            if name == "transformer":
                continue
            r = (
                baseline_energy
                / results[name]["energy_per_token_joules"]
            )
            print(f"  {name}: {r:.2f}x more efficient than baseline")

            # UID-specific claim check.
            if name == "cid_full":
                if r >= 3.0:
                    print("    [ok] UID A4 claim met (>= 3x efficiency)")
                else:
                    print(
                        f"    [fail] UID A4 claim NOT met "
                        f"(needs >= 3x, got {r:.2f}x)"
                    )


if __name__ == "__main__":
    main()
