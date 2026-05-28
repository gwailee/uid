
<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>

PHASE 1 REPORT TEMPLATE
=======================
This is a TEMPLATE. To produce an actual Phase 1 report:

  1. Copy this file to `results/phase1/REPORT.md` (drop the `.template`).
  2. Fill in every `<<...>>` placeholder. Do NOT leave any placeholder
     in the published report — empty placeholders are a signal that the
     report is incomplete and the results are not citable.
  3. Run the validator: `python scripts/validate_report.py results/phase1/REPORT.md`
     (the validator checks that no `<<...>>` placeholders remain AND
     that every F-condition is in {PASS, FAIL, ABSTAIN_rank_deficient,
     ABSTAIN_not_measured, PARTIAL}).
  4. Commit alongside the corresponding `MANIFEST.json` and result JSONs.

This template follows the 7-section structure mandated by
`results/README.md` §"Schema 6 — REPORT.md (per phase)".

Markers used in this template:
  <<placeholder>>    : MUST be replaced before publishing
  [optional: ...]    : May be replaced or deleted
  -->

# UID Phase 1 Report — Small-to-Medium Scaling Validation

> **Phase**: Phase 1 (10M–100M scaling + 11-way ablation + critical
> exponents + above-idle energy)
> **Phase status at publication of this report**: <<COMPLETE | PARTIAL>>
> **Pre-registered conditions tested**: F1, F2, F3, F4, F5, F6, F7, F8
> **Citation policy**: per `results/README.md` "Cite-or-not quick
> reference" — Phase 1 v2.1 results are **citable WITH the v2.1
> commit hash and the per-claim caveats listed in §6 of this report**.

---

## 1. Phase metadata

| Field | Value |
|---|---|
| Phase name | Phase 1 |
| Start date | <<YYYY-MM-DD>> |
| End date | <<YYYY-MM-DD>> |
| Total wall-clock (calendar days) | <<N days>> |
| UID version | v2.1 |
| UID commit hash | `<<abcdef1234567890...>>` |
| Tokenizer | `gpt2` (vocab_size=50257) |
| Datasets | wikitext-103 (raw-v1), see `MANIFEST.json` for SHA-256 |
| Seeds used | <<[42, 43, 44]>> |
| Scales tested | <<[10M, 30M, 100M]>> |
| Hardware platform | <<NVIDIA H100 80GB SXM5, 8 GPUs × 4 nodes>> |
| Total training compute (GPU-hours) | <<approx N,000 GPU-hours>> |
| Total energy-measurement compute (GPU-hours) | <<approx M>> |
| Authors of this report | <<Gui LI; Dangyang JIE; Haitao KANG>> |
| Report version | 1.0 |

---

## 2. Falsification scorecard

This phase tested **eight** pre-registered falsification conditions
from `ROADMAP.md` §"Phase 1 — Pre-registered falsification conditions".
Each row gives the verdict and a one-sentence justification.

> **Reading guide.** A `FAIL` verdict means the corresponding UID
> claim is **falsified at this scale**. `ABSTAIN_*` means the
> measurement was inconclusive for a stated reason (typically a
> data-quality issue), not that the claim was supported.

