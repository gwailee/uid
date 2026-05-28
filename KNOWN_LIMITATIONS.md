<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-28

Honest declaration of every known methodological / engineering defect
of the UID Theory reference implementation, broken down by release.
This file is the COUNTER-DOCUMENT to README.md: where README describes
what the project promises, this file describes where it has failed.
-->

# Known Limitations & Methodological Defects

This document is the **honest counter-document** to `README.md`. Where
the README describes what the project promises, this file documents
every known defect, by release. The goal is that:

1. A future user can cite any version of this codebase **knowing
   exactly what was broken at that version**.
2. The honest acknowledgement of failure protects scientific integrity
   and reduces the risk that downstream papers cite defective numbers.

We follow the convention that **defects identified post-release stay
in this file forever**, even after they are fixed in a later version.
A "FIXED IN" annotation records when the fix landed.

本文件是对 `README.md` 的**反向文档**：README 写承诺，本文件写已识别
的缺陷。我们坚持一条原则：**已识别的缺陷永远保留**，即使后续版本已修
复——"FIXED IN" 标记记录修复版本。这样任何引用旧版本数据的人都能立
即看到该版本下哪些主张是不可信的。

---

## Quick scope-of-trust table

| Version | Status | Can I cite empirical claims? |
|---|---|---|
| **v2.1** (current) | Infrastructure complete; large-scale experiments not yet run | **Cite only the predictions, not their realisation.** Until Phase 1 finishes, there is no v2.1 empirical run worth citing. |
| **v2.0** | Methodologically improved over v0.1 but contained 7 implementation / engineering bugs (see §B) | ⚠ **Do not cite v2.0 empirical numbers**: they were either invalidated by the v2.0 bugs (§B) or are based on a v0.1-era methodology. Re-run on v2.1 before citing. |
| **v0.1** | Validation suite had ≥10 methodological defects (see §A) | ❌ **Do not cite v0.1 empirical numbers**. Period. |

---

## §A — v0.1 (released 2026-03-01)

The v0.1 release accompanied the v0.1 paper preprint with three claims
of "verified" predictions:

* τ ≈ 1.5 (avalanche exponent)
* H ≈ 0.7 (Hurst exponent)
* β ≈ 1 (1/f spectrum slope)

Subsequent peer review identified **at least ten methodological
defects** that, taken together, made those claims unfalsifiable as
written. The defects are listed below in the order of severity.

### A1 — Circular critical-exponent measurement (severity: 🔴 critical)

**Defect.** v0.1 injected colored noise (1/f spectrum) at training
time as a regulariser, AND used the trained model's hidden-state
spectrum as the measurement of "emergent" 1/f. Because the same
spectrum was on both sides of the equation, the "validated 1/f"
result was structurally guaranteed; it carried no information about
whether the model itself developed any emergent dynamics.

**Why it matters.** This makes Theory §5 / README predictions 1-3
appear validated when they have not actually been tested.

**FIXED IN**: v2.0 introduced `CIDLayer.set_noise_injection(False)`;
v2.1 verified by `tests/test_cid_layer.py::TestDisableNoiseInjection`.

### A2 — Avalanche "detection" measured noise differences (severity: 🔴 critical)

**Defect.** v0.1's `test_avalanche_exponent` ran the same input
through the model twice (with dropout / noise on), then took
`|logits_a − logits_b|` as the "avalanche size" distribution. This
quantity is the magnitude of stochastic forward-pass noise; it has
nothing to do with the Beggs-Plenz definition of a neural avalanche
as a spatio-temporal cascade of supra-threshold activations.

**Why it matters.** The "τ ≈ 1.5" claim in the v0.1 paper was an
artefact of how stochastic differences scale, not of any avalanche
physics.

**FIXED IN**: v2.0 `verification/avalanche_detector.py` implements
the proper Beggs-Plenz protocol (z-score threshold crossings on
hidden-state activations).

### A3 — Log-binned linear regression for power-law fitting (severity: 🟠 high)

**Defect.** v0.1 fit power laws by `np.histogram` + log-bin centres +
`stats.linregress(log_centres, log_counts)`. Clauset, Shalizi & Newman
(2009, SIAM Rev. 51(4)) showed in detail that this estimator has
systematic bias of 10-30% even for distributions that are exactly
power-law, and gives no quantitative goodness-of-fit measure.

**Why it matters.** The reported exponents could be off by hundreds
of percentage points without any signal being available to detect it.

**FIXED IN**: v2.0 `verification/powerlaw_estimator.py` implements
Clauset-Shalizi-Newman MLE + KS goodness-of-fit + bootstrap
p-value.

### A4 — Sample size of 1 sequence × 256 timesteps (severity: 🟠 high)

**Defect.** v0.1's tests called the model once on a single input
batch (typically B=1, S=256) and computed all statistics from the
resulting 256 hidden-state values. Statistical power for fitting a
1/f spectrum requires at least several thousand samples per fit;
≤300 is in the regime where the fit slope is dominated by noise.

**FIXED IN**: v2.0's battery driver defaults to
`n_sequences=10000` and `max_seq_len>=4096`.

### A5 — R/S Hurst analysis instead of DFA (severity: 🟡 medium)

**Defect.** v0.1 estimated the Hurst exponent via the rescaled-range
(R/S) method. R/S is known to have heavy small-sample bias and is
not the modern gold standard. Peng et al. (1994) Detrended
Fluctuation Analysis (DFA) is the accepted replacement.

**FIXED IN**: v2.0 `verification/critical_exponents.estimate_hurst_dfa`.

### A6 — Toy baseline (severity: 🟡 medium)

**Defect.** v0.1 compared against `TinyTransformerLM`, an in-tree
toy with no RoPE, no RMSNorm, no SwiGLU, no proper init scaling.
Any v0.1 result of the form "CID > Transformer" was beating a
straw-man baseline.

**FIXED IN**: v2.0 `model/modern_transformer.py` (RoPE + RMSNorm +
SwiGLU) and `model/known_tricks_baseline.py` (Transformer + the same
tricks CID claims to need).

### A7 — Ablation matrix incomplete (severity: 🟡 medium)

**Defect.** v0.1's ablation had four entries (`cid_full`,
`cid_no_vortex`, `cid_no_noise`, `transformer`). It was missing both
`cid_no_memory` (so the contribution of the memory kernel was
untestable) AND every "Transformer + known tricks" variant (so the
central falsification — "does the physical framework add anything
above the known tricks?" — could not be answered).

**FIXED IN**: v2.0 introduced a 9-way ablation; v2.1 extended to 11
including `cid_full_no_et` and `cid_full_fft_noise`.

### A8 — Energy comparison was Landauer-limit arithmetic (severity: 🟡 medium)

**Defect.** v0.1 compared "CID energy per token" against the
theoretical Landauer lower bound (k_B T ln 2 per bit erased). This
ratio is a property of the laws of thermodynamics, not of any
particular implementation; comparing two implementations against the
same Landauer bound does not measure how the two implementations
differ from each other.

**FIXED IN**: v2.0 `verification/energy_meter.py` does real
`nvidia-smi` measurement; v2.1 upgrades to `pynvml` high-frequency
sampling with idle baseline and above-idle reporting.

### A9 — Parameter-efficiency claim was a single-point comparison (severity: 🟡 medium)

**Defect.** v0.1 claimed "5-10× parameter efficiency" by comparing
CID-N and Transformer-N at one specific N. Parameter efficiency is
defined as the horizontal spacing between scaling-law curves at
iso-loss; a single-point comparison cannot establish it.

**FIXED IN**: v2.0 `experiments/run_scaling_law.py` is an iso-FLOP
scaling-law study; the "≥3× / ≥5×" threshold is now operationalised
as "left-shift of the CID curve at iso-loss".

### A10 — No CI / no published results / no pre-registration (severity: 🟢 low)

**Defect.** v0.1 had no automated tests, no published result files
under `results/`, and no pre-registered falsification conditions —
so the "validated" claims could not be independently reproduced and
the criteria for falsification were retroactively adjustable.

**FIXED IN**: v2.0 added GitHub Actions CI/CD, `results/` directory,
and `ROADMAP.md` with pre-registered conditions.

### Verdict on v0.1 empirical claims

> ❌ **Do not cite any "validated" claim from the v0.1 paper or
> codebase.** The defects above act jointly, so even results that
> happen to be qualitatively correct cannot be defended against
> peer-review questions.

---

## §B — v2.0 (released 2026-05-15)

v2.0 was a complete methodological rewrite that addressed all the
defects in §A. However, subsequent review identified **seven
implementation / engineering bugs** that invalidate some v2.0
results. All seven have been fixed in v2.1.

### B1 — `HopfieldAttention` was standard attention, not ET symmetric (severity: 🔴 critical)

**Defect.** Theory §8.5 (which itself cites Hoover et al. 2023, the
Energy Transformer paper) requires the attention update to be the
**negative gradient of an ET energy function**, which has TWO terms:

