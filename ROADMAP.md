<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-28

Validation roadmap for the UID Theory reference implementation,
with pre-registered falsification conditions and version-by-version
completion status.
-->

# UID Validation Roadmap

This document is the **single source of truth** for what the UID
project plans to test, in what order, and by what falsification
criteria. Every phase below has explicit pre-registered conditions
that, if violated, count as **falsification** of the corresponding
UID claim. We commit to publishing all results regardless of outcome.

本文件是 UID 项目验证计划的**单一可信源**：每个阶段都有明确的预注册
证伪条件——一旦未满足，即视为对应 UID 主张被**证伪**。我们承诺无论
结果如何都公开发布。

---

## Master timeline

| Phase | Time | Status | Deliverable |
|---|---|---|---|
| **Phase 0** | 2026 Q2 | ✅ **COMPLETE (v2.1)** | Validation infrastructure ready |
| **Phase 1** | 2026 Q2–Q3 | 🔄 **IN PROGRESS** | 10M–100M scaling + 11-way ablation + critical exponents |
| **Phase 2** | 2026 Q3–Q4 | ⏳ planned | 300M–1B validation + tightened thresholds |
| **Phase 3** | 2026 Q4 | ⏳ planned | Multi-hardware (H100 / A100 / edge) energy comparison |
| **Phase 4** | 2027 Q1 | ⏳ planned | Independent third-party reproduction |
| **Phase 5** | 2027 Q2+ | ⏳ planned | Theory paper update + peer-reviewed journal submission |

A phase is marked **COMPLETE** only when every deliverable in the
"Pre-registered exit criteria" subsection has been met, and the
results have been pushed to `results/` under the corresponding
version tag.

---

## Phase 0 — Validation infrastructure (2026 Q2)

**Status: ✅ COMPLETE — shipped in v2.1 (2026-05-28).**

### Goal

Build the complete software infrastructure required to run rigorous
validation experiments, so that Phase 1 onwards is purely a matter of
compute and time, not engineering.

### Deliverables (all complete)

| # | Deliverable | Where | v2.1 status |
|---|---|---|---|
| 0.1 | CID master-equation reference implementation | `uid_theory/cid/` | ✅ ET symmetric attention + zero-extra-params vortex + OU noise |
| 0.2 | QID classical surrogate | `uid_theory/qid/` | ✅ Zero-extra-params defaults + Berry phase + QFDT |
| 0.3 | FID diagnostic probe | `uid_theory/fid/` | ✅ Direct η + Ricci surrogate + JSON-safe info |
| 0.4 | Modern Transformer baseline | `model/modern_transformer.py` | ✅ RoPE + RMSNorm + SwiGLU |
| 0.5 | "Transformer + all known tricks" critical contrast | `model/known_tricks_baseline.py` | ✅ Real, non-degenerate `linear_extra` |
| 0.6 | 11-way ablation suite | `uid_theory/verification/ablation_suite.py` | ✅ Includes §8.5 / §14.2 isolation variants |
| 0.7 | Iso-FLOP scaling-law driver | `experiments/run_scaling_law.py` | ✅ Saves unified v2.1 checkpoint schema |
| 0.8 | Critical-exponent battery with η | `experiments/run_critical_exponents.py` | ✅ noise-OFF vs noise-ON + η verdict |
| 0.9 | Real-hardware energy meter | `uid_theory/verification/energy_meter.py` | ✅ pynvml + idle baseline + above-idle + prefill/decode |
| 0.10 | End-to-end pipeline | `experiments/run_all.py` | ✅ Loud warnings on missing artifacts |
| 0.11 | Data loaders | `data_loaders.py` | ✅ PretrainJsonl + SftJsonl (tail-keeping truncation) |
| 0.12 | Test suite | `tests/` | ✅ 7 v2.1 test files, ~200+ test cases |
| 0.13 | CI/CD | `.github/workflows/` | ✅ Lint + tests + smoke + nightly |
| 0.14 | Documentation | `README.md` / `theory.md` / `CHANGELOG.md` / `KNOWN_LIMITATIONS.md` / this file | ✅ Bilingual (CN + EN) |

### Pre-registered exit criteria (all met)

