<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-30
UPDATE: 2026-06-24 (v2.3 — multi-scale ablation + ET non-causal structural result + independent reproduction)

This README is part of the UID Theory reference implementation (v2.3).

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

***Corresponding author***: Gui LI, Ph.D. B.Sc. from the School of Physics, Northwest University; M.Sc. and Ph.D. from the Hefei Institutes of Physical Science, CAS; currently at Suzhou Jodell Robotics Co., Ltd., working on the theory and engineering of Unified Intelligo-Dynamics (UID). E-mail: guilichina@163.com

---

## ⚠️ Important Notice: v2.3 Honest-Version Statement

**This repository is at v2.3 (Honest-Verification Edition · multi-scale ablation complete).** On top of v2.2 it adds a **10M/30M/100M multi-scale ablation**, resolves a **fundamental conflict between the ET term and causality**, and archives an **independent third-party reproduction**:

| Key v2.3 progress | Theory section / fix |
|---|---|
| **10M/30M/100M multi-scale ablation** (3 seeds); ratio grows with scale 3.12→3.71→4.09× | T1 / T2 (directional) |
| **ET symmetric term shown intrinsically NON-CAUSAL**: its second term needs keys to depend on future queries (~0.11 leakage measured); incompatible with autoregressive causality; in causal LMs it is **dropped, ET reduces to standard attention** | §8.5 |
| Critical-exponent toolchain: fixed three bugs (noise-OFF/ON degeneracy → shuffle surrogate; ill-conditioned η → global covariance; erroneous Hurst correction → standard DFA-2, surrogate H=0.519) | §6.1 |
| Energy: robust global idle baseline + iso-parameter/iso-performance three views | §0.1 / §13 |
| Independent third-party reproduction archived (Xingyu Zhao) | §16.9 |

The v2.3 edition:
- ✅ **T1 (core thesis) strongly supported, and the advantage GROWS with scale**: cid_full/transformer perplexity ratio **3.12× (10M) → 3.71× (30M) → 4.09× (100M)**; **cid_full at 10M (~4.8M params) already beats transformer at 100M (~49M params)** — winning at roughly **1/10 the parameters**, a strong directional signal toward 5–10× parameter efficiency
- ✅ **"Attention is not all you need" replicated at all three scales**: known tricks give < 1% at every scale
- ✅ **§14.2 OU noise supported** (magnitude scale-dependent: ~7× at 10M, ~1.24× at 100M)
- ✅ **Memory kernel is the dominant physical term** (+15–22% on removal at every scale)
- ✅ **F4 Hurst supported**: H=0.803 ∈ [0.6,0.8], surrogate 0.519 validates genuine long-range correlation
- ❌ **F3 β falsified** (0.572), **F5 avalanche falsified** (not power-law)
- ⚠️ **F6 η non-discriminating** (0.997 ≈ baseline 0.998; metric saturates)
- 🔧 **F8 ET term**: v2.3 proves the ET symmetric term is **non-causal and cannot be realized in a causal LM**; it is dropped and `cid_full ≡ cid_full_no_et`. This **supersedes** the v2.2 "F8 falsified" reading — the correct statement is that **CID's advantage comes entirely from its three causal-safe physical terms, and ET is inapplicable here**
- ⏳ **Equal-compute multi-scale scaling-law (F1/F2) and iso-PPL energy (F7)** deferred to Phase 1b (H100) — the decisive tests of T2 and C13
- 🎯 Commits to **publishing all results** (positive or negative)

**Falsifying a theory is as valuable as confirming it** — the fundamental principle of scientific progress.

---

## 🧪 First Empirical Results (Phase 1 · v2.3 · 2026-06-24)

> **Status**: SUBSTANTIALLY COMPLETE (multi-scale ablation + critical exponents + decode energy done; equal-compute scaling-law F1/F2 and iso-PPL energy F7 deferred to Phase 1b)
> **Dataset**: MiniMind Chinese pretraining corpus, 100k subset (~10M tokens) · **Seeds**: [42,43,44] · **Hardware**: RTX 4090 (Phase 1b on H100)
> Full report: [`results/phase1/REPORT.md`](./results/phase1/REPORT.md).

