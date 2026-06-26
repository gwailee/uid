<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-30
UPDATE: 2026-06-22 (v2.2 — Phase 1 four-experiment complete + independent reproduction)

This README is part of the UID Theory reference implementation (v2.2).

DUAL LICENSE:
  - PolyForm Noncommercial License 1.0.0  (free for academic / personal use)
  - Commercial License from Suzhou Jodell Robotics Co., Ltd.
For commercial licensing inquiries, contact: lig@jodell.cn
-->

<div align="center">

![logo](./images/logo.png)

</div>

<div align="center">
<a href="./README.md">README（中文）</a> | <a href="./README_en.md"><b>README（English）</b></a>
</div>

<div align="center">
<a href="./30minutes_report.md">30 分钟读懂 UID 理论（中文）</a> | <a href="./30minutes_report_en.md">Understand UID in 30 Minutes（English）</a>
</div>

<div align="center">
<a href="./theory.md">UID 理论全文（中文）</a> | <a href="./theory_en.md">UID Theory (English)</a>
</div>

<br>

<div align="center">

# Intelligence Is a Non-Equilibrium Field: A Three-Tier Physical Theory of Unified Intelligo-Dynamics (UID)
## — Attention Is Not All You Need: The Non-Equilibrium Physical Foundations of Intelligent Architectures