| Criterion | How verified |
|---|---|
| Every CID master-equation term has a corresponding code module | `tests/test_cid_layer.py::TestCIDLayerParameterBudget` confirms the 4-term assembly with 6 scalar extras |
| ET energy is monotonically non-increasing under recursive application (Theory §8.5) | `tests/test_et_lyapunov.py::test_et_energy_decreases_monotonically` |
| VortexField introduces exactly +1 scalar parameter per layer (Theory §14.2) | `tests/test_et_lyapunov.py::test_vortex_introduces_exactly_one_scalar_parameter` |
| All v2.1 keys propagate three levels deep (CID → QID → FID) | `tests/test_fid_layer.py::TestV21TogglePropagation` |
| FID's `info` dict is JSON-safe even with `curvature_weight > 0` | `tests/test_fid_layer.py::TestInfoIsJsonSafe` |
| Fisher anisotropy η is directly measurable from a trained model | `tests/test_critical_exponents.py::TestFisherAnisotropyEta` |
| Energy meter cleanly refuses to run on CPU-only platforms | `tests/test_energy_meter.py::TestCpuPlatformRefusal` |
| Data loaders handle empty / malformed / extreme-length records | `tests/test_data_loaders.py::TestEncodingResilience` |
| Truncation preserves prompt tail (instruction-tuning convention) | `tests/test_data_loaders.py::TestSftJsonlGetItem::test_truncation_keeps_recent_prompt` |
| Documentation honestly states what v2.1 can and cannot validate | `README.md` §"Honest Statement" + `KNOWN_LIMITATIONS.md` §C |

---

## Phase 1 — Small-to-medium scaling (2026 Q2–Q3)

**Status: 🔄 IN PROGRESS.**

### Goal

Run the eight pre-registered falsification conditions from
`README.md` §"Pre-registered falsification conditions" at scales
10M–100M, with multiple seeds per cell, and publish all results to
`results/phase1/`.

### Deliverables

| # | Deliverable | Where output goes |
|---|---|---|
| 1.1 | Iso-FLOP scaling-law results across 10M / 30M / 100M for `cid_full`, `transformer`, `transformer_plus_all_tricks`, `cid_full_no_et`, `cid_full_fft_noise`, with 3 seeds each | `results/phase1/scaling_law/` |
| 1.2 | 11-way ablation at 30M with 3 seeds | `results/phase1/ablation/` |
| 1.3 | Critical-exponent measurement (β, H, η) on the best-trained `cid_full` and `transformer` checkpoints, with noise-OFF vs noise-ON contrast | `results/phase1/critical_exponents/` |
| 1.4 | Avalanche-size τ via Clauset-Shalizi-Newman MLE on the same checkpoints | `results/phase1/avalanche/` |
| 1.5 | Energy benchmark (prefill + decode, both raw and above-idle) at 100M | `results/phase1/energy/` |
| 1.6 | Phase-1 summary report (markdown + bibtex-ready) | `results/phase1/REPORT.md` |

### Pre-registered falsification conditions

> If **any** of the following conditions is not met after Phase 1
> completes, we will publicly acknowledge the corresponding UID claim
> as **falsified** and update the theory paper accordingly.

| # | Falsification condition | Reference |
|---|---|---|
| **F1** | At 100M, `cid_full`'s iso-loss point sits **≥ 1.5×** to the left of `transformer_plus_all_tricks`'s curve | UID's "physical framework" claim |
| **F2** | At 100M, `cid_full`'s iso-loss point sits **≥ 3×** to the left of `transformer`'s curve | README prediction 5 |
| **F3** | On the trained `cid_full`, with noise injection OFF, β ∈ [0.7, 1.3] in ≥80% of layers | README prediction 3 |
| **F4** | On the trained `cid_full`, with noise injection OFF, H ∈ [0.6, 0.8] | README prediction 2 |
| **F5** | On the trained `cid_full`, avalanche τ via Clauset MLE is in [1.3, 1.7] with KS p > 0.1 | README prediction 1 |
| **F6** | On the trained `cid_full`, Fisher anisotropy η > 0.5 (excluding rank-deficient runs) | README prediction 4 (Theory §6.1) |
| **F7** | Measured above-idle energy per token (decode mode) on `cid_full` is ≤ 1/3 of `transformer` at iso-perplexity | README prediction 6 |
| **F8** | `cid_full_no_et` perplexity is noticeably worse than `cid_full` (paired t-test on three seeds, p < 0.05) | §8.5 engineering contribution |

### Pre-registered exit criteria

Phase 1 is COMPLETE when:

* All six deliverables above are pushed to `results/phase1/`.
* The Phase-1 summary report explicitly states the pass/fail outcome
  of each of F1–F8.
* The result files include training logs, seeds, hardware
  configuration, and v2.1 commit hash for full reproducibility.

### Realistic resource estimate

| Item | Estimate |
|---|---|
| Training compute | ~80,000 GPU-hours on H100, or equivalent |
| Wall-clock | 8–12 weeks (with parallelisation across multiple nodes) |
| Storage | ~3 TB for checkpoints + ~100 GB for hidden-state samples |
| Headcount | 1 senior engineer + 1 RA (rotating) |

---

## Phase 2 — Larger-scale validation (2026 Q3–Q4)

**Status: ⏳ PLANNED.**

### Goal

Push Phase 1's eight falsification conditions to the 300M–1B parameter
regime, where Chinchilla-style scaling-law extrapolation is most
informative. Tighten the F1 / F2 thresholds from "≥ 1.5× / ≥ 3×" to
"≥ 2× / ≥ 5×" — the targets from the original UID paper.

### Deliverables

| # | Deliverable |
|---|---|
| 2.1 | Scaling-law extension to 300M and 1B for `cid_full`, `transformer`, `transformer_plus_all_tricks` |
| 2.2 | Critical-exponent measurement at 1B scale |
| 2.3 | Energy benchmark at 1B scale (prefill + decode) |
| 2.4 | Generalisation evaluation (zero-shot perplexity on 5 unseen domains) |
| 2.5 | Phase-2 summary report |

### Pre-registered tightened falsification conditions (replace F1 / F2)

| # | Tightened condition |
|---|---|
| **F1'** | At 1B, `cid_full`'s iso-loss point sits **≥ 2×** to the left of `transformer_plus_all_tricks`'s curve |
| **F2'** | At 1B, `cid_full`'s iso-loss point sits **≥ 5×** to the left of `transformer`'s curve |

### Realistic resource estimate

| Item | Estimate |
|---|---|
| Training compute | ~400,000 GPU-hours on H100 |
| Wall-clock | 12–16 weeks |
| Storage | ~20 TB |
| Headcount | 2 senior engineers + 1 RA |

---

## Phase 3 — Multi-hardware energy comparison (2026 Q4)

**Status: ⏳ PLANNED.**

### Goal

Verify that the v2.1 above-idle energy advantage observed in Phase 1
generalises across different NVIDIA hardware generations and to
non-NVIDIA accelerators where possible. Test the hypothesis that
the energy advantage is hardware-portable (a property of the CID
architecture, not of any specific GPU).

### Deliverables

| # | Deliverable |
|---|---|
| 3.1 | Energy benchmark at 100M and 1B on H100 (Hopper) |
| 3.2 | Energy benchmark at 100M and 1B on A100 (Ampere) |
| 3.3 | Energy benchmark at 100M on RTX 4090 (consumer) |
| 3.4 | Energy benchmark at 100M on edge device (Jetson Orin) |
| 3.5 | Cross-hardware portability report |

### Pre-registered exit criterion

The above-idle energy-per-token ratio of `cid_full` over `transformer`
at iso-perplexity must be **≥ 2.5× on every hardware platform tested**.
If the advantage disappears on any platform, the README prediction 6
will be revised from "≥ 3×" to "≥ 3× on data-centre GPUs only".

---

## Phase 4 — Independent reproduction (2027 Q1)

**Status: ⏳ PLANNED.**

### Goal

Invite at least three independent research teams to reproduce the
Phase 1 and Phase 2 critical experiments using only the public v2.1
codebase, public datasets, and published configuration files.
Reproduction must NOT require any private communication with the UID
authors.

### Deliverables

| # | Deliverable |
|---|---|
| 4.1 | Publicly hosted Phase 1 / Phase 2 reproduction kit (configs + seeds + expected outputs) |
| 4.2 | Three or more independent reproduction reports (linked from `results/phase4/`) |
| 4.3 | Discrepancy analysis: any reproduction result that differs from the original Phase 1 / 2 by > 10% must be analysed and the cause documented |

### Pre-registered exit criterion

* At least **two of the three** independent reproductions must
  successfully reproduce the F1' / F2' falsification conditions
  within ± 10%.
* All reproduction reports must be published openly (with the
  reproducing team's consent).

---

## Phase 5 — Theory-paper update + peer review (2027 Q2+)

**Status: ⏳ PLANNED.**

### Goal

Based on the empirical results from Phases 1–4, write a revised
version of the UID theory paper that:

* Reports the actual measured values (with confidence intervals) for
  each prediction, not just the projected ranges.
* Explicitly distinguishes "confirmed by direct measurement" from
  "supported by analogy with biological data" from "unfalsified but
  not yet directly tested".
* Acknowledges any falsified predictions, with an analysis of which
  parts of the theory survive and which need revision.

### Deliverables

| # | Deliverable |
|---|---|
| 5.1 | Revised theory paper, posted to arXiv as v2.0 of the preprint |
| 5.2 | Submission to a peer-reviewed venue (target: *Physical Review E* or *Nature Communications Physics*) |
| 5.3 | Response-to-reviewers document (published once review concludes) |
| 5.4 | Final accepted version (linked from `README.md` if accepted) |

### Pre-registered exit criterion

The submitted paper must be reviewed by at least two anonymous
referees with expertise in non-equilibrium statistical physics AND
deep learning. If the paper is rejected, the rejection letter (with
referees' permission, anonymised) will be published in `results/phase5/`
alongside the response.

---

## Cross-phase guarantees

These commitments apply across **every** phase:

1. **All result files published openly** under `results/phase{N}/`,
   with version tag, commit hash, hardware configuration, random
   seeds, and training logs.
2. **Negative results published with equal prominence as positive
   ones.** If a falsification condition fails, that finding will be
   on the front page of the README, not buried in an appendix.
3. **No retroactive adjustment of falsification conditions.** Once a
   phase begins, its pre-registered conditions are frozen. New
   conditions can only be added in *later* phases.
4. **Honest update of `KNOWN_LIMITATIONS.md` after each phase.** Any
   newly discovered defect — even one that was masked by a different
   bug — gets a §-entry under its discovery version.
5. **No selective metric reporting.** If a benchmark is measured, it
   is reported in full (mean, std, all seeds, all hardware platforms
   tested), not cherry-picked.
6. **Conflict-of-interest declaration.** The authors are employees
   of Suzhou Jodell Robotics Co., Ltd. and the company holds
   commercial rights to the UID framework. This commercial interest
   is declared on every submitted paper. The validation methodology
   (especially F1–F8 in Phase 1) is designed precisely so that
   commercial interest cannot bias the conclusion: every condition
   is a numerical pass/fail test on publicly committed thresholds.

---

## How to follow / contribute

* **Watch this repository** for phase-completion announcements
  (we tag each phase's completion as a Git release).
* **Subscribe to the Zenodo DOI** for archival snapshots of each
  validated version.
* **File an issue** if you want to volunteer for Phase 4 independent
  reproduction (especially welcome: groups with access to H100 / A100
  clusters who can run F1' / F2').
* **Email lig@jodell.cn** with subject `[UID Roadmap]` for any other
  research-collaboration enquiries.

跟进 / 贡献渠道：
* **Watch 本仓库**接收阶段完成公告（每个阶段完成会打 Git tag）。
* **订阅 Zenodo DOI** 获取每个已验证版本的归档快照。
* **提 issue** 申请参与 Phase 4 独立复现（特别欢迎拥有 H100 / A100
  集群可跑 F1' / F2' 的团队）。
* **邮件 lig@jodell.cn**（主题 `[UID Roadmap]`）洽谈其他研究合作。

---

## Closing statement

> A research programme stands or falls by the questions it agrees in
> advance to answer "no" to.
>
> UID has committed in this document to fifteen pre-registered
> falsification conditions across five phases. Every one of them is
> a question we agree in advance to answer honestly, even — especially
> — when the answer is no.
>
> If, by the end of Phase 5, more than half of those fifteen
> conditions have failed, the UID theory will have been falsified
> in the strict Popperian sense, and we will say so publicly. If
> all fifteen succeed, the case for UID as a unified physical theory
> of intelligence will be vastly stronger than any qualitative
> argument from biology or thermodynamics alone could establish.
>
> Either outcome is a win for science.
>
> 一个研究计划的价值，取决于它事先承诺会回答"否"的那些问题。本文件中
> UID 跨五个阶段共做出 15 项预注册证伪承诺，每一项都是我们事先承诺
> 会诚实回答的问题——即使（尤其当）答案是否定的。
>
> 如果到 Phase 5 结束时，15 项中超过一半失败，UID 理论将在严格的波普
> 尔意义上被证伪，我们会公开承认。若 15 项全部通过，UID 作为统一智能
> 物理理论的论据将远比任何来自生物学或热力学的定性论证更强。
>
> 两种结果都是科学的胜利。
