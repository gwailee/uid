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

