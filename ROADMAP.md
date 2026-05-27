<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-27
-->

# UID Validation Roadmap

**Status**: Phase 0 substantially complete (infrastructure ready). Phases 1-7 ahead.  
**Last updated**: 2026-05-30  
**Document version**: v1.1

This document gives the **public, pre-registered timeline** for validating UID's empirical claims. We commit to **publish results — positive or negative — at each milestone**, including via independent third-party publication channels (see §10 below).

---

## 0. Guiding Principles

1. **Pre-registration**: Falsification criteria are committed to **before** experiments are run, not after.
2. **Public commitment**: All results (positive, negative, or inconclusive) will be published.
3. **Honest scope**: Only the CID tier can be verified by this codebase. QID requires real quantum hardware; FID requires PDE solvers. These boundaries are respected throughout.
4. **Independent reproduction**: Single-team results are insufficient. We actively invite reproduction.
5. **Negative results are valuable**: Falsifying a theory advances science as much as confirming it.

---

## Phase 0 — Infrastructure (✅ SUBSTANTIALLY COMPLETE, 2026 Q2)

**Goal**: Rebuild the validation suite to address v0.1 methodological flaws and prepare for rigorous large-scale validation.

| Task | Status | Notes |
|---|---|---|
| Acknowledge v0.1 limitations publicly | ✅ Done | See [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) |
| Implement Clauset-Shalizi-Newman power-law estimator | ✅ Done | Replaces v0.1's unreliable log-binned regression |
| Implement DFA-based Hurst estimator | ✅ Done | Replaces v0.1's R/S method |
| Implement proper Beggs-Plenz avalanche detector | ✅ Done | Z-scored threshold crossings on hidden states |
| Implement modern Transformer baseline (RoPE + RMSNorm + SwiGLU) | ✅ Done | Replaces v0.1's TinyTransformerLM toy |
| Implement "Transformer + all known tricks" critical baseline | ✅ Done | The crucial control: if CID doesn't beat this, the "physical framework" claim is falsified |
| Add `set_noise_injection(False)` API | ✅ Done | Breaks v0.1's circular logic in critical-exponent tests |
| Implement real `nvidia-smi` energy meter | ✅ Done | Replaces v0.1's Landauer-limit theoretical arithmetic |
| Set up GitHub Actions CI/CD | ✅ Done | Lint + tests + smoke + nightly |
| Write unit tests for all verification utilities | ✅ Done | ~50 tests covering core modules |
| Add 9-way ablation (including `cid_no_memory`) | ✅ Done | Was missing in v0.1 |
| Mark QID/FID modules as "not verifiable here" | ✅ Done | With prominent runtime warnings |
| Define pre-registered falsification criteria | ✅ Done | See §3 below |
| **MVP pipeline-proof run** | 🔧 **In progress** | Single 10M-model × 1-epoch × WikiText-2 run to prove the pipeline works end-to-end; results to be committed to `results/pipeline_proof_v0.1/` by 2026-06-15 |
| **Compute resource agreement** | 🔧 **In progress** | Securing GPU access for Phase 1 (see §9) |
| **Independent-publication agreement** | 🔧 **In progress** | Partnership with university lab for guaranteed result disclosure (see §10) |

---

## Phase 1 — Small-Scale Validation (🎯 2026 Q3, July–September)

**Goal**: Run the validation pipeline at 10M–100M scale and report results publicly.

**Estimated compute**: ~1,500 GPU-hours on A100/H100  
**Estimated wall time**: 8–10 weeks  
**Estimated cost**: ~$15,000–25,000 USD (cloud-equivalent)

**Pre-registered hypotheses** (failure to meet = claim falsified):

| Hypothesis | Falsification threshold | Statistical requirement |
|---|---|---|
| H1: CID outperforms strong Transformer in scaling law | CID curve must be ≥1.5× left of baseline at 100M scale (iso-loss) | At least 3 seeds, z-score ≥ 2 |
| H2: CID beats "Transformer + all tricks" | Improvement must be statistically significant | Bonferroni-corrected p < 0.05 across 9 ablations |
| H3: Critical exponents emerge with noise OFF | β ∈ [0.7, 1.3] in ≥80% of layers AND H ∈ [0.6, 0.8] | Clauset MLE + KS test, p > 0.1 |

**Deliverables** (each committed to `results/`):

- [ ] `scaling_law_v1.0/`: full scaling curve, 3 seeds × 5 scales × 3 model families
- [ ] `ablation_v1.0/`: 9-way ablation at 30M and 100M scales
- [ ] `critical_exponents_v1.0/`: emergence test with noise injection OFF
- [ ] `energy_v1.0/`: real `nvidia-smi` measurements at 100M scale
- [ ] **A public blog post / preprint reporting all results** (no matter the outcome)

**Decision point**: At end of Phase 1, if H1-H3 are not met:
- The corresponding claims will be publicly marked as **falsified at small scale**
- The theory paper (theory.md) will be updated to reflect this
- Phase 2 will proceed only if there is a credible path to test the hypotheses at larger scale

---

## Phase 2 — Mid-Scale Validation (🎯 2026 Q4, October–December)

**Goal**: Scale to 300M–1B and either confirm or refute Phase 1 results.

**Estimated compute**: ~12,000 GPU-hours  
**Estimated wall time**: 10–12 weeks  
**Estimated cost**: ~$120,000–200,000 USD (cloud-equivalent)

**Falsification thresholds tighten**:
- CID curve ≥3× left of Transformer at 1B scale
- ≥1.5× left of "all tricks" baseline at 1B scale
- All critical exponents within tighter bands (β ∈ [0.8, 1.2], H ∈ [0.65, 0.75])

**Conditional execution**: Phase 2 only proceeds if Phase 1 results meet H1-H3 with margin (i.e., scaling-law slopes are not at the boundary). Otherwise, we conclude that UID's quantitative claims are falsified at the scales testable with our resources.

---

## Phase 3 — Hardware Energy Validation (🎯 2027 Q1, January–March)

**Goal**: Real-world energy benchmarks on multiple hardware platforms.

**Hardware coverage**:
- NVIDIA H100 (data-center)
- NVIDIA A100 (data-center)
- NVIDIA RTX 4090 (workstation)
- NVIDIA Jetson AGX Orin (edge)
- (Optional) AMD MI300X if access available

**Deliverables**:
- [ ] Energy per token measurements at production batch sizes
- [ ] Comparison with Transformer baseline at iso-PPL conditions
- [ ] Multi-platform consistency report
- [ ] Cost per million tokens at typical cloud pricing

---

## Phase 4 — Independent Reproduction (🎯 2027 Q2, April–June)

**Goal**: External teams reproduce all Phase 1-3 results.

**Mechanisms**:
- **Containerized reproduction kit**: Docker image with pinned dependencies, exact data preprocessing, and one-command experiment runs
- **Reproduction grants**: $5,000–10,000 USD per reproduced experiment family (funded by Suzhou Jodell Robotics)
- **Public leaderboard**: List of reproducing labs and their results (positive AND negative)
- **Encouraged adversarial reproduction**: We explicitly invite teams that *expect* to falsify our results

**Deliverables**:
- [ ] At least 2 independent reproductions of Phase 1
- [ ] At least 1 independent reproduction of Phase 2
- [ ] Public discrepancy report (if any)

---

## Phase 5 — Theory Update & Journal Submission (🎯 2027 Q3, July–September)

**Goal**: Based on Phase 1-4 results, update the theory and seek peer review.

**Three possible outcomes**:

### Outcome A: Hypotheses confirmed
- Submit to *Nature Machine Intelligence*, *Communications Physics*, or *Physical Review X*
- Update theory.md with empirical evidence
- Prepare engineering deployment guide for industry