### Headline: the framework advantage GROWS with scale; CID wins at ~1/10 the parameters (T1 strongly supported)

Multi-scale ablation (memory_length=64, 1 epoch, 3 seeds):

| Scale | cid_full non-emb params | cid_full PPL | transformer PPL | **PPL ratio** |
|---|---|---|---|---|
| 10M | ~4.8M | **23.62** | 73.58 | **3.12×** |
| 30M | ~22.7M | **12.49** | 46.36 | **3.71×** |
| 100M | ~49.3M | **10.21** | 41.76 | **4.09×** |

**Two key points**:
1. **The ratio grows monotonically with scale** (3.12→3.71→4.09×) — an advantage that grows with size, the opposite of the "baseline catches up" failure mode.
2. **cid_full at 10M (~4.8M params, PPL 23.62) is far better than transformer at 100M (~49M params, PPL 41.76)** — CID wins at roughly **1/10 the parameters**, a strong directional signal toward 5–10× parameter efficiency (T2).

> ⚠️ Honest note: the table uses the **ablation budget (1 epoch)** and is a **directional lower bound** on T2, **not** the strict verdict; strict T2 needs equal-compute multi-scale curves (Phase 1b). For reference, the fully-trained single point (tpp=200) at 10M was cid_full 7.90 vs transformer 31.12 (3.94×).

### "Attention is not all you need": replicated at all three scales

Known Transformer tricks (conv/linear/noise) give < 1% at each of 10M/30M/100M; `transformer_plus_tricks` is not better than plain transformer yet costs ~2.3× the compute. CID's advantage cannot be attributed to "more tricks."

### Ablation attribution: memory kernel dominates; ET inapplicable to causal LMs

| Physical term | Δ PPL on removal (per scale) | Conclusion |
|---|---|---|
| Colored-damping memory kernel ∫γ | +21.7% (10M) / +14.7% (30M) / +14.8% (100M) | **Largest single contributor** |
| Vortex v(φ) | +0.2–0.4% | Small ablation effect; necessity tested via critical exponents (Prop. C3.3) |
| Colored noise (presence) | ~0% | Type (OU vs FFT) matters, not presence |
| OU → FFT noise | ~7× worse (10M) / ~1.24× (100M) | OU supports §14.2 (magnitude scale-dependent) |
| ET symmetric term (§8.5) | `cid_full ≡ cid_full_no_et` | **Non-causal, not realizable in causal LM, dropped** (below) |

**On ET (formerly F8), v2.3 conclusion**: ET's symmetric second term requires key positions to depend on future query positions, causing ~0.11 future-token leakage in a causal LM — **ET's dual-softmax symmetry and autoregressive causality are mathematically incompatible**. v2.3 drops the term; `use_et_symmetric=True` reduces to standard causal attention and `cid_full ≡ cid_full_no_et`. This **supersedes** the v2.2 "F8 falsified": not "ET is useless" but **"ET is inapplicable to causal LMs; CID's advantage comes entirely from its three causal-safe physical terms (vortex/memory/noise)."**

### Critical exponents (10M): partial support, no discrimination

> Tooling validated: shuffle-surrogate Hurst = 0.519 ≈ 0.5; spectral-fit R² = 0.94.

