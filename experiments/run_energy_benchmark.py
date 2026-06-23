# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
# UPDATE: 2026-06-20 (v2.2 — iso-performance rewrite, native scaling parser)
#   * REWRITE of the comparison layer. The old comparison computed an
#     ISO-PARAMETER energy ratio and judged cid_full against a hard-coded
#     ">=3x" threshold ("A4"). Because cid_full at EQUAL parameters is
#     slower / heavier (but far more accurate), that comparison would
#     always print "FAIL A4" — i.e. the script contradicted the theory's
#     own energy-bonus claim (C13/C14), which is defined at
#     ISO-PERFORMANCE, not iso-parameter.
#
#   New design:
#     1. Energy MEASUREMENT hardened:
#        - robust idle baseline measured ONCE (settle clocks + multi-window
#          median) and SHARED across families, fixing the observed
#          211W-vs-124W idle discrepancy that made above-idle non-comparable;
#        - decode mode is the recommended/default mode; the per-token
#          denominator is recorded explicitly (new tokens for decode).
#     2. Energy COMPARISON reported in THREE honest views:
#        - iso-parameter : same #params (overhead baseline; NEUTRAL, no verdict)
#        - iso-FLOPs proxy: wall-clock & param ratios (matched-compute context)
#        - iso-performance: THE decisive one — energy/token at a TARGET
#          perplexity, with each family's params read off its scaling-law
#          curve (log-param vs ppl interpolation; NO extrapolation).
#     3. The ">=3x energy efficiency" verdict (C13) is evaluated ONLY against
#        the iso-performance ratio.
#     4. The scaling-law parser reads run_scaling_law.py's NATIVE output
#        natively: a top-level LIST of ScalingResult dicts
#        (model_family / non_emb_params / final_eval_ppl), averaging seeds.
#        It still accepts pre-aggregated {"summary": [...]} / {"results": {...}}.
"""
Real-hardware energy benchmark (v2.2) — RESUMABLE, iso-performance aware.

Usage (measure + all three comparison views):
    python experiments/run_energy_benchmark.py \\
        --families cid_full transformer transformer_plus_tricks \\
        --checkpoint_dir ./results/scaling_law_v2.1/checkpoints \\
        --scale 100M --seeds 42 \\
        --mode decode --new_tokens_per_decode 64 \\
        --batch_size 16 --seq_len 1024 \\
        --scaling_law_json ./results/scaling_law_v2.1/results.json \\
        --target_ppl 23.6 \\
        --output_dir ./results/energy_v2.2 \\
        --resume

The iso-performance column (the decisive C13 test) requires both
--scaling_law_json and --target_ppl. Without them the script still prints
the neutral iso-parameter overhead columns but refuses to issue any
energy-efficiency verdict.

IMPORTANT — family naming must match the checkpoints produced by
run_scaling_law.py (it uses 'transformer_plus_tricks', NOT
'transformer_plus_all_tricks'). A mismatch silently skips the family.

RESUME BEHAVIOR (--resume):
  * Families already present in <output_dir>/results.json are skipped.
  * If ALL requested families are present, comparison is printed and we exit.
  * New family results are merged (not overwritten) into results.json.
  * Delete results.json (or output_dir) to force a full re-run.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

from uid_theory.verification.energy_meter import (
    EnergyMeasurement,
    measure_inference_energy,
)


# ======================================================================
# Unified v2.1 checkpoint loader  (unchanged contract)
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


def _count_params(model: torch.nn.Module, non_embedding: bool = True) -> int:
    """Count parameters, by default excluding token/position embeddings so
    the count matches run_scaling_law.py's 'non_emb_params' convention."""
    embed_markers = ("embed", "wte", "wpe", "tok_emb", "pos_emb")
    total = 0
    for n, p in model.named_parameters():
        if non_embedding and any(m in n.lower() for m in embed_markers):
            continue
        total += p.numel()
    return total


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
    matches = sorted(ckpt_dir.glob(f"{family}_{scale}_seed*.pt"))
    if matches:
        return matches[0]
    legacy = ckpt_dir / f"{family}.pt"
    return legacy if legacy.exists() else None

def _discover_min_max_positions(
    families, ckpt_dir: Path, scale: str, seeds, device: str,
) -> Optional[int]:
    """Peek each family's checkpoint init_kwargs for max_seq_len and return
    the MINIMUM across families (the binding constraint). Best-effort: any
    family whose limit can't be read is ignored."""
    limits = []
    for fam in families:
        ck = _find_checkpoint(ckpt_dir, fam, scale, list(seeds))
        if ck is None:
            continue
        try:
            blob = torch.load(ck, map_location="cpu")
            ik = blob.get("init_kwargs", {})
            m = ik.get("max_seq_len")
            if m:
                limits.append(int(m))
        except Exception:
            continue
    return min(limits) if limits else None

# ======================================================================
# Resume helpers
# ======================================================================


def _load_existing_output(output_path: Path) -> Dict[str, Any]:
    if not output_path.exists():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[resume] WARNING: could not parse {output_path} ({e}); "
              f"starting fresh.")
        return {}


# ======================================================================
# Hardened, SHARED idle-baseline measurement
# (uses the REAL _PowerSampler API: _build_sampler / start / snapshot / stop)
# ======================================================================


def _robust_idle_power_watts(
    sampler_preference: str,
    sample_rate_hz: float,
    window_seconds: float,
    n_windows: int = 3,
    settle_seconds: float = 2.0,
    device_index: int = 0,
) -> Dict[str, float]:
    """Measure idle GPU power ROBUSTLY.

    The old code took a single idle window per family. Because GPUs ramp
    clocks down slowly, the first family's "idle" can be tens of watts
    higher than a later family's (we observed 211 W vs 124 W on the same
    4090), making the above-idle column non-comparable.

    Fix: force the device quiescent, wait for clocks to settle, take
    several windows, and use the MEDIAN of per-window median power. Spread
    is returned so callers can detect a non-quiescent baseline.
    """
    from uid_theory.verification.energy_meter import _build_sampler  # type: ignore

    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    time.sleep(settle_seconds)  # let clocks ramp down

    window_medians: List[float] = []
    for _ in range(max(1, n_windows)):
        sampler = _build_sampler(
            device_index=device_index,
            requested_rate_hz=sample_rate_hz,
            prefer=sampler_preference,
        )
        sampler.start()
        try:
            time.sleep(window_seconds)
        finally:
            sampler.stop()
        _ts, pw = sampler.snapshot()
        if pw:
            pw_sorted = sorted(pw)
            window_medians.append(pw_sorted[len(pw_sorted) // 2])
        time.sleep(0.5)

    if not window_medians:
        return {"idle_power_watts": 0.0, "idle_spread_watts": 0.0,
                "idle_n_windows": 0.0}

    window_medians.sort()
    median = window_medians[len(window_medians) // 2]
    spread = max(window_medians) - min(window_medians)
    return {
        "idle_power_watts": float(median),
        "idle_spread_watts": float(spread),
        "idle_n_windows": float(len(window_medians)),
    }


# ======================================================================
# Pretty printing of a single measurement (dict-based, robust)
# ======================================================================


def _print_measurement(rec: Dict[str, Any], denom_kind: str) -> None:
    def g(k, default=0.0):
        v = rec.get(k, default)
        return v if v is not None else default

    print()
    print(f"  --- {g('model_name', 'model')} ({g('mode', '?')}) ---")
    print(f"  Sampler            : {g('sampler', '?')}")
    print(f"  GPU                : {g('gpu_name', '?')} ({g('device', '?')})")
    print(
        f"  Sampling rate      : {g('sample_rate_hz'):.1f} Hz "
        f"({int(g('n_samples'))} samples in {g('wall_clock_seconds'):.3f} s)"
    )
    print(
        f"  Warmup / measure   : {int(g('n_warmup'))} / {int(g('n_measure'))} "
        f"(batch={int(g('batch_size'))}, seq_len={int(g('seq_len'))}, "
        f"new_tokens={int(g('new_tokens_per_decode'))})"
    )
    if rec.get("idle_power_shared"):
        print(
            f"  Idle baseline      : {g('idle_power_watts'):>7.2f} W "
            f"(SHARED robust median; meter-local was "
            f"{g('idle_power_watts_meter'):.2f} W)"
        )
    else:
        print(
            f"  Idle baseline      : {g('idle_power_watts'):>7.2f} W "
            f"({g('idle_window_seconds'):.2f} s window)"
        )
    print(
        f"  Avg power (work)   : {g('avg_power_watts'):>7.2f} W "
        f"  (peak {g('max_power_watts'):>7.2f} W)"
    )
    print(f"  Above-idle power   : {g('power_above_idle_watts'):>7.2f} W")
    print(
        f"  Total energy       : {g('total_energy_joules'):>10.4f} J  "
        f"(above idle: {g('energy_above_idle_joules'):>10.4f} J)"
    )
    print(f"  Tokens ({denom_kind:<9s}): {int(g('total_tokens')):,}")
    print(
        f"  Energy / token     : {g('energy_per_token_joules')*1e3:>10.4f} mJ"
        f"  (above idle: "
        f"{g('energy_per_token_above_idle_joules')*1e3:>10.4f} mJ)"
    )
    if rec.get("n_params_non_embedding"):
        print(f"  #params (non-embed): {int(rec['n_params_non_embedding']):,}")
    notes = rec.get("notes") or []
    if notes:
        print("  Notes:")
        for n in notes:
            print(f"    - {n}")


# ======================================================================
# Scaling-law curve helpers (for iso-performance comparison)
# ======================================================================


def _load_scaling_curves(
    scaling_law_json: Path,
    ppl_field: str,
    params_field: str,
) -> Dict[str, List[Tuple[float, float]]]:
    """Parse a scaling-law results file into per-family curves.

    Returns: {family: [(n_params, ppl), ...] sorted by n_params}.

    Accepts THREE shapes:
      (a) {"summary": [{family-key, params-field, ppl-field}, ...]}
      (b) {"results": {family: <rec>}}  or  {family: {scale: <rec>}}
      (c) [ ScalingResult-as-dict, ... ]   <-- run_scaling_law.py NATIVE output
          (top-level LIST; fields: model_family / non_emb_params /
           final_eval_ppl). Multiple seeds per (family, scale) are AVERAGED.

    Field names are resolved with fallbacks, so a single parser works for
    both the native schema and any pre-aggregated summary.
    """
    blob = json.loads(scaling_law_json.read_text(encoding="utf-8"))

    fam_keys = ("model_family", "family", "ablation", "name")
    params_keys = (params_field, "non_emb_params", "n_params",
                   "n_params_non_embedding")
    ppl_keys = (ppl_field, "final_eval_ppl", "eval_ppl_mean", "eval_ppl")

    def _pick(d: Dict[str, Any], keys) -> Any:
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return None

    # Accumulate raw points, then average duplicate (family, params) across
    # seeds so multi-seed scaling runs collapse to one point per size.
    raw: Dict[str, Dict[float, List[float]]] = {}

    def _add(fam: Any, p: Any, q: Any):
        if fam is None:
            return
        try:
            pf, qf = float(p), float(q)
        except (TypeError, ValueError):
            return
        if pf > 0 and qf > 0 and math.isfinite(pf) and math.isfinite(qf):
            raw.setdefault(str(fam), {}).setdefault(pf, []).append(qf)

    def _consume(rec: Dict[str, Any]):
        _add(_pick(rec, fam_keys),
             _pick(rec, params_keys),
             _pick(rec, ppl_keys))

    if isinstance(blob, list):
        # (c) native run_scaling_law.py output
        for rec in blob:
            if isinstance(rec, dict):
                _consume(rec)
    elif isinstance(blob, dict):
        if isinstance(blob.get("summary"), list):
            for rec in blob["summary"]:
                if isinstance(rec, dict):
                    _consume(rec)
        if isinstance(blob.get("results"), dict):
            for fam, val in blob["results"].items():
                if not isinstance(val, dict):
                    continue
                sub = list(val.values())
                recs = (sub if (sub and all(isinstance(v, dict) for v in sub))
                        else [val])
                for rec in recs:
                    if isinstance(rec, dict):
                        rec = {**rec}
                        rec.setdefault("model_family", fam)
                        _consume(rec)

    curves: Dict[str, List[Tuple[float, float]]] = {}
    for fam, by_p in raw.items():
        pts = [(p, sum(qs) / len(qs)) for p, qs in by_p.items()]
        pts.sort(key=lambda t: t[0])
        curves[fam] = pts

    if not curves:
        print(f"[iso-perf] WARNING: no usable (params, ppl) points parsed "
              f"from {scaling_law_json}. Tried family keys {fam_keys}, "
              f"params keys {params_keys}, ppl keys {ppl_keys}.")
    return curves


def _params_at_target_ppl(
    curve: List[Tuple[float, float]],
    target_ppl: float,
) -> Optional[float]:
    """Estimate #params needed to reach target_ppl by interpolating in
    (log10 params) vs ppl. Returns None if target is OUTSIDE the measured
    range — we deliberately do NOT extrapolate (extrapolation is how
    scaling claims fool themselves)."""
    if not curve:
        return None
    if len(curve) == 1:
        return curve[0][0] if abs(curve[0][1] - target_ppl) < 1e-6 else None

    pts = sorted(curve, key=lambda t: t[1])  # sort by ppl ascending
    for (p_a, q_a), (p_b, q_b) in zip(pts, pts[1:]):
        lo, hi = min(q_a, q_b), max(q_a, q_b)
        if lo - 1e-9 <= target_ppl <= hi + 1e-9 and q_a != q_b:
            t = (target_ppl - q_a) / (q_b - q_a)
            log_p = math.log10(p_a) + t * (math.log10(p_b) - math.log10(p_a))
            return 10.0 ** log_p
    return None  # outside measured range


def _largest_curve_params(curve: List[Tuple[float, float]]) -> Optional[float]:
    """Fallback param count when a benchmarked checkpoint's #params was not
    recorded: assume it is the largest trained point on the curve."""
    return max(curve, key=lambda t: t[0])[0] if curve else None


def _rescale_energy_to_params(
    *, measured_energy: float,
    measured_params: Optional[float],
    target_params: Optional[float],
) -> Tuple[float, bool]:
    """E_iso = E_measured * (target_params / measured_params).

    Per-token FLOPs ~ #params for these fixed-shape families, so energy
    scales ~linearly with params at fixed sequence length. Returns
    (energy, exact) where exact=False means we lacked a measured param
    count and returned the energy unscaled (a degraded, flagged estimate).
    """
    if not measured_params or not target_params or measured_params <= 0:
        return measured_energy, False
    return measured_energy * (target_params / measured_params), True


# ======================================================================
# Comparison: three honest views
# ======================================================================


def _print_comparison(
    results: Dict[str, Dict[str, Any]],
    *,
    scaling_curves: Optional[Dict[str, List[Tuple[float, float]]]],
    target_ppl: Optional[float],
    iso_eff_threshold: float,
) -> None:
    if "transformer" not in results:
        print("\n[warn] No 'transformer' baseline; skipping comparison "
              "(need a key named exactly 'transformer').")
        return

    base = results["transformer"]
    base_raw = base["energy_per_token_joules"]
    base_above = base["energy_per_token_above_idle_joules"]
    base_params = base.get("n_params_non_embedding")
    base_wall = base.get("wall_clock_seconds")

    print("\n" + "=" * 78)
    print("Energy Comparison  (lower energy per token is better)")
    print("=" * 78)
    print("\nBaseline (transformer):")
    print(f"  raw          = {base_raw * 1e3:.4f} mJ/token")
    print(f"  above-idle   = {base_above * 1e3:.4f} mJ/token")
    if base_params:
        print(f"  #params(NE)  = {int(base_params):,}")

    # ---- idle-baseline sanity across families ----
    idle_powers = {n: r.get("idle_power_watts") for n, r in results.items()
                   if r.get("idle_power_watts")}
    shared = bool(results) and all(
        r.get("idle_power_shared") for r in results.values())
    if shared:
        print("  idle baseline: SHARED robust median across families (good).")
    if len(idle_powers) >= 2 and not shared:
        vals = [v for v in idle_powers.values() if v]
        spread = max(vals) - min(vals)
        if spread > 15.0:
            print(f"\n  [WARN] per-family idle baselines differ by "
                  f"{spread:.1f} W: {idle_powers}.")
            print("         The ABOVE-IDLE column is NOT comparable; re-run so "
                  "idle is shared/robust. Prefer the RAW column meanwhile.")

    if base_raw > 0:
        idle_frac = 1.0 - (base_above / base_raw)
        if idle_frac > 0.30:
            print(f"\n  [warn] idle floor = {idle_frac*100:.1f}% of baseline "
                  "total energy; above-idle is sensitive to idle error.")

    # ----------------------------------------------------------------
    # VIEW 1 & 2: iso-parameter overhead (NEUTRAL) + iso-FLOPs proxy
    # ----------------------------------------------------------------
    print("\n" + "-" * 78)
    print("VIEW 1/2 — iso-parameter overhead  (NEUTRAL: NOT a verdict)")
    print("  Compares EQUAL-SIZE models. cid_full is far more accurate at")
    print("  equal params, so a per-token energy *overhead* here is EXPECTED")
    print("  and does NOT test the C13 energy bonus.")
    print("-" * 78)
    print(f"  {'Family':32s} {'raw ovhd':>10s} {'above-idle':>12s} "
          f"{'wall x':>8s} {'params x':>9s}")
    print("  " + "-" * 74)
    for name, r in results.items():
        if name == "transformer":
            continue
        eptj = r["energy_per_token_joules"]
        eptj_a = r["energy_per_token_above_idle_joules"]
        raw_ovhd = (eptj / base_raw) if base_raw > 0 else float("nan")
        above_ovhd = (eptj_a / base_above) if base_above > 0 else float("nan")
        wall_x = (r.get("wall_clock_seconds", float("nan")) / base_wall
                  if base_wall else float("nan"))
        params_x = (r.get("n_params_non_embedding", float("nan")) / base_params
                    if base_params else float("nan"))
        print(f"  {name:32s} {raw_ovhd:>9.2f}x {above_ovhd:>11.2f}x "
              f"{wall_x:>7.2f}x {params_x:>8.2f}x")
    print("  (overhead > 1.0x means MORE energy per token at equal size)")

    # ----------------------------------------------------------------
    # VIEW 3: iso-performance (THE decisive C13/C14 test)
    # ----------------------------------------------------------------
    print("\n" + "-" * 78)
    print("VIEW 3 — iso-PERFORMANCE energy ratio  (DECISIVE, tests C13)")
    print("-" * 78)

    if scaling_curves is None or target_ppl is None:
        print("  [skipped] needs --scaling_law_json AND --target_ppl.")
        print("  Without it NO energy-efficiency verdict (>=3x) is issued;")
        print("  the iso-parameter views above are NOT a substitute.")
        print("\nNote: the C13 '>=3x energy efficiency' claim is evaluated "
              "ONLY against the iso-performance ratio, never iso-parameter.")
        return

    base_curve = scaling_curves.get("transformer")
    base_iso_params = (_params_at_target_ppl(base_curve, target_ppl)
                       if base_curve else None)
    if base_iso_params is None:
        print(f"  [skipped] transformer cannot reach target_ppl={target_ppl} "
              "within its MEASURED scaling range (refusing to extrapolate).")
        print("  Train larger transformer points, or pick a --target_ppl that "
              "all compared families actually reach.")
        return

    base_meas_params = base_params or _largest_curve_params(base_curve)
    base_iso_energy, base_exact = _rescale_energy_to_params(
        measured_energy=base_above,
        measured_params=base_meas_params,
        target_params=base_iso_params,
    )

    print(f"  Target perplexity            : {target_ppl}")
    print(f"  transformer @ target         : ~{base_iso_params:,.0f} "
          f"params(NE), est. {base_iso_energy*1e3:.4f} mJ/token (above-idle)"
          f"{'' if base_exact else '  [DEGRADED: no measured #params]'}")
    print()
    print(f"  {'Family':30s} {'iso params':>14s} {'iso mJ/tok':>12s} "
          f"{'iso-perf ratio':>14s} {'verdict':>18s}")
    print("  " + "-" * 76)

    for name, r in results.items():
        if name == "transformer":
            continue
        curve = scaling_curves.get(name)
        if not curve:
            print(f"  {name:30s} {'(no curve)':>14s}")
            continue
        iso_params = _params_at_target_ppl(curve, target_ppl)
        if iso_params is None:
            print(f"  {name:30s} {'(out of range)':>14s}  "
                  f"-- cannot reach ppl={target_ppl} in measured range")
            continue
        meas_params = (r.get("n_params_non_embedding")
                       or _largest_curve_params(curve))
        iso_energy, exact = _rescale_energy_to_params(
            measured_energy=r["energy_per_token_above_idle_joules"],
            measured_params=meas_params,
            target_params=iso_params,
        )
        ratio = (base_iso_energy / iso_energy) if iso_energy > 0 else float("nan")
        if name == "cid_full":
            verdict = (f"PASS (>= {iso_eff_threshold:g}x)"
                       if ratio >= iso_eff_threshold
                       else f"BELOW ({ratio:.2f}x)")
        else:
            verdict = (f"{ratio:.2f}x better" if ratio >= 1.0
                       else f"{1.0/ratio:.2f}x worse")
        flag = "" if exact else "  [DEGRADED]"
        print(f"  {name:30s} {iso_params:>14,.0f} {iso_energy*1e3:>11.4f} "
              f"{ratio:>13.2f}x {verdict:>18s}{flag}")

    print("\n  Method: iso-performance energy/token = measured above-idle")
    print("  energy/token rescaled by (iso_params / measured_params), since")
    print("  per-token FLOPs ~ #params for these fixed-shape families.")
    print(f"\n  C13 verdict for cid_full uses the iso-perf ratio vs the "
          f"{iso_eff_threshold:g}x threshold ONLY.")


# ======================================================================
# Output blob
# ======================================================================


def _make_output_blob(args, results: Dict[str, Dict[str, Any]],
                       idle_info: Dict[str, float]) -> Dict[str, Any]:
    return {
        "schema_version": "energy_v2.2_iso_perf",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "torch_version": torch.__version__,
            "cuda_version": (
                torch.version.cuda if torch.cuda.is_available() else None),
            "device_name": (
                torch.cuda.get_device_name(0)
                if torch.cuda.is_available() else None),
            "shared_idle_baseline": idle_info,
            "cli_args": vars(args),
        },
        "results": results,
    }


# ======================================================================
# Main
# ======================================================================


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families", nargs="+",
        default=["cid_full", "transformer", "transformer_plus_tricks"],
        help="Model families to benchmark. NOTE: must match the names used "
             "by run_scaling_law.py (e.g. 'transformer_plus_tricks').",
    )
    parser.add_argument("--checkpoint_dir", type=str, required=True)
    parser.add_argument("--scale", type=str, default="100M")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--seq_len", type=int, default=1024)
    parser.add_argument("--vocab_size", type=int, default=50257)
    parser.add_argument("--n_warmup", type=int, default=50)
    parser.add_argument("--n_measure", type=int, default=500)
    parser.add_argument(
        "--mode", type=str, default="decode",
        choices=["prefill", "decode"],
        help="decode (recommended for energy claims): token-by-token greedy "
             "decode; per-token denominator = NEW tokens. "
             "prefill: one full forward; denominator = all input tokens.",
    )
    parser.add_argument("--new_tokens_per_decode", type=int, default=64)
    parser.add_argument("--sample_rate_hz", type=float, default=25.0)
    parser.add_argument("--idle_window_seconds", type=float, default=2.0)
    parser.add_argument(
        "--idle_n_windows", type=int, default=3,
        help="Idle windows to median over (robust baseline).",
    )
    parser.add_argument(
        "--idle_settle_seconds", type=float, default=2.0,
        help="Seconds to wait for GPU clocks to settle before idle sampling.",
    )
    parser.add_argument(
        "--sampler_preference", type=str, default="auto",
        choices=["auto", "pynvml", "nvidia_smi"],
    )
    parser.add_argument(
        "--real_token_file", type=str, default=None,
        help="Optional .pt/.bin of real token ids (>= batch*seq_len total). "
             "If omitted, random tokens are used and flagged.",
    )
    # ---- iso-performance comparison inputs ----
    parser.add_argument(
        "--scaling_law_json", type=str, default=None,
        help="run_scaling_law.py results.json (top-level list of "
             "ScalingResult). REQUIRED for the decisive iso-performance column.",
    )
    parser.add_argument(
        "--target_ppl", type=float, default=None,
        help="Target perplexity for the iso-performance comparison. Must be "
             "reachable by ALL compared families within their measured range.",
    )
    parser.add_argument(
        "--sl_ppl_field", type=str, default="final_eval_ppl",
        help="Perplexity field name in the scaling-law json "
             "(native: final_eval_ppl; aggregated summary: eval_ppl_mean).",
    )
    parser.add_argument(
        "--sl_params_field", type=str, default="non_emb_params",
        help="Non-embedding param-count field name in the scaling-law json "
             "(native: non_emb_params).",
    )
    parser.add_argument(
        "--iso_eff_threshold", type=float, default=3.0,
        help="Energy-efficiency threshold for the cid_full C13 verdict, "
             "evaluated against the ISO-PERFORMANCE ratio only.",
    )
    parser.add_argument("--output_dir", type=str,
                        default="./results/energy_v2.2")
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip families already in results.json; merge new results.",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("Energy benchmark requires NVIDIA GPU; "
                           "torch.cuda.is_available() == False.")
    device = "cuda"

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "results.json"

    existing_blob = _load_existing_output(output_path) if args.resume else {}
    existing_results: Dict[str, Dict[str, Any]] = (
        existing_blob.get("results", {}) if existing_blob else {}
    )

    # ---- load scaling curves up-front (used in final comparison) ----
    scaling_curves = None
    if args.scaling_law_json:
        scaling_curves = _load_scaling_curves(
            Path(args.scaling_law_json),
            ppl_field=args.sl_ppl_field,
            params_field=args.sl_params_field,
        )

    # ---- RESUME: short-circuit if everything is already present ----
    if args.resume and existing_results:
        present = set(existing_results.keys())
        if set(args.families).issubset(present):
            print(f"[resume] All requested families already in "
                  f"{output_path.name} ({sorted(present)}); nothing to do.")
            _print_comparison(
                existing_results,
                scaling_curves=scaling_curves,
                target_ppl=args.target_ppl,
                iso_eff_threshold=args.iso_eff_threshold,
            )
            return
        else:
            todo = set(args.families) - present
            print(f"[resume] {len(present)} done ({sorted(present)}); "
                  f"running remaining: {sorted(todo)}")
    # ---- guard: decode must not exceed the model's positional limit ----
    if args.mode == "decode":
        # Try to discover each model's max positional length; fall back to
        # the user-supplied seq_len budget. We clamp the STARTING seq_len so
        # that  start_len + new_tokens_per_decode <= max_positions.
        max_pos = _discover_min_max_positions(
            args.families, Path(args.checkpoint_dir),
            args.scale, args.seeds, device,
        )
        if max_pos is not None:
            budget = max_pos - args.new_tokens_per_decode
            if budget < 1:
                raise RuntimeError(
                    f"new_tokens_per_decode={args.new_tokens_per_decode} >= "
                    f"model max positions={max_pos}; reduce --new_tokens_per_decode."
                )
            if args.seq_len > budget:
                print(f"[guard] decode: clamping --seq_len {args.seq_len} -> "
                      f"{budget} so that seq_len + new_tokens "
                      f"({args.new_tokens_per_decode}) <= max_positions "
                      f"({max_pos}).")
                args.seq_len = budget

    # ---- input tokens: prefer real tokens, flag random ----
    used_random_tokens = True
    if args.real_token_file:
        toks = torch.load(args.real_token_file, map_location="cpu")
        if not torch.is_tensor(toks):
            toks = torch.as_tensor(toks)
        toks = toks.view(-1)
        need = args.batch_size * args.seq_len
        if toks.numel() < need:
            raise RuntimeError(
                f"real_token_file has {toks.numel()} tokens; need {need}.")
        input_ids = toks[:need].view(
            args.batch_size, args.seq_len).long().to(device)
        used_random_tokens = False
    else:
        input_ids = torch.randint(
            0, args.vocab_size, (args.batch_size, args.seq_len), device=device)

    ckpt_dir = Path(args.checkpoint_dir)
    results: Dict[str, Dict[str, Any]] = dict(existing_results)

    print(f"\nEnergy benchmark v2.2 (resume={args.resume})")
    print(f"  mode          = {args.mode}")
    if args.mode == "decode":
        print(f"  new_tokens    = {args.new_tokens_per_decode} per iter")
    print(f"  tokens        = "
          f"{'RANDOM (flagged)' if used_random_tokens else 'REAL'}")
    print(f"  sampler_pref  = {args.sampler_preference}")
    print(f"  sample_rate   = {args.sample_rate_hz} Hz")
    print(f"  batch x seq   = {args.batch_size} x {args.seq_len}")
    print(f"  warmup/measur = {args.n_warmup} / {args.n_measure}")

    denom_kind = "new" if args.mode == "decode" else "prefill"

    # ---- robust idle baseline measured ONCE, shared by all families ----
    print("\n[idle] measuring robust shared idle baseline "
          f"({args.idle_n_windows} windows, median)...")
    idle_info = _robust_idle_power_watts(
        sampler_preference=args.sampler_preference,
        sample_rate_hz=args.sample_rate_hz,
        window_seconds=args.idle_window_seconds,
        n_windows=args.idle_n_windows,
        settle_seconds=args.idle_settle_seconds,
    )
    shared_idle_w = idle_info["idle_power_watts"]
    print(f"[idle] shared idle = {shared_idle_w:.2f} W "
          f"(spread {idle_info['idle_spread_watts']:.2f} W over "
          f"{int(idle_info['idle_n_windows'])} windows)")
    if idle_info["idle_spread_watts"] > 15.0:
        print("[idle] WARNING: idle spread > 15 W; GPU not quiescent. "
              "Above-idle numbers will be unreliable — increase "
              "--idle_settle_seconds or quiesce the box.")

    for name in args.families:
        if args.resume and name in results:
            print(f"\n[resume] skip '{name}' — already in results.json")
            continue

        ckpt_path = _find_checkpoint(ckpt_dir, name, args.scale, args.seeds)
        if ckpt_path is None:
            print(f"\n[warn] No checkpoint for '{name}' scale='{args.scale}' "
                  f"under {ckpt_dir}; skipping. (Check family naming matches "
                  f"run_scaling_law.py, e.g. 'transformer_plus_tricks'.)")
            continue

        print(f"\n{'=' * 70}\nBenchmarking: {name}  ({ckpt_path.name})\n"
              f"{'=' * 70}")
        model, loaded_family = _load_model_from_unified_ckpt(ckpt_path, device)
        n_params_ne = _count_params(model, non_embedding=True)

        em = measure_inference_energy(
            model=model,
            model_name=name,
            input_ids=input_ids,
            n_warmup=args.n_warmup,
            n_measure=args.n_measure,
            device=device,
            mode=args.mode,
            new_tokens_per_decode=args.new_tokens_per_decode,
            sample_rate_hz=args.sample_rate_hz,
            idle_window_seconds=args.idle_window_seconds,
            sampler_preference=args.sampler_preference,
        )

        # ---- override per-family idle with the shared robust baseline so
        #      the above-idle column is comparable across families ----
        rec: Dict[str, Any] = dict(em.to_dict())
        rec["idle_power_watts_meter"] = rec.get("idle_power_watts")
        rec["idle_power_watts"] = shared_idle_w
        rec["idle_power_shared"] = True
        rec["idle_spread_watts"] = idle_info["idle_spread_watts"]

        above_w = max(rec.get("avg_power_watts", 0.0) - shared_idle_w, 0.0)
        rec["power_above_idle_watts"] = above_w
        rec["energy_above_idle_joules"] = (
            above_w * rec.get("wall_clock_seconds", 0.0))
        tot_tok = rec.get("total_tokens", 0)
        rec["energy_per_token_above_idle_joules"] = (
            rec["energy_above_idle_joules"] / tot_tok if tot_tok > 0 else 0.0)

        rec["n_params_non_embedding"] = n_params_ne
        rec["used_random_tokens"] = used_random_tokens
        rec["token_denominator_kind"] = denom_kind
        rec["checkpoint"] = str(ckpt_path)
        rec["loaded_family"] = loaded_family

        _print_measurement(rec, denom_kind)

        results[name] = rec

        output = _make_output_blob(args, results, idle_info)
        output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"  [save] results.json updated ({len(results)} families)")

        del model
        torch.cuda.empty_cache()

    output = _make_output_blob(args, results, idle_info)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\n[ok] Results saved to {output_path}")

    _print_comparison(
        results,
        scaling_curves=scaling_curves,
        target_ppl=args.target_ppl,
        iso_eff_threshold=args.iso_eff_threshold,
    )


if __name__ == "__main__":
    main()