| # | Condition | Verdict | One-sentence justification |
|---|---|---|---|
| **F1** | At 100M, `cid_full` iso-loss point ≥ 1.5× left of `transformer_plus_all_tricks` | <<PASS \| FAIL \| PARTIAL>> | <<measured horizontal shift = X.X×, with std Y; see §3.1>> |
| **F2** | At 100M, `cid_full` iso-loss point ≥ 3× left of `transformer` | <<PASS \| FAIL \| PARTIAL>> | <<measured horizontal shift = X.X×, with std Y; see §3.1>> |
| **F3** | β ∈ [0.7, 1.3] in ≥80% of layers (`cid_full`, noise OFF) | <<PASS \| FAIL \| ABSTAIN_*>> | <<measured β̄ = X.XX, in-range layers Z/L; see §3.3>> |
| **F4** | H ∈ [0.6, 0.8] (`cid_full`, noise OFF, DFA) | <<PASS \| FAIL \| ABSTAIN_*>> | <<measured H = X.XX ± Y.YY across N series; see §3.3>> |
| **F5** | Avalanche τ ∈ [1.3, 1.7] with KS p > 0.1 (Clauset MLE) | <<PASS \| FAIL \| ABSTAIN_*>> | <<measured τ = X.XX, KS p = Y.YY; see §3.4>> |
| **F6** | η > 0.5, excluding rank-deficient runs | <<PASS \| FAIL \| ABSTAIN_rank_deficient>> | <<measured η = X.XX, seq_len/hidden ratio = Z; see §3.3>> |
| **F7** | Decode above-idle energy per token of `cid_full` ≤ 1/3 of `transformer` at iso-PPL | <<PASS \| FAIL \| PARTIAL>> | <<measured ratio = X.XX×; see §3.5>> |
| **F8** | `cid_full` outperforms `cid_full_no_et` (paired t-test, p < 0.05) | <<PASS \| FAIL>> | <<measured Δloss = X.XXX, p = Y.YYY; see §3.2>> |

### 2.1 Headline summary

> <<Replace this paragraph with a 3-5 sentence high-level summary:
> which predictions passed, which failed, and what (if anything) was
> surprising. Example: "All eight predictions PASSED at 100M scale.
> The most notable result is that F1 passed with a measured shift of
> 2.1× (predicted ≥ 1.5×), supporting the UID physical framework
> claim against a strong known-tricks baseline. F6 (η) is reported
> as ABSTAIN_rank_deficient on three of nine layer-level
> measurements because max_seq_len < hidden_size in two model
> configurations; the remaining six measurements all gave η > 0.5
> and are reported as the headline η result.">>

### 2.2 Aggregate pass/fail count

| Verdict | Count | Conditions |
|---|---|---|
| PASS | <<N>> | <<F1, F2, ...>> |
| FAIL | <<N>> | <<list, or "(none)">> |
| ABSTAIN_rank_deficient | <<N>> | <<list, or "(none)">> |
| ABSTAIN_not_measured | <<N>> | <<list, or "(none)">> |
| PARTIAL | <<N>> | <<list, or "(none)">> |

---

## 3. Per-experiment summaries

### 3.1 Scaling-law experiment (F1, F2)

**Goal**: Iso-FLOP scaling-law curves for all model families across
10M / 30M / 100M, with multiple seeds per cell. Test whether
`cid_full` sits to the LEFT of `transformer` and
`transformer_plus_all_tricks` at iso-loss.

**Methodology**:

* Tokens-per-parameter: <<20.0>> (Chinchilla optimal)
* Total FLOPs per model: 6 × N × D where N = non-embedding params
* Optimizer: AdamW (lr=3e-4, weight_decay=0.01, cosine schedule)
* Batch size: <<32>> sequences × <<1024>> tokens
* Mixed precision: <<bf16>>
* Seed handling: each (family, scale, seed) is an independent run

**Result files**:

* `phase1/scaling_law/results.json` (schema: `scaling_law_v1`)
* `phase1/scaling_law/scaling_curves.png`
* `phase1/scaling_law/checkpoints/{family}_{scale}_seed{seed}.pt`

**Headline numbers** (mean ± std across <<3>> seeds, 100M scale):

| Family | Non-emb params | Eval loss (mean ± std) | Eval PPL |
|---|---|---|---|
| `transformer` | <<N,NNN,NNN>> | <<X.XX ± X.XX>> | <<XX.XX>> |
| `transformer_plus_all_tricks` | <<N,NNN,NNN>> | <<X.XX ± X.XX>> | <<XX.XX>> |
| `cid_full` | <<N,NNN,NNN>> | <<X.XX ± X.XX>> | <<XX.XX>> |
| `cid_full_no_et` | <<N,NNN,NNN>> | <<X.XX ± X.XX>> | <<XX.XX>> |
| `cid_full_fft_noise` | <<N,NNN,NNN>> | <<X.XX ± X.XX>> | <<XX.XX>> |

**Iso-loss horizontal shift** (computed by linear interpolation of
each family's scaling curve in log-param space):

| Comparison | Shift at loss = <<X.XX>> | UID prediction | Verdict |
|---|---|---|---|
| `cid_full` vs `transformer` | <<X.XX×>> | ≥ 3× | <<PASS \| FAIL>> |
| `cid_full` vs `transformer_plus_all_tricks` | <<X.XX×>> | ≥ 1.5× | <<PASS \| FAIL>> |

[optional: include the scaling-curve plot inline]

```
[scaling curves plot here, or: see phase1/scaling_law/scaling_curves.png]
```

### 3.2 Eleven-way ablation (F8 and three critical contrasts)

**Goal**: Quantify the contribution of each CID component and the
v2.1 isolation variants; verify the three critical contrasts
reported by `run_ablation.py`.

**Methodology**:

* Scale: <<30M>>
* Seeds: <<[42, 43, 44]>>
* All other settings identical to scaling-law experiment

**Result files**:

* `phase1/ablation/results.json`
* `phase1/ablation/summary.json` (schema: `ablation_summary_v1`)
* `phase1/ablation/tables/`

**Sorted leaderboard** (best to worst eval loss):

| Rank | Variant | Loss (mean ± std) | PPL | Δ vs `cid_full` |
|---|---|---|---|---|
| 1 | <<variant>> | <<X.XX ± X.XX>> | <<XX.XX>> | <<+0.000>> |
| 2 | <<variant>> | <<X.XX ± X.XX>> | <<XX.XX>> | <<+0.XXX>> |
| ... | ... | ... | ... | ... |

**Three critical contrasts**:

| Contrast | Δloss (a vs b) | z-score | Verdict |
|---|---|---|---|
| A. `cid_full` vs `transformer_plus_all_tricks` | <<+0.XXX>> | <<X.XX>> | <<supported \| falsified>> |
| B. `cid_full` vs `cid_full_no_et` (= §8.5 contribution; F8) | <<+0.XXX>> | <<X.XX>> | <<supported \| falsified>> |
| C. `cid_full` vs `cid_full_fft_noise` (= §14.2 contribution) | <<+0.XXX>> | <<X.XX>> | <<supported \| falsified>> |

> [optional: short paragraph explaining any surprising ablation
> finding, e.g. "Contrast C had a smaller-than-expected effect on
> raw PPL, but the §14.2 motivation for OU is downstream
> measurement reliability rather than perplexity — see §3.3 for
> the noise-OFF vs noise-ON eta gap."]

### 3.3 Critical-exponent measurement (F3, F4, F6)

**Goal**: Measure β, H, η on the best-trained `cid_full` checkpoint
(by validation PPL across the three seeds), with noise injection
both OFF (the genuine emergence test) and ON (a sanity check that
should differ meaningfully from OFF).

**Methodology**:

* Checkpoint: `phase1/scaling_law/checkpoints/cid_full_100M_seed<<42>>.pt`
* Hidden states collected from <<10,000>> sequences × <<4,096>> tokens
* Layer index: <<-1>> (last)
* β estimator: rFFT + log-log linear regression in inertial range
* H estimator: DFA (Peng et al. 1994)
* η estimator: `measure_fisher_anisotropy_eta()`, eta_threshold=0.5,
  eta_max_samples=<<256>>

**Result file**:

* `phase1/critical_exponents/results.json` (schema:
  `critical_exponents_v1`)
* `phase1/critical_exponents/verdict.md`

**Contrast table** (noise OFF vs noise ON, `cid_full` only):

|   | noise OFF | noise ON | |diff| | In UID range? |
|---|---|---|---|---|
| β (spectrum slope) | <<X.XXX>> | <<X.XXX>> | <<0.XXX>> | <<PASS [0.7,1.3] \| FAIL>> |
| H (Hurst exponent) | <<X.XXX>> | <<X.XXX>> | <<0.XXX>> | <<PASS [0.6,0.8] \| FAIL>> |
| η (Fisher anisotropy) | <<X.XXX>> | <<X.XXX>> | <<0.XXX>> | <<PASS (> 0.5) \| FAIL \| ABSTAIN_rd>> |

**Residual-echo sanity check**:

* `|d_β|` vs noise_diff_tol = <<0.05>> : <<PASS (> tol, meaningful difference) \| WARN (< tol, residual echo risk)>>
* `|d_H|` vs noise_diff_tol = <<0.05>> : <<PASS \| WARN>>
* Final residual-echo verdict: <<no residual echo \| residual echo warning>>

**Rank-deficient check (for η specifically)**:

* `seq_len` used = <<4096>>
* `hidden_size` = <<768>>
* `rank_deficient` flag = <<False \| True>>
* If True: η FAIL/PASS results are NOT counted toward F6; see §4.

### 3.4 Avalanche analysis (F5)

**Goal**: Verify that the avalanche-size distribution measured on
trained `cid_full` is consistent with a power law of exponent
τ ≈ 1.5 (Beggs-Plenz mean-field directed-percolation universality
class).

**Methodology**:

* Same checkpoint as §3.3
* Avalanche detector: `detect_avalanches(hidden_states,
  threshold_sigma=2.0)` (Beggs-Plenz protocol)
* Power-law fit: `fit_power_law(sizes)` (Clauset-Shalizi-Newman MLE
  with bootstrap p-value, n_bootstrap=1000)
* Comparison against exponential: `compare_with_exponential()`

**Result files**:

* `phase1/avalanche/results.json`
* `phase1/avalanche/plots/`

**Headline numbers**:

| Quantity | Value | UID prediction | Verdict |
|---|---|---|---|
| τ (Clauset MLE) | <<X.XX ± X.XX>> | 1.5 ± 0.2 | <<PASS \| FAIL>> |
| x_min | <<XX.X>> | — | (informational) |
| n_tail | <<NNNN>> | ≥ 100 required for fit | <<OK \| insufficient>> |
| KS statistic | <<0.XXX>> | < 0.05 desired | (informational) |
| KS p-value | <<0.XXX>> | > 0.1 (power-law plausible) | <<PASS \| FAIL>> |
| Log-likelihood ratio vs exponential | <<+X.XX>> | > 0 (power-law preferred) | <<PASS \| FAIL>> |

### 3.5 Energy benchmark (F7)

**Goal**: Measure above-idle energy per token for `cid_full` and
`transformer` at iso-PPL and verify the ≥ 3× ratio prediction.

**Methodology**:

* Sampler: <<pynvml @ 25 Hz>> (fallback `nvidia-smi` if unavailable)
* Idle window: <<2.0>> seconds
* Warmup forwards: <<50>>
* Measure forwards: <<500>>
* Modes tested: <<["prefill", "decode"]>>
* Batch size: <<16>>
* Seq len: <<1024>>
* Decode new tokens per iteration: <<64>>
* Hardware: <<NVIDIA H100 80GB HBM3>>

**Result files**:

* `phase1/energy/results.json` (schema: `energy_v2.1_batch4`)
* `phase1/energy/verdict.md`
* `phase1/energy/traces/` (power-vs-time traces)

**Headline numbers (decode mode)**:

|   | `transformer` | `cid_full` | Ratio (Trans/CID) |
|---|---|---|---|
| Idle power (W) | <<XXX.X>> | <<XXX.X>> | — |
| Above-idle power (W) | <<XXX.X>> | <<XXX.X>> | <<X.XX×>> |
| Raw energy / token (mJ) | <<X.XXXX>> | <<X.XXXX>> | <<X.XX×>> |
| **Above-idle energy / token (mJ)** | <<X.XXXX>> | <<X.XXXX>> | **<<X.XX×>>** |
| Eval PPL at this checkpoint | <<XX.XX>> | <<XX.XX>> | (must be within ±5% to count as iso-PPL) |
| Idle fraction of total energy | <<XX.X%>> | <<XX.X%>> | (if > 30%, prefer above-idle metric) |

**F7 verdict**: <<PASS — above-idle ratio ≥ 3.0× | FAIL — above-idle ratio < 3.0× | PARTIAL — passes on decode but not prefill, etc.>>

[optional: mention prefill numbers as informational]

---

## 4. Anomalies and surprises

> List any result that **deviates by more than 20% from the
> pre-registered expectation**, or that surprised the authors in a
> way that may affect interpretation. For each anomaly:
> (1) describe the deviation,
> (2) propose a hypothesis on its cause,
> (3) state what (if anything) should be done in Phase 2.

### 4.1 <<Anomaly title, e.g. "η rank-deficiency on 768-d / 1024-S configurations">>

**Observation**: <<...>>

**Hypothesis**: <<...>>

**Phase 2 follow-up**: <<re-run with max_seq_len = 2 × hidden_size \| no action needed \| ...>>

### 4.2 [optional further anomalies]

### 4.3 No anomalies declared

[Delete this subsection if any anomaly was reported above.]

> We declare no result deviating by more than 20% from the
> pre-registered expectation in Phase 1. The closest call was
> <<which condition, with measured value vs predicted>>, well
> within the tolerance.

---

## 5. Implications for downstream phases

### 5.1 Implications for Phase 2 (300M–1B validation)

| Phase 1 outcome | Implication for Phase 2 |
|---|---|
| <<F1 passed with 2.1× shift at 100M>> | <<Tightened F1' threshold of ≥ 2× at 1B is reasonable; proceed as planned>> |
| <<F6 had 3 rank-deficient cases>> | <<Phase 2 must use max_seq_len ≥ 2 × hidden_size for all η measurements>> |
| <<F7 passed at 4.2× in decode>> | <<Phase 3 multi-hardware sweep is justified; Phase 2 will also include prefill measurement>> |
| <<...>> | <<...>> |

### 5.2 Theory paper implications

| Section of theory paper | Status after Phase 1 | Action |
|---|---|---|
| §5 sub-Ohmic spectrum prediction | <<supported \| weakened \| falsified>> | <<no change \| rewrite paragraph X \| ...>> |
| §6.1 Fisher anisotropy prediction | <<supported \| weakened \| falsified>> | <<...>> |
| §8.5 ET energy descent | <<unit-test verified, no large-scale needed>> | <<no change>> |
| §11.4 energy efficiency claim (≥ 3×) | <<supported \| weakened \| falsified>> | <<...>> |
| §14.2 zero-extra-params + OU defaults | <<supported in F8 + Contrast C>> | <<no change>> |

### 5.3 Should Phase 2 be modified?

> <<State explicitly whether Phase 1 outcomes motivate changes to
> Phase 2's scope, methodology, or pre-registered conditions.
> Any change to pre-registered conditions must comply with
> ROADMAP.md §"Cross-phase guarantees" #3 — pre-registered
> conditions for Phase 2 can ONLY be tightened, never loosened.>>

---

## 6. Limitations

This section enumerates what Phase 1 did NOT test, and what its
results cannot be used to conclude. **Any citation of Phase 1
numbers must include or link to this section.**

### 6.1 Methodological surrogates (carries over from `KNOWN_LIMITATIONS.md` §C3)

* Fisher anisotropy η is measured on the **hidden-state empirical
  covariance**, not on the parameter-space true Fisher matrix.
  Phase 1 numbers for F6 should be cited as "η on the v2.1
  hidden-state surrogate" rather than "η of the Fisher information
  matrix".
* Avalanche τ uses the Beggs-Plenz protocol on hidden-state
  z-scores, which is a mechanistic analogue of (not a strict
  identity to) the original neural-recording protocol.
* Energy numbers are measured on a single hardware platform
  (<<NVIDIA H100 80GB SXM5>>); Phase 3 will test portability.

### 6.2 Scale limitations

* Phase 1 tested 10M / 30M / 100M only. The ≥ 5× iso-loss shift
  predicted by the theory paper at LLM-relevant scales (≥ 1B) is
  NOT tested here.
* Phase 1 ablation was run at 30M only; cross-scale ablation
  trends are NOT characterised.
* Phase 1 used a single tokenizer (`gpt2`) and a single dataset
  (wikitext-103). Cross-tokenizer / cross-dataset generalisation
  is NOT tested.

### 6.3 What Phase 1 cannot tell us

* Whether the trained CID model **generalises** to unseen domains
  better than Transformer (this is Phase 2 deliverable 2.4).
* Whether the energy advantage **transfers** to other hardware
  (Phase 3).
* Whether **independent teams** can reproduce these numbers from
  the public artifacts alone (Phase 4).
* Whether the theory paper's **quantum-tier (QID)** or
  **field-geometric-tier (FID)** predictions hold (these are
  classical surrogates in this codebase per
  `KNOWN_LIMITATIONS.md` §C1; full validation requires quantum
  hardware).

### 6.4 Known data-quality issues encountered in Phase 1

> <<List any data-quality issue encountered, e.g. "On seed 44, the
> H100 node experienced thermal throttling during run 7 of the
> energy benchmark; that single run was discarded and re-run, see
> phase1/energy/notes/thermal_event_seed44.md for the audit
> trail.">>

If no data-quality issue was encountered, state explicitly:

> No data-quality issues were encountered during Phase 1 execution.
> Every `MANIFEST.json` entry has an intact SHA-256 hash; every
> training run completed without divergence; every benchmark
> completed without sampler-side errors.

---

## 7. Reproducibility appendix

### 7.1 Exact CLI invocations

```bash
# 7.1.1 Scaling-law experiment
python experiments/run_scaling_law.py \
    --data_path data/wikitext-103/train.jsonl \
    --tokenizer_path gpt2 \
    --families transformer transformer_plus_tricks cid_full \
               cid_full_no_et cid_full_fft_noise \
    --scales 10M 30M 100M \
    --seeds 42 43 44 \
    --target_tokens_per_param 20.0 \
    --batch_size 32 --max_seq_len 1024 \
    --output_dir results/phase1/scaling_law

# 7.1.2 Eleven-way ablation
python experiments/run_ablation.py \
    --data_path data/wikitext-103/train.jsonl \
    --tokenizer_path gpt2 \
    --scale 30M --epochs 3 \
    --seeds 42 43 44 \
    --batch_size 16 --max_seq_len 1024 \
    --output_dir results/phase1/ablation

# 7.1.3 Critical-exponent measurement (with eta)
python experiments/run_critical_exponents.py \
    --checkpoint results/phase1/scaling_law/checkpoints/cid_full_100M_seed42.pt \
    --baseline_checkpoint results/phase1/scaling_law/checkpoints/transformer_100M_seed42.pt \
    --data_path data/wikitext-103/test.jsonl \
    --tokenizer_path gpt2 \
    --max_seq_len 4096 --batch_size 4 --n_sequences 10000 \
    --eta_threshold 0.5 --eta_max_samples 256 \
    --noise_diff_tol 0.05 \
    --output_dir results/phase1/critical_exponents

# 7.1.4 Energy benchmark
python experiments/run_energy_benchmark.py \
    --families cid_full transformer transformer_plus_all_tricks \
    --checkpoint_dir results/phase1/scaling_law/checkpoints \
    --scale 100M --seeds 42 \
    --mode decode --new_tokens_per_decode 64 \
    --batch_size 16 --seq_len 1024 \
    --n_warmup 50 --n_measure 500 \
    --sample_rate_hz 25.0 --idle_window_seconds 2.0 \
    --sampler_preference pynvml \
    --output_dir results/phase1/energy
```

### 7.2 Environment

| Item | Version / value |
|---|---|
| Python | <<3.11.9>> |
| PyTorch | <<2.4.0+cu124>> |
| CUDA | <<12.4>> |
| Driver | <<555.42.06>> |
| pynvml | <<11.5.0>> |
| transformers | <<4.45.0>> |
| OS / kernel | <<Ubuntu 22.04 LTS / 5.15.0-...>> |
| GPU | <<NVIDIA H100 80GB SXM5 × 32 (8 per node × 4 nodes)>> |

### 7.3 Wall-clock breakdown per experiment

| Experiment | Wall-clock (h) | Compute (GPU-h) |
|---|---|---|
| Scaling law (5 families × 3 scales × 3 seeds) | <<NNN>> | <<NN,NNN>> |
| Ablation (11 variants × 3 seeds) | <<NN>> | <<N,NNN>> |
| Critical exponents | <<N>> | <<N>> |
| Energy benchmark | <<N>> | <<N>> |
| **Phase 1 total** | <<NNN>> | <<NN,NNN>> |

### 7.4 Result-file integrity

The `MANIFEST.json` for Phase 1 records the SHA-256 hash of every
result file. To verify locally:

```bash
python scripts/verify_results_integrity.py phase1
# Expected output: silent success + exit code 0.
```

If any hash mismatch is reported, **do not cite the affected file**
until the discrepancy is investigated; file an issue per
`KNOWN_LIMITATIONS.md` §D.

### 7.5 How to cite Phase 1 results

> LI, Gui, JIE, Dangyang, & KANG, Haitao. (2026). Intelligence Is a
> Non-Equilibrium Field: A Three-Tier Physical Theory of Unified
> Intelligo-Dynamics (UID), v2.1 reference implementation,
> Phase 1 empirical results (commit `<<abcdef1>>`).
> Zenodo. https://doi.org/10.5281/zenodo.20372493

When citing a single number, please also include:

* the seed (or "averaged over seeds <<{42, 43, 44}>>"),
* the hardware platform,
* the v2.1 batch number of the producing script (e.g. "energy
  v2.1 batch 4"),
* the relevant §6 limitation caveat if any applies.

### 7.6 Negative-result policy reminder

Per `results/README.md` §"Negative-result policy", any FAIL or
PARTIAL verdict listed in §2 above is published with the same
prominence as the PASS verdicts and is permanently retained in this
directory (i.e., subsequent phases cannot delete this report even if
they re-test and pass).

---

## 8. Authors' statement of commitment

> By publishing this report, we (the authors) affirm:
>
> 1. **No selective reporting.** Every experiment listed in
>    `ROADMAP.md` §Phase 1 was executed; no measurement was hidden,
>    re-run with cherry-picked seeds, or selectively reported.
> 2. **No retroactive adjustment.** The pre-registered F1–F8
>    conditions in `ROADMAP.md` were not modified between phase
>    start and phase end.
> 3. **Open data.** All result files, training logs, and seeds are
>    in this directory (or linked from `MANIFEST.json` to public
>    archives for files > 10 GB).
> 4. **Honest limitations.** §6 of this report enumerates every
>    limitation we are aware of; we commit to amending this section
>    if newly discovered limitations come to light later.
> 5. **Negative results unhidden.** Any FAIL or PARTIAL verdict in
>    §2 is reported in §1 (headline summary) with the same
>    prominence as PASS verdicts.

| Signatory | Role | Date |
|---|---|---|
| <<Gui LI>> | <<Project lead / corresponding author>> | <<YYYY-MM-DD>> |
| <<Dangyang JIE>> | <<Engineering lead>> | <<YYYY-MM-DD>> |
| <<Haitao KANG>> | <<Verification lead>> | <<YYYY-MM-DD>> |

---

<!-- END OF TEMPLATE -->
```