| Exponent (F#) | Predicted | `cid_full` | Transformer baseline | Verdict |
|---|---|---|---|---|
| Hurst (F4) | [0.6, 0.8] | **0.803** (surrogate 0.519) | 0.813 | ✅ PASS |
| β 1/f (F3) | [0.7, 1.3] | 0.572 (R²=0.94) | 0.709 | ❌ FAIL |
| Avalanche τ (F5) | ~1.5 | not power-law (p=0) | not power-law | ❌ FAIL |
| η (F6) | > 0.5 | 0.997 | 0.998 | ⚠️ no discrimination |

**Key honesty point**: none of the four exponents distinguish CID from a plain Transformer — as the abstract pre-states. They are descriptive corroboration only, **not** independent evidence that CID is superior.

### Energy (10M): clean after the idle fix; iso-PPL verdict deferred

> Robust shared idle baseline = 61.9 W (spread 0.06 W).

| Family | Perplexity | above-idle energy (mJ/token) | vs baseline |
|---|---|---|---|
| transformer | 31.12 | **0.141** | 1.00× |
| cid_full | 7.90 | 0.160 | 1.13× (overhead) |
| transformer_plus_tricks | 31.23 | 0.164 | 1.17× |

At iso-parameter, CID uses only ~13% more per-token energy (and less than tricks, fewest params), for ~3.9× lower perplexity. **This is the iso-parameter overhead, NOT the C13 ≥3× verdict (F7)**, which needs a multi-scale iso-PPL curve (Phase 1b).

### Phase 1 falsification scorecard

| Verdict | Conditions |
|---|---|
| ✅ PASS (1) | F4 (Hurst) |
| ❌ FAIL (2) | F3 (β), F5 (avalanche) |
| ⚠️ INCONCLUSIVE (1) | F6 (η) |
| 🔧 RESOLVED_not_realizable (1) | F8 (ET non-causal, not realizable) |
| ⏳ ABSTAIN (3) | F1/F2 (equal-compute curve), F7 (iso-PPL) |

> All negative results are presented with equal prominence and permanently retained. Cite with the v2.3 commit hash and the per-claim caveats in [`REPORT.md`](./results/phase1/REPORT.md) §6.

### ✅ Independent Third-Party Reproduction

The repository's Phase 1 core results have been independently reproduced by **Xingyu Zhao (Neutron Technology Application Research Center, Institute of Energy, Hefei Comprehensive National Science Center)** on commit `53f2aa06` (RTX 4090, 3 seeds). Key numbers match bit-for-bit: ablation Contrast A **3.11× / z=182.2**; fully-trained scaling law **cid 7.89 / tf 31.12 (3.94× ± 0.03)**. The reproduction equally confirms the negative/neutral findings (critical exponents cannot distinguish CID from Transformer; iso-parameter energy ~20% higher for CID; transformer throughput ~27% higher; iso-PPL energy undecidable), and independently flagged several engineering issues (since fixed). Full report: [`results/phase1/independent-reports/`](./results/phase1/independent-reports/) (excludes ~880MB weights; available on request).

> **Acknowledgment**: We thank Xingyu Zhao for the independent reproduction and engineering feedback.
> **Note**: the reproduction used commit `53f2aa06` (before the v2.3 ET fix); its critical-exponent tool is the pre-fix version, so the reproduced Hurst (0.77) differs slightly from our corrected value (0.803), in the same direction.

---

## 📦 What Is This

**UID** treats intelligent architectures as **stochastic fields far from thermal equilibrium**; from three open-system axioms, via Mori-Zwanzig projection, it derives the **generalized Langevin equation** and argues mainstream architectures are its special-case limits. This repository provides a **reference CID implementation** and a **falsifiable verification suite**: adding three **causal-safe** physical terms — **vortex v(φ), colored-damping memory kernel ∫γ, OU colored noise ξ** — onto a standard attention backbone.

- 📄 Full theory: [`theory.md`](./theory.md) / [`theory_en.md`](./theory_en.md)
- 🧪 Full experiment report: [`results/phase1/REPORT.md`](./results/phase1/REPORT.md)

---

## 🚀 Quick Start

```bash
git clone https://github.com/gwailee/uid.git && cd uid
pip install -e .
pip install modelscope transformers torch tqdm protobuf
# Dependency note: the typeguard pin in requirements.txt is fixed; pin transformers<5.0

modelscope download --dataset gongjy/minimind_dataset --local_dir dataset
python convert_minimind_data.py
python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('bert-base-chinese').save_pretrained('tokenizers/bert-base-chinese')"

head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# (a) Multi-scale ablation (10M/30M/100M)
for S in 10M 30M 100M; do
  python experiments/run_all.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale $S --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_100k \
    --skip_scaling --skip_critical --skip_energy
done

# (b) Scaling-law family training (3 families × 3 seeds, tpp=200)
python experiments/run_scaling_law.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scales 10M --families transformer transformer_plus_tricks cid_full \
    --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --target_tokens_per_param 200 \
    --output_dir ./output/minimind_100k/scaling_law_v2.1

# (c) Critical exponents (fixed toolchain)
python experiments/run_critical_exponents.py \
    --checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/cid_full_10M_seed42.pt \
    --baseline_checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/transformer_10M_seed42.pt \
    --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
    --max_seq_len 512 --batch_size 4 --n_sequences 2000 --eta_max_samples 50000 \
    --output_dir output/minimind_100k/critical_exponents_v2.2.1

# (d) Decode energy
python experiments/run_energy_benchmark.py \
    --families transformer cid_full transformer_plus_tricks \
    --checkpoint_dir output/minimind_100k/scaling_law_v2.1/checkpoints \
    --scale 10M --seeds 42 43 44 --batch_size 8 --seq_len 256 \
    --vocab_size 21128 --mode decode --new_tokens_per_decode 64 \
    --scaling_law_json output/minimind_100k/scaling_law_v2.1/results.json \
    --output_dir output/minimind_100k/energy_v2.2

# Phase 1b (H100, decisive F1/F2/F7): equal-compute multi-scale scaling law + iso-PPL energy
#   --scaling_scales 10M 30M 100M --target_tokens_per_param 200 --force_stage scaling energy
```

> **On training budgets**: ablation defaults to `epochs=1`; `run_scaling_law.py` defaults to `tokens_per_param=20`; `run_all.py` defaults to `tokens_per_param=200`. Different entry points → different budgets → different ratios (ablation 3.12× vs fully-trained 3.94×); always state the budget when citing.

---

## 🔬 Falsifiable Predictions & Decision Points

| # | Prediction | Grade | Phase 1 status |
|---|---|---|---|
| **T1** | CID physical terms > Transformer | C | ✅ Supported, grows with scale (3.12→4.09×, wins at ~1/10 params) |
| **T2** | 5–10× parameter efficiency (equal-compute) | C | ⏳ Strong directional support; verdict pending Phase 1b (F1/F2) |
| **C3.3** | Vortex necessity | B | Partial (exponents cannot discriminate baseline) |
| **§14.2** | OU > FFT | C | ✅ Supported at all scales (magnitude scale-dependent) |
| **Critical universality** | τ≈1.5 / H≈0.7 / β≈1 | B | Hurst PASS; β/avalanche FAIL; no baseline discrimination |
| **C13** | ≥3× energy at iso-PPL | C | ⏳ Pending Phase 1b (undecidable at single scale) |
| **ET §8.5** | ET symmetric term | borrowed (Hoover 2023) | 🔧 Non-causal, not realizable in causal LM, dropped |

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

> When citing Phase 1 results, attach the v2.3 commit hash and the per-claim caveats in [`REPORT.md`](./results/phase1/REPORT.md) §6.

---

## 🙏 Acknowledgments

We thank Xingyu Zhao (Neutron Technology Application Research Center, Institute of Energy, Hefei Comprehensive National Science Center) for the independent reproduction and engineering feedback.

---

## 📄 License

Dual-licensed: **PolyForm Noncommercial 1.0.0** (academic/personal, [`LICENSE-NONCOMMERCIAL`](./LICENSE-NONCOMMERCIAL)) + **Commercial License** (production use requires written authorization from Suzhou Jodell Robotics Co., Ltd., [`LICENSE-COMMERCIAL`](./LICENSE-COMMERCIAL)). Inquiries: lig@jodell.cn