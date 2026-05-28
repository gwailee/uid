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

```
−dE/dg = softmax_C(K Q^T) @ q   +   softmax_B(K Q^T) @ k
                                  ^^^^^^^^^^^^^^^^^^^^^^
                                  the ET symmetric term
```

v2.0's `HopfieldAttention` implemented only the first term — i.e.
standard scaled dot-product attention. The Lyapunov-guaranteed
monotonic energy descent that §8.5 claims for CID was therefore not
realised in code.

**Why it matters.** Any v2.0 claim about "the CID Hopfield attention
descends an energy function" was structurally false. The theory
paper itself acknowledges this gap in §8.5 (the section that opens
with "What is required is to change 'subsequent versions should
supplement' into directly providing the corrected HopfieldAttention
in the body of this paper").

**FIXED IN**: v2.1 `uid_theory/cid/hopfield_potential.py` implements
the dual-term update; `tests/test_et_lyapunov.py` verifies monotonic
descent.

### B2 — `VortexField` introduced 2H² extra parameters, violating §14.2 (severity: 🔴 critical)

**Defect.** Theory §14.2 explicitly requires the vortex term to be
constructed from the antisymmetric part of an EXISTING weight (e.g.
the FFN first-layer weight), with **zero extra matrix parameters**.
v2.0 instead instantiated two independent `nn.Linear(H, H, bias=False)`
inside `VortexField`, adding **`2 × H × H` parameters per layer**.

For H=768 this is roughly 1.18M extra parameters per layer; for an
8-layer model, ~9.4M extra — comparable to an entire MiniMind-26M
model. This directly inflates v2.0's CID parameter count and makes
the "≥10× parameter efficiency" prediction harder to evaluate fairly.

**FIXED IN**: v2.1 `uid_theory/cid/vortex_field.py` rebuilds the
operator on-the-fly from an external `weight_ref`. The only
learnable parameter is one scalar (`log_temp_diff`).
`tests/test_et_lyapunov.py::TestVortexZeroExtraParams` verifies the
zero-extra-params contract.

### B3 — `VortexField` silent no-op inside the baseline (severity: 🔴 critical)

**Defect.** v2.0's `model/known_tricks_baseline.py` instantiated
`VortexField(hidden_size)` without passing any `weight_ref`. Because
v2.0's `VortexField` always created its own weights internally, this
worked; but in v2.1 (where `VortexField` requires a reference) the
caller forgot to update the baseline call, and the result was that
the curl operator silently degenerated to zero.

Consequence: in v2.1 (before this bug was caught), the
`transformer_plus_linear` and `transformer_plus_all_tricks` variants
were NOT actually testing what their names claimed — the "extra linear
term" was a no-op. Any v2.0 → v2.1 transition that didn't catch this
bug would have produced a contrast in which CID "won" trivially.

**Why it matters.** The central falsification test in v2.0 was
"does `cid_full` beat `transformer_plus_all_tricks`?" — if the
baseline silently has its key term zeroed out, this question is
unanswerable.

**FIXED IN**: v2.1 `model/known_tricks_baseline.py` passes
`weight_ref=ffn.W1.weight` to `VortexField` and includes a
`_get_ffn_first_weight()` helper for SwiGLU variants.
Regression test in `tests/test_data_loaders.py` is not the right
place; see `tests/test_run_scaling_law.py` instead.

### B4 — Default colored noise was FFT shaping, not physical OU (severity: 🟠 high)

**Defect.** Theory §14.2 prefers the colored noise to be generated
by a local SDE (specifically an Ornstein-Uhlenbeck process) so that
it self-consistently couples to the sub-Ohmic memory kernel via the
fluctuation-dissipation theorem. v2.0's default was FFT spectral
shaping, which is non-local: every output token has global
correlations with every other token. This creates a
"circular-measurement" risk: even with noise injection off at
measurement time, the trained weights may carry the imprint of the
non-physical correlations, so the measured 1/f signature partially
reflects the injected spectrum.

**FIXED IN**: v2.1 default is `noise_type="ou"` with the discrete-OU
update `xi[t+1] = decay * xi[t] + sqrt(1-decay²) * N(0,1)`.
`tests/test_critical_exponents.py::TestEtaInBattery` verifies the
end-to-end pipeline.

### B5 — `UIDConfig` dropped v2.1 fields on `save_pretrained` / `from_pretrained` (severity: 🟠 high)

**Defect.** Adding `noise_type`, `noise_tau`, `use_et_symmetric` to
the `UIDConfig.__init__` signature is necessary for HuggingFace
serialisation to preserve them. v2.0 (and the early v2.1 transition)
forgot to add the fields to `__init__`, so `cfg.to_dict()` would
omit them, and `UIDConfig.from_dict(cfg.to_dict())` would silently
revert them to defaults.

**Why it matters.** Anyone training a CID model with non-default
settings (e.g. `noise_type="fft"` for the §14.2 isolation
ablation), then saving and reloading the checkpoint, would have
gotten back an OU-noise model — silently invalidating their
experiment.

**FIXED IN**: v2.1 `model/model_uid.py` adds the three fields to
`UIDConfig.__init__`. `tests/test_run_scaling_law.py::
TestUnifiedCheckpoint::test_config_dict_present_for_cid_model`
verifies the round trip.

### B6 — `run_scaling_law.py` never saved checkpoints (severity: 🟠 high)

**Defect.** v2.0's `run_scaling_law.py` only wrote `results.json` and
`scaling_curves.png`. But `run_critical_exponents.py` and
`run_energy_benchmark.py` both required `.pt` checkpoint files. As a
result, when a user ran `run_all.py`, the latter two experiments
were silently skipped via "checkpoint not found" branches — but the
final summary report did not flag this loudly. Any v2.0 end-to-end
"validation" run that relied on these downstream experiments was
therefore vacuous.

**FIXED IN**: v2.1 `run_scaling_law.py` saves
`{family}_{scale}_seed{seed}.pt` in a unified v2.1 schema, and
`run_all.py` discovers them via `find_checkpoint()` and warns
loudly if anything is missing.

### B7 — `FIDLayer.info["curvature_loss"]` broke JSON serialisation (severity: 🟡 medium)

**Defect.** v2.0's `FIDLayer.forward` returned a Python dict
containing both Python scalars (e.g. `info["curvature"] = 0.42`) AND
an autograd-bearing `torch.Tensor` (`info["curvature_loss"]`). The
caller was expected to extract the tensor and add it to the loss
manually. But the typical `run_*.py` pipeline called
`json.dumps(info)` on the result — which crashes on a Tensor. So any
experiment that turned on `curvature_weight > 0` would have failed
silently at JSON-dump time, often after hours of training.

**FIXED IN**: v2.1 introduces `LOSS_PREFIX = "__loss__"` and an
`extract_loss_tensors(info)` helper. Loss tensors are stored under a
key with the LOSS_PREFIX so a `json.dumps` cannot accidentally pick
them up; the caller is required to call `extract_loss_tensors()`
explicitly before serialisation. `tests/test_fid_layer.py::
TestInfoIsJsonSafe` verifies the contract.

### Verdict on v2.0 empirical claims

> ⚠ **v2.0 empirical numbers should be re-run on v2.1 before
> citation.** Specifically:
>
> * Any benchmark that relied on `transformer_plus_linear` or
>   `transformer_plus_all_tricks` is invalidated by B3.
> * Any benchmark that depended on `save_pretrained` round-tripping
>   the CID config is invalidated by B5.
> * Any end-to-end `run_all.py` summary that included
>   "critical exponents" or "energy" steps is invalidated by B6.
> * Any experiment with `curvature_weight > 0` is invalidated by B7.
> * Any claim about ET energy descent or "zero extra parameters" is
>   invalidated by B1 / B2.
>
> v2.0 was a major methodological improvement and remains correct
> in spirit, but the implementation bugs above mean its concrete
> numbers should not be cited.

---

## §C — v2.1 (current release, 2026-05-28)

v2.1 has fixed every defect in §A and §B. **However, three categories
of limitation remain by design**, and any v2.1 citation should
acknowledge them.

### C1 — CID is the only tier that is fully falsifiable in this codebase (severity: 🟡 by design)

**Statement.** Only the CID tier maps from theory equations to runnable
code without external dependencies. QID and FID have **structural**
limitations that this codebase cannot overcome:

* **QID** is a classical surrogate. The "Lindblad channels" are
  phenomenological linear maps, not true Kraus decompositions. The
  "quantum noise" is FFT or OU shaping of classical Gaussian noise
  with a QFDT-shaped envelope. The "Berry phase" is a paired
  rotation in real (not complex) space. Real quantum advantage
  requires NISQ or fault-tolerant quantum hardware.
* **FID** is a diagnostic geometric probe, not a numerical solver
  for the FID field equation. The Fisher metric used is the
  hidden-state empirical covariance, not the parameter-space true
  Fisher matrix (which is O(M²) and infeasible). The "Ricci scalar
  surrogate" is `log det(g) − log H`, a volume-element proxy.

**Implication.** Any v2.1 citation should say "CID is implemented and
tested; QID and FID are exploratory probes". The README enforces this
in its "Honest statement" section.

### C2 — Phase 1 large-scale experiments are not yet complete (severity: 🟡 schedule)

**Statement.** v2.1 ships the **infrastructure** for the full
validation programme but the actual runs at 10M-1B scale have not
been executed. The eight pre-registered falsification conditions in
README §"Pre-registered falsification conditions" cannot be
evaluated until Phase 1 runs complete.

**Implication.** A paper citing v2.1 should say "the validation
infrastructure is complete and pre-registered; Phase 1 results are
pending (see ROADMAP §Phase 1)". A paper citing v2.1 should **not**
make any empirical claim of the form "CID achieves Xx parameter
efficiency" until Phase 1 has been run and reported.

### C3 — Some validation methods are statistical surrogates (severity: 🟡 by design)

**Statement.** Even with v2.1's infrastructure, the following
measurements are NOT direct verifications of the theory paper:

* **Fisher anisotropy η** is measured on the hidden-state empirical
  covariance, not on the parameter-space Fisher matrix that Theory
  §2.2 / §6.1 actually defines. `EtaResult.rank_deficient` flags
  the case where `seq_len < hidden_size` makes even this surrogate
  unreliable. Compare against the theory's quantitative form is
  meaningful only at the order-of-magnitude level.
* **Avalanche τ via the Beggs-Plenz protocol** measures activity
  cascades in hidden-state z-scores; the original Beggs-Plenz
  protocol applies to spike counts in cortical recordings. The
  analogy is mechanistic and well-established in the criticality
  literature but is not a strict identity.
* **Energy per token "above-idle"** is a hardware-specific
  measurement; idle baseline depends on driver state, ambient
  temperature, and other processes on the same GPU. Cross-hardware
  comparisons require the Phase 3 multi-hardware roadmap.

**Implication.** A paper citing v2.1 numbers should report the v2.1
methodology AND its surrogate status, e.g.: "measured Fisher anisotropy
η = 0.72 on the hidden-state empirical covariance (parameter-space
true Fisher is provided as `FisherMetric.compute_true_fisher_diagonal`
for calibration; see CHANGELOG §v2.1)".

### Verdict on v2.1 empirical claims

> ⏳ **v2.1 has no large-scale empirical claims to cite yet.** When
> Phase 1 runs are reported, they will be the first set of UID
> empirical numbers safe to cite. Until then, cite only:
> (a) the theory paper itself; and
> (b) the v2.1 infrastructure as the means of pre-registered
>     falsification.

---

## §D — Contact for newly discovered defects

If you identify a defect in any version of this codebase that is
**not** listed above, please file an issue or email **lig@jodell.cn**
with subject prefix `[UID Defect Report]`. We commit to:

1. Adding the defect to this document within 7 days, with severity
   classification and "FIXED IN" placeholder.
2. Fixing it in the next minor release, OR explicitly justifying why
   it is a "by-design" limitation (in which case it goes under §C of
   the current version).
3. Re-running any pre-Phase-1 numbers that the defect invalidates,
   and updating CHANGELOG.md accordingly.

如发现本文件未列出的缺陷，请提交 issue 或发送邮件至 **lig@jodell.cn**
（主题前缀 `[UID Defect Report]`）。我们承诺：
1. 7 天内更新本文件，注明严重度与 "FIXED IN" 占位；
2. 在下一个 minor release 中修复（或明确说明为"设计内限制"，归入当前
   版本的 §C）；
3. 重跑被该缺陷影响的所有 Phase-1 前数据，同步更新 CHANGELOG.md。

---

## Honest closing statement

> Every project that claims to "verify" predictions in machine
> learning, physics, or any quantitative science faces the same
> tension: between the speed of releasing impressive-looking results
> and the rigour required to make those results actually mean what
> they appear to say. v0.1 of this project tilted too far toward the
> first; v2.0 over-corrected and introduced its own bugs; v2.1
> tries to honestly state what is and is not yet validated.
>
> If you read this file and think "wow, they admit a lot" — good.
> That is the entire point. A theory paper that hides its limitations
> earns one paper. A theory paper that documents its limitations
> earns a research programme.
>
> 任何在机器学习、物理或任何定量科学中声称"已验证"预言的项目，都面
> 临同一矛盾：发布漂亮结果的速度，与让这些结果真正名副其实所需的严谨
> 性之间的冲突。本项目 v0.1 偏向了前者，v2.0 矫枉过正引入了新 bug，
> v2.1 努力诚实陈述哪些已验证、哪些尚未。
>
> 如果你读完本文件感到"他们承认得真多" —— 这正是本意。一篇隐藏局限
> 的论文换来一篇引用；一篇记录局限的论文换来一个研究计划。
```