### Outcome B: Hypotheses partly falsified
- Update theory.md acknowledging the boundaries of applicability
- Identify which sub-claims survive (e.g., the unified framework may still be valuable even if 5× efficiency isn't reached)
- Submit a more modest claim to journals

### Outcome C: Hypotheses fully falsified
- Publish a transparent "negative results" paper
- UID's contribution becomes the **framework and methodology**, not the specific quantitative predictions
- Theory.md will be rewritten to reflect this

**All three outcomes are valuable. Science advances by elimination of wrong hypotheses, not only by confirming right ones.**

---

## Phase 6 — QID Quantum-Hardware Integration (🎯 2028+, depends on quantum-hardware maturity)

**Goal**: Test QID's quantum-coherence claims on actual quantum hardware.

**Prerequisites**:
- Access to NISQ-era quantum processors (IBM Quantum, IonQ, Quantinuum, or Chinese systems like Origin Quantum)
- ≥100 logical qubits with sufficient coherence time
- Quantum-classical hybrid framework (e.g., Qiskit, PennyLane)

**Note**: Phase 6 will only begin when quantum hardware reaches sufficient maturity. Until then, the QID tier remains formally **unverifiable** by this project. The classical-emulation code in `uid_theory/qid/` serves only as an API sketch for future quantum integration.

**No specific timeline** — depends on industry-wide quantum-hardware progress.

---

## Phase 7 — FID Field-Equation Numerical Solver (🎯 2028+, R&D phase)

**Goal**: Develop a numerical solver for FID field equations on simplified information manifolds.

**Prerequisites**:
- Collaboration with applied mathematics / numerical PDE experts
- Development of a finite-element or spectral solver for the FID field equations
- Comparison with analytical solutions on toy manifolds (e.g., S², T²)

**Note**: Phase 7 is research-grade, not engineering. It may yield publishable mathematical results long before practical applications. Until a solver exists, FID's geometric claims remain **unverifiable** by this project. The diagnostic probes in `uid_theory/fid/` serve only as measurement utilities, not as solvers.

**No specific timeline** — depends on research progress and collaboration availability.

---

## 9. Compute Resources

Validation at 1B-scale requires substantial compute. Our plan:

### Confirmed Sources

| Source | Capacity | Notes |
|---|---|---|
| **Suzhou Jodell internal cluster** | ~200 GPU-hours/week of A100 | Used for Phase 0 MVP and Phase 1 small scales |
| **Cloud burst capacity** | Up to ~5,000 GPU-hours of A100 (budget-limited) | AWS/Aliyun for peak runs |

### Sources Under Discussion

| Source | Status | Target capacity |
|---|---|---|
| University partnership | Negotiating with 2 universities | ~3,000 GPU-hours of A100/H100 |
| National HPC center | Application submitted | TBD |
| Hardware vendor collaboration | Initial outreach to 2 vendors | Loan equipment + co-investment |

### Risk Mitigation

- **If compute falls short**: Phase 1 will be executed at maximum-affordable scale (likely 100M cap instead of 1B); Phase 2 may be delayed
- **If compute exceeds plan**: Additional scales (3B, 10B) will be added to strengthen evidence

**Transparency commitment**: At Phase 1 launch, we will publish the actual confirmed compute budget and any constraints it imposes on the experimental design.

---

## 10. Independent Result Disclosure Mechanism

**The problem**: A commercial entity (Suzhou Jodell Robotics) has obvious incentives to suppress negative results. How can the community trust that we'll publish failures?

**Our solution**: Bind ourselves with an irrevocable mechanism.

### Mechanism Design

1. **University Custodian Agreement** (in negotiation, target signing 2026 Q2):
   - A partner university lab will receive **complete raw data** from every Phase 1-3 experiment in real time
   - The university has **independent authority** to publish the results after a 12-month embargo, regardless of Suzhou Jodell's position
   - Suzhou Jodell waives any veto right

2. **Pre-registration platform**:
   - All hypotheses are publicly committed in this ROADMAP.md before experiments run
   - Any post-hoc revision of falsification criteria will be flagged with a public diff in git history

3. **Public results timestamps**:
   - Phase 1 results must be published within 90 days of experiment completion
   - If Suzhou Jodell fails to publish within 90 days, the university custodian automatically publishes

### Why This Matters

Many industrial AI projects make grand claims, fail to deliver, and quietly drop the topic. **We refuse to do that.** This mechanism makes failure-suppression structurally impossible.

**Status**: Custodian agreement in active negotiation with [University TBD]. Will be made public when signed.

---

## 11. How to Help

If you want to contribute to validation:

### For Researchers
- **Critique our methodology**: Review the verification utilities and report issues via GitHub Issues
- **Reproduce experiments**: When Phase 1 results are published, run them independently on your own hardware
- **Submit alternative baselines**: Add Mamba, Linear Attention, MoE, or your favorite architecture to the ablation suite

### For Engineers
- **Provide compute**: If your organization has spare GPU capacity, contact us about co-validation
- **Optimize implementations**: PRs that speed up the verification suite are very welcome
- **Test on novel hardware**: Edge devices, neuromorphic chips, etc.

### For Institutions
- **University partnership**: We are actively seeking academic partners for independent result custody (see §10)
- **Industry consortium**: Companies interested in CID-based architectures for production are invited to join an early-access program

**Contact**: 
- Academic: guilichina@163.com
- Commercial: lig@jodell.cn
- General: open a GitHub issue

---

## 12. Versioning of This Roadmap

This roadmap is itself version-controlled. Any change to falsification criteria, timelines, or thresholds will be made via Git commits with clear justification. The full history is auditable.

| Version | Date | Changes |
|---|---|---|
| v1.0 | 2026-05-25 | Initial roadmap |
| v1.1 | 2026-05-30 | Added: MVP pipeline-proof task, compute resources section (§9), independent disclosure mechanism (§10), Phase 6-7 for QID/FID; tightened pre-registered statistical requirements; clarified conditional execution between phases |

---

## 13. Final Commitment

We commit, in writing and in public, to:

1. **Publish all Phase 1-5 results, positive or negative, within 90 days of experiment completion**
2. **Not modify pre-registered falsification criteria after experiments begin** (any modification will be a separate, public ROADMAP version, justified)
3. **Submit Phase 5 results to peer-reviewed journals** regardless of outcome
4. **Accept independent reproduction with grace**, including reproductions that contradict our results
5. **Acknowledge falsification clearly** if our hypotheses don't survive, without spin or excuses

Science advances by honest hypothesis-testing. We chose this path. We will follow it through.

---

**Document maintained by**: Suzhou Jodell Robotics Co., Ltd. (project lead) + [University Custodian, TBD]  
**Next scheduled update**: Upon completion of Phase 0 MVP (target 2026-06-15)  
**Public discussion**: GitHub Issues  
**Contact**: guilichina@163.com