[CI](https://github.com/gwailee/uid/actions/workflows/ci.yml) | [DOI](https://doi.org/10.5281/zenodo.20372493) | [License: PolyForm Noncommercial](LICENSE)


***Authors***: Gui LI <guilichina@163.com>, Dangyang JIE <jiedy@jodell.cn>, Haitao KANG <kanght@jodell.cn>

***Affiliation***: Suzhou Jodell Robotics Co., Ltd., Suzhou, China

</div>

***Corresponding author***: Gui LI, Ph.D. B.Sc. from the School of Physics, Northwest University; M.Sc. and Ph.D. from the Hefei Institutes of Physical Science, Chinese Academy of Sciences; currently at Suzhou Jodell Robotics Co., Ltd., working on the theory and engineering of **Unified Intelligo-Dynamics (UID)** — an open-system physical framework for intelligent architectures (the three-tier CID/QID/FID system) and its falsifiable verification across robotic cognitive brains, motor-control cerebella, dexterous-hand operating systems, large language models, and dedicated intelligence chips. E-mail: guilichina@163.com

---

## ⚠️ Important Notice: v2.2 Honest-Version Statement

**This repository is currently at v2.2 (Honest-Verification Edition · Phase 1 four-experiment-complete edition).** On top of v2.1, it **completes the full Phase 1 empirical suite (ablation + scaling-law family training + critical exponents + decode energy), fixes several flaws in the energy and critical-exponent measurement toolchains, and archives an independent third-party reproduction**:

| Key v2.2 progress | Theory section / fix |
|---|---|
| 10M scaling-law families trained (3 families × 3 seeds, well-converged tpp=200) | T1 / T2 |
| Energy switched to a **robust GLOBAL idle baseline** (fixing a prior artifact: CID 124 W vs Transformer 211 W idle made above-idle non-comparable) | §0.1 / §11.4 |
| Energy comparison now in **three views: iso-parameter (neutral) + iso-performance (the C13 verdict)**, with no extrapolation | §13 |
| Critical-exponent toolchain: fixed three bugs — degenerate noise-OFF/ON → shuffle surrogate; ill-conditioned per-sequence η → global covariance; erroneous Hurst correction → standard DFA-2 (validated by surrogate H = 0.519) | §6.1 |
| Archived an independent third-party reproduction (Xingyu Zhao), bit-for-bit match | §16.9 |

The v2.2 edition:
- ✅ Provides the **complete infrastructure** for rigorous verification (full test coverage)
- ✅ Delivers all promised fixes: §8.5 ET correction, §14.2 zero-parameter vortex, §14.2 OU noise, §6.1 measurable η
- ✅ **All four Phase 1 experiments completed** (ablation, scaling-law families, critical exponents, energy; see "First Empirical Results" below)
  - ✅ **T1 (core thesis) strongly supported**: after full training, CID perplexity **7.90** vs Transformer **31.12** = **3.94×**, with FEWER parameters (4.83M vs 5.12M) and near-zero cross-seed variance (std ≈ 0.01)
  - ✅ **"Attention is not all you need" replicated three times**: stacking known tricks is useless (ablation < 1%; in scaling-law `transformer_plus_tricks` 31.23 ≈ `transformer` 31.12 yet costs 2.3× the compute)
  - ✅ **§14.2 OU noise supported**: OU beats FFT by **6.9×** (z = 37)
  - ✅ **F4 Hurst supported**: H = 0.803, inside [0.6, 0.8], far above the shuffle surrogate (0.519), demonstrating genuine long-range correlation
  - ❌ **F3 β falsified**: β = 0.572, just below [0.7, 1.3]
  - ❌ **F5 avalanche falsified**: tail not power-law (KS p = 0, α ≈ 3.0; with a measurement-validity caveat)
  - ⚠️ **F6 η non-discriminating**: η = 0.997 > 0.5 but essentially identical to the Transformer baseline (0.998); the metric saturates
  - ❌ **F8 ET term falsified**: no benefit, marginally harmful (−3.2%); **note: the theory states ET is NOT original to UID and credits Hoover et al. 2023**
  - ⏳ **Multi-scale scaling law (F1/F2) and iso-PPL energy (F7) not yet done** — the **only decisive tests** of T2 (5–10× parameter efficiency) and C13 (≥3× energy), deferred to Phase 1b
- ✅ **Independent third-party reproduction archived** (bit-for-bit on the key numbers, negative findings reproduced too)
- 🎯 Commits to **publishing all results** (positive or negative)

**Falsifying a theory is as valuable as confirming it** — the fundamental principle of scientific progress.

---

## 🧪 First Empirical Results (Phase 1 Complete · 2026-06-22)

> **Status**: SUBSTANTIALLY COMPLETE (ablation + scaling-law families + critical exponents + decode energy done; multi-scale scaling law F1/F2 and iso-PPL energy F7 deferred to Phase 1b)
> **Dataset**: MiniMind Chinese pretraining corpus, 100k subset (~10M tokens)
> **Scale**: 10M params · **Seeds**: [42, 43, 44] · **Hardware**: NVIDIA RTX 4090 (24GB)
> **Reproduction commands**: see Quick Start §Step 5. Full report: [`results/phase1/REPORT.md`](./results/phase1/REPORT.md).

### Finding 1: With full training, CID's framework advantage GROWS (T1 strongly supported)

| Family | Non-emb params | Perplexity (mean of 3 seeds) | vs CID |
|---|---|---|---|
| `transformer` | 5,115,136 | **31.12** | 3.94× worse |
| `transformer_plus_tricks` | 5,213,470 | **31.23** | 3.95× worse |
| **`cid_full`** | **4,831,268** | **7.90** (std ≈ 0.01) | — |

CID reaches perplexity 7.90 with **fewer parameters**, **3.94×** below Transformer (31.12); the advantage grew from the 3.22× seen in 1-epoch ablation, with near-zero seed variance. Known tricks (conv/linear/noise) are useless, and `transformer_plus_tricks` costs 2.3× the compute yet is worse — a third independent replication of "attention is not all you need."

### Finding 2: Ablation — UID's original physical terms supported, the borrowed ET term falsified

> Ablation is single-epoch (1 epoch); the ratio is a single-scale iso-parameter perplexity ratio, a **different training budget** from the 3.94× above.

| Contrast | Meaning (theory §) | `cid_full` | Control | PPL ratio | z(eval_loss) | Verdict |
|---|---|---|---|---|---|---|
| **A** | CID physical framework vs known tricks (T1) | 23.62 | `transformer_plus_all_tricks` = 73.33 | **3.10×** | 182.19 | ✅ supported |
| **C** | §14.2 OU vs FFT noise | 23.62 | `cid_full_fft_noise` = 169.93 | **6.87×** | 37.14 | ✅ supported |
| **B** | §8.5 ET symmetric term (F8) | 23.62 | `cid_full_no_et` = 22.87 | 0.97× | −6.39 | ❌ **not_supported** |

The **colored-damping memory kernel is the single largest physical contributor** (removing it raises perplexity by 21%). The ET falsification concerns only the borrowed, non-original component; removing it makes CID *better*, "purifying" the attribution. (Note: Contrast A is 3.22× as a loss ratio and 3.10× as a perplexity ratio; the repository's headline number is the well-trained scaling-law **3.94×**.)

### Finding 3: Critical exponents — partial support, and NO discrimination from baseline (consistent with the theory's own caveat)

> Tooling validated after fixes: shuffle-surrogate Hurst = 0.519 ≈ 0.5; spectral-fit R² = 0.94.

| Exponent (F#) | Predicted | `cid_full` | Transformer baseline | Verdict |
|---|---|---|---|---|
| **Hurst (F4)** | [0.6, 0.8] | **0.803** (surrogate 0.519) | 0.813 | ✅ **PASS** |
| **β 1/f (F3)** | [0.7, 1.3] | **0.572** (R²=0.94) | 0.709 | ❌ FAIL |
| **Avalanche τ (F5)** | ~1.5 | not power-law (α≈3.0, p=0) | not power-law | ❌ FAIL |
| **η anisotropy (F6)** | > 0.5 | 0.997 | 0.998 | ⚠️ no discrimination |

**Key honesty point**: none of the four exponents distinguish CID from a plain Transformer — exactly as the abstract pre-states ("these universal exponents have limited falsifying power and cannot separate CID from other critical models"). They are descriptive corroboration that "CID shows brain-like critical statistics," **not** independent evidence that CID is superior to Transformer.

### Finding 4: Energy — clean after the idle fix; the iso-PPL verdict awaits multi-scale

> Robust shared idle baseline = 61.9 W (inter-window spread 0.06 W), fixing a prior 87 W CID/Transformer idle artifact.

| Family | Perplexity | above-idle energy (mJ/token) | vs baseline |
|---|---|---|---|
| `transformer` | 31.12 | **0.141** | 1.00× |
| **`cid_full`** | **7.90** | 0.160 | 1.13× (overhead) |
| `transformer_plus_tricks` | 31.23 | 0.164 | 1.17× |

At iso-parameter, CID's per-token energy is only ~**13%** higher (and *lower* than tricks, with the fewest params and the lowest peak power), yet it buys a **3.9×** perplexity advantage — i.e. "3.9× quality for 13% more energy." **Note: this is the iso-parameter overhead, NOT the C13 ≥3× energy verdict (F7)**, which must be measured on a multi-scale iso-PPL curve where the Transformer reaches CID's perplexity; untestable at a single scale and deferred to Phase 1b.

### Phase 1 falsification scorecard

| Verdict | Conditions |
|---|---|
| ✅ PASS (1) | F4 (Hurst) |
| ❌ FAIL (3) | F3 (β), F5 (avalanche), F8 (borrowed ET) |
| ⚠️ INCONCLUSIVE (1) | F6 (η, no discrimination) |
| ⏳ ABSTAIN (3) | F1/F2 (multi-scale not run), F7 (iso-PPL untestable at single scale) |

> All negative results are presented with **equal prominence** to positive ones and permanently retained. Cite these results with the v2.2 commit hash and the per-claim caveats in [`results/phase1/REPORT.md`](./results/phase1/REPORT.md) §6.

### ✅ Independent Third-Party Reproduction

The repository's Phase 1 core results have been independently reproduced by **Xingyu Zhao (Neutron Technology Application Research Center, Institute of Energy, Hefei Comprehensive National Science Center)** in a fresh environment, on commit `53f2aa06` (10M scale, 3 seeds, RTX 4090), built from scratch following the official `requirements.txt` and documentation.

| Experiment | Reproduced | Repo published | Match |
|---|---|---|---|
| Ablation Contrast A (z) | **3.11×, z=182.2** | 3.10×, z=182 | ✅ bit-for-bit |
| Scaling law tpp=200 (3 seeds) | **3.94× ± 0.03** (cid 7.89 / tf 31.12) | 3.94× | ✅ bit-for-bit |
| Iso-parameter energy (decode) | **1.20×** (CID +20%) | 1.13× (prefill, same direction) | ✅ same direction |
| Iso-PPL energy (C13) | **undecidable at this scale** | deferred | ✅ same conclusion |
| Critical-exponent emergence | **emergence_not_confirmed** | same (no baseline discrimination) | ✅ same conclusion |

The reproduction confirms not only the positive results bit-for-bit but **equally reproduces the negative and neutral findings** (critical exponents cannot distinguish CID from Transformer; iso-parameter energy is ~20% higher for CID; raw inference throughput is ~27% higher for Transformer; the iso-PPL energy verdict is undecidable at this scale), and independently flagged several engineering issues (dependency-version pins, a sampling cap for the critical-exponent statistics, inconsistent training-budget defaults across entry points), which the repository has since fixed.

The full reproduction report (zh/en), aggregated JSON, and provenance are in [`results/phase1/independent-reports/`](./results/phase1/independent-reports/) (model weights `.pt`, ~880MB intermediate products, not included but available on request; every number is recomputable from the JSON files and the report's commands).

> **Acknowledgment**: We thank Xingyu Zhao for the independent reproduction of our Phase 1 experiments and the engineering feedback. The report and all aggregated data are archived as-is, including the negative findings consistent with this repository.
> **Note**: the reproduction used commit `53f2aa06`, whose critical-exponent tool is the pre-DFA-fix version, so the reproduced Hurst (0.766) differs slightly from the repository's fixed value (0.803), though in the same direction (both inside [0.6,0.8] and both non-discriminating vs the baseline).

---

## 📦 What Is This

**UID (Unified Intelligo-Dynamics)** treats intelligent architectures as **stochastic fields far from thermal equilibrium**. From three axioms of open-system physics, via Mori-Zwanzig projection, it derives the **generalized Langevin equation** as the general evolution structure of intelligent systems, and argues that mainstream architectures (Transformer, Mamba, diffusion models, …) are its special cases in particular limits.

This repository provides a **reference engineering implementation of the CID (Classical Intelligo-Dynamics) tier** plus a **falsifiable verification suite**: adding UID's three physical terms — **vortex v(φ), colored-damping memory kernel ∫γ, OU colored noise ξ** — onto a standard attention backbone, with four experiment classes (ablation, scaling law, critical exponents, energy).

- 📄 Full theory: [`theory.md`](./theory.md) (zh) / [`theory_en.md`](./theory_en.md) (en)
- ⏱️ 30-minute read: [`30minutes_report.md`](./30minutes_report.md) (zh) / [`30minutes_report_en.md`](./30minutes_report_en.md) (en)
- 🧪 Full experiment report: [`results/phase1/REPORT.md`](./results/phase1/REPORT.md)

---

## 🚀 Quick Start

### Step 1: Clone & install

```bash
git clone https://github.com/gwailee/uid.git
cd uid
pip install -e .
pip install modelscope transformers torch tqdm protobuf
```

> Dependency note: following third-party reproduction feedback, the `typeguard` version constraint in `requirements.txt` has been fixed; pin `transformers<5.0` (4.5x verified).

### Step 2: Download the MiniMind dataset

```bash
modelscope download --dataset gongjy/minimind_dataset --local_dir dataset
```

### Step 3: Convert the data format

```bash
python convert_minimind_data.py
```

### Step 4: Download the BERT-Chinese tokenizer

```bash
python -c "from transformers import AutoTokenizer; \
AutoTokenizer.from_pretrained('bert-base-chinese').save_pretrained('tokenizers/bert-base-chinese')"
```

### Step 5: Reproduce Phase 1

```bash
head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# (a) Ablation (11 variants × 3 seeds, single epoch)
python experiments/run_all.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_100k \
    --skip_scaling --skip_critical --skip_energy

# (b) Scaling-law family training (3 families × 3 seeds, well-trained tpp=200)
python experiments/run_scaling_law.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scales 10M --families transformer transformer_plus_tricks cid_full \
    --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --target_tokens_per_param 200 \
    --output_dir ./output/minimind_100k/scaling_law_v2.1

# (c) Critical exponents (fixed toolchain; n_sequences=2000 to avoid OOM)
python experiments/run_critical_exponents.py \
    --checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/cid_full_10M_seed42.pt \
    --baseline_checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/transformer_10M_seed42.pt \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --max_seq_len 512 --batch_size 4 --n_sequences 2000 --eta_max_samples 50000 \
    --output_dir output/minimind_100k/critical_exponents_v2.2.1

# (d) Decode energy (seq_len + new_tokens <= max_seq_len)
python experiments/run_energy_benchmark.py \
    --families transformer cid_full transformer_plus_tricks \
    --checkpoint_dir output/minimind_100k/scaling_law_v2.1/checkpoints \
    --scale 10M --seeds 42 43 44 --batch_size 8 --seq_len 256 \
    --vocab_size 21128 --mode decode --new_tokens_per_decode 64 \
    --scaling_law_json output/minimind_100k/scaling_law_v2.1/results.json \
    --output_dir output/minimind_100k/energy_v2.2
```

> **On training budgets (important)**: ablation defaults to `epochs=1`; `run_scaling_law.py` itself defaults to `tokens_per_param=20` (Chinchilla-optimal); the `run_all.py` end-to-end pipeline defaults to `tokens_per_param=200` (full convergence on the small corpus). Different entry points use different budgets and yield different advantage ratios (ablation 3.1–3.22× vs well-trained 3.94×); always state the budget when citing.

---

## 🔬 Falsifiable Predictions & Decision Points

| # | Prediction | Evidence grade | Phase 1 status |
|---|---|---|---|
| **T1** | CID physical terms beat plain Transformer | C (falsifiable engineering target) | ✅ Supported (ablation 3.22× / scaling 3.94×) |
| **T2** | 5–10× parameter efficiency (multi-scale iso-FLOP) | C | ⏳ Pending Phase 1b (**a decisive test**) |
| **C3.3** | Vortex necessity (prediction implies non-equilibrium) | B | Partial (critical exponents cannot discriminate baseline) |
| **§14.2** | OU colored noise > FFT spectral shaping | C | ✅ Supported (6.9×, z=37) |
| **Critical universality** | τ≈1.5 / H≈0.7 / β≈1 | B | Hurst PASS, β/avalanche FAIL, no baseline discrimination |
| **C13** | ≥3× energy efficiency at iso-PPL | C | ⏳ Pending Phase 1b (undecidable at single scale) |

> The genuinely discriminating decision points are **T2 (parameter efficiency)** and **C13 (energy)**; the critical universal exponents have limited discriminating power (empirically confirmed: they cannot distinguish CID from Transformer) and serve only as descriptive corroboration.

---

## 📚 Citation

```bibtex
@article{li2026uid,
  title  = {Intelligence Is a Non-Equilibrium Field: A Three-Tier Physical
            Theory of Unified Intelligo-Dynamics (UID)},
  author = {LI, Gui and JIE, Dangyang and KANG, Haitao},
  year   = {2026},
  publisher = {Zenodo},
  doi    = {10.5281/zenodo.20372493},
  url    = {https://github.com/gwailee/uid}
}
```

> When citing Phase 1 results, attach the v2.2 commit hash and the per-claim caveats in [`results/phase1/REPORT.md`](./results/phase1/REPORT.md) §6.

---

## 🙏 Acknowledgments

We thank Xingyu Zhao (Neutron Technology Application Research Center, Institute of Energy, Hefei Comprehensive National Science Center) for the independent reproduction of our Phase 1 experiments and the engineering feedback.

---

## 📄 License

Dual-licensed:

- **PolyForm Noncommercial License 1.0.0**: free for academic / personal non-commercial use, see [`LICENSE-NONCOMMERCIAL`](./LICENSE-NONCOMMERCIAL).
- **Commercial License**: any commercial / for-profit / production use requires prior written authorization from Suzhou Jodell Robotics Co., Ltd., see [`LICENSE-COMMERCIAL`](./LICENSE-COMMERCIAL).

Commercial licensing inquiries: lig@jodell.cn