# Independent Reproduction Report: CID vs Transformer Parameter Efficiency (10M / 100k)

> This is an **independent third-party reproduction** of the CID/Transformer comparison experiments in the UID (Unified Intelligo-Dynamics) repository. The goal is to re-measure the core metrics in a clean environment and cross-check them against the repository's published numbers. Every figure below is measured in this run; no conclusion is cited without being re-computed here.

| Item | Value |
|---|---|
| Author | Zhao Xingyu (赵星宇) |
| Affiliation | Neutron Technology Application Research Center, Institute of Energy, Hefei Comprehensive National Science Center |
| Target | `gwailee/uid`, commit `53f2aa06` |
| Model scale / data | 10M parameter family / first 100,000 entries of MiniMind pretrain |
| Hardware | NVIDIA RTX 4090 (24GB) |
| Seeds | 42 / 43 / 44 |

---

## 0. Results at a Glance

| Experiment | Metric | This run (measured) | Repo published | Match |
|---|---|---|---|---|
| Ablation (1 epoch) | cid_full vs transformer eval_ppl | **3.12×** (cid 23.62 / tf 73.58) | ~3.1× | ✅ |
| Ablation critical comparison A | cid_full vs transformer+tricks, z(eval_loss) | **3.11×, z=182.2** | 3.1×, z=182 | ✅ digit-for-digit |
| Scaling law (full training, tpp=200) | cid_full vs transformer eval_ppl, 3 seeds | **3.94× ± 0.03** (cid 7.89 / tf 31.12) | 3.94× | ✅ digit-for-digit |
| Inference throughput | cid_full vs transformer | Transformer ~**27% faster** | — (not stated by repo) | new observation |
| Energy (iso-parameter) | cid_full / transformer, per token | **1.20×** (CID 20% higher) | prefill ~1.13× | ✅ same direction |
| Energy (iso-performance, iso-PPL / C13) | ≥3× threshold verdict | **not decidable at this scale** | listed as TODO | ✅ same conclusion |
| Critical exponents | emergence verdict | **emergence_not_confirmed** | marked "to be verified" | ✅ same conclusion |

**One-line takeaway**: CID's perplexity advantage over a same-parameter-count Transformer is **a function of training budget** — about **3.1×** under a single-epoch ablation, growing to **3.94× (≈4×)** under full training (tokens_per_param=200), with very low variance across 3 seeds. This advantage is at the **parameter-efficiency** level; on raw inference throughput and iso-parameter energy, CID actually carries a modest overhead. UID's phase-transition / emergence-style physical predictions **cannot yet be distinguished from a plain Transformer** at the 10M single point.

---

## 1. Environment and Data

### 1.1 Dependencies and versions

A dedicated virtual environment was built from `requirements.txt`. A per-item check surfaced **3 packaging issues** (see §5); after handling them, all final versions fall within the official constraints:

```
torch 2.11.0+cu128   transformers 4.57.6 (<5.0)   numpy 1.26.4   scipy 1.17.1
datasets 4.8.4       matplotlib 3.10.9            protobuf 7.35.1  tqdm 4.67.3
```

Import self-check: `get_ablation_configs()` returns **11** ablation variants; the `bert-base-chinese` tokenizer loads successfully with **vocab_size = 21128**.

### 1.2 Data preparation

Following the official docs: download the pretrain corpus from ModelScope `gongjy/minimind_dataset` → convert to `pretrain.jsonl` via `convert_minimind_data.py` → take the first 100,000 entries:

```bash
head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl
```

Data checksum:

```
pretrain_100k.jsonl : 100,000 lines / 71 MB
md5                 : f27f4c15095f44ecd3388b4c0ef6169a
```

Preprocessing (`data_loaders.PretrainJsonl`): `bert-base-chinese` tokenization, `max_length=512`; build causal-LM `labels` (pad → -100); **9:1 train/eval split with the split seed fixed to `manual_seed(42)`**, decoupled from the run seed — this guarantees that processes with different run seeds use exactly the same eval set, so results are comparable and mergeable.

---

## 2. Ablation (Core: Parameter Efficiency)

Command (one process per seed, three in parallel; equivalent to a single sequential process, since each (variant, seed) sets its own seed before training):

```bash
python experiments/run_ablation.py \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --scale 10M --epochs 1 --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
  --output_dir output/ablation_100k
```

### 2.1 All 11 variants, eval_ppl (3 seeds)

| Rank | Variant | Params | eval_ppl (mean ± std) | Tier |
|---|---|---|---|---|
| 1 | cid_full_no_et | 10.37M | **22.87 ± 0.17** | CID |
| 2 | cid_full | 10.37M | **23.62 ± 0.11** | CID |
| 3 | cid_no_vortex | 10.37M | 23.71 ± 0.20 | CID |
| 4 | cid_no_noise | 10.37M | 23.79 ± 0.04 | CID |
| 5 | cid_no_memory | 10.27M | 28.65 ± 0.26 | CID (memory removed) |
| 6 | transformer_plus_conv | 10.62M | 72.81 ± 0.44 | Transformer |
| 7 | transformer_plus_all_tricks | 10.62M | 73.33 ± 0.72 | Transformer |
| 8 | transformer_plus_noise | 10.52M | 73.55 ± 0.14 | Transformer |
| 9 | transformer_plus_linear | 10.52M | 73.57 ± 0.13 | Transformer |
| 10 | transformer_baseline | 10.52M | **73.58 ± 0.20** | Transformer |
| 11 | cid_full_fft_noise | 10.37M | 157.28 ± 2.87 | CID (FFT noise, degraded) |

The CID tier (22–29) and the Transformer tier (73) are separated by an order of magnitude, with very small cross-seed std.

### 2.2 CID vs Transformer ratio

| Comparison | TF ppl | CID ppl | Ratio | z(eval_loss) |
|---|---|---|---|---|
| Comparison A: transformer_plus_all_tricks / cid_full | 73.33 | 23.62 | **3.11×** | **182.2** |
| transformer_baseline / cid_full | 73.58 | 23.62 | 3.12× | 374.8 |

→ Under single-epoch training, CID's perplexity is about **3.1× lower** than a same-parameter-count Transformer, with overwhelming statistical significance.

### 2.3 Physics-term ablation reading

- **Memory kernel** (removing it: 23.6→28.7, +21%): largest contributor.
- **Noise type** (OU 23.6 vs FFT 157.3): OU noise is far better than FFT.
- **ET symmetric term** (removing it: 23.62→22.87, slight **improvement**): no engineering benefit in this causal-LM setting.

---

## 3. Scaling Law: Parameter Efficiency Under Full Training

The ablation uses a single epoch; the scaling law uses the full-training budget of `run_scaling_law.py`. Note the two training-budget conventions:

- `run_scaling_law.py` itself defaults to `tokens_per_param=20` (Chinchilla-optimal);
- the end-to-end `run_all.py` pipeline defaults to `tokens_per_param=200` (full convergence on small datasets).

These differ by 10× in training volume, yielding different convergence levels and ratios. Both are reported below.

### 3.1 tokens_per_param=200 (full training, 10M, 3 seeds)

```bash
python experiments/run_scaling_law.py \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --scales 10M --families transformer transformer_plus_tricks cid_full \
  --seeds 42 43 44 --batch_size 64 --max_seq_len 512 --target_tokens_per_param 200
```

| family | non-emb params | eval_ppl (3 seeds) | mean ± std |
|---|---|---|---|
| transformer | 5.12M | 31.35 / 30.98 / 31.03 | **31.12 ± 0.16** |
| transformer_plus_tricks | 5.21M | 30.90 / 31.32 / 31.48 | 31.23 ± 0.24 |
| **cid_full** | 4.83M | 7.88 / 7.90 / 7.90 | **7.89 ± 0.01** |

**Ratios**:

| Comparison | Ratio (3 seeds) |
|---|---|
| transformer / cid_full | **3.94× ± 0.03** (per-seed 3.98 / 3.92 / 3.93) |
| (transformer+tricks) / cid_full | 3.96× ± 0.03 |

→ Under full training the ratio grows to **3.94× (≈4×)**, and cid_full uses **fewer** parameters (4.83M vs 5.12M), with very low cross-seed variance.

### 3.2 tokens_per_param=20 (10M + 30M, scale-trend reference)

| scale | transformer | transformer+tricks | cid_full | TF / CID |
|---|---|---|---|---|
| 10M | 40.89 | 40.57 | 11.27 | 3.63× |
| 30M | 27.17 | 27.39 | 7.37 | 3.69× |

→ Under the undertrained budget the ratio is lower (3.6–3.7×), but it **rises slightly** from 10M→30M, consistent in direction with "parameter efficiency grows with scale." This convention is for scale-trend reference only; for the full-training figure see §3.1.

> **On training budget**: CID's perplexity advantage grows with training volume (single-epoch 3.1× → full-training 3.94×). Testing the paper's end-goal 5–10× prediction requires larger-scale, strictly iso-compute multi-scale curves.

---

## 4. Inference Efficiency and Energy

### 4.1 Inference throughput (prefill, `measure_inference_energy`)

| Model | Params | Throughput (tok/s) | Latency (ms/fwd) |
|---|---|---|---|
| cid_full | 10.37M | 594,686 | 13.78 |
| transformer_baseline | 10.52M | **756,026** | **10.84** |
| transformer_plus_all_tricks | 10.62M | 606,504 | 13.51 |

→ On raw inference throughput, the **plain Transformer is actually ~27% faster**. CID adds vortex / memory-kernel / colored-noise operators, increasing per-forward compute. **This is a separate dimension from parameter efficiency**: CID wins on "smarter at equal parameter count," not on "faster inference."

### 4.2 Energy benchmark (`run_energy_benchmark.py`, decode mode)

Clean idle baseline idle = 69.97 W (median of 3 windows, spread 0.56 W).

| family | non-emb params | above-idle mJ/token |
|---|---|---|
| cid_full | 4.83M | 265.26 |
| transformer | 5.12M | 221.69 |
| transformer_plus_tricks | 5.21M | 259.70 |

**Iso-parameter (VIEW 1, neutral overhead)**: cid_full / transformer = **1.20×** (CID's per-token energy is 20% higher, while using 6% fewer parameters). Same direction as the repo's prefill figure of ~13%; the difference comes from decode mode. This is expected overhead.

**Iso-performance, iso-PPL (VIEW 3, the decisive C13 ≥3× verdict)**: **not decidable at this scale**. The script requires the two families' ppl ranges to overlap, but at 10M–30M the transformer bottoms out around ~27 while CID is already at ~7–11 — **the ranges are disjoint**, the script refuses to extrapolate, and returns `out of range` for cid_full. This matches the repo's own stance: a 10M Transformer cannot reach CID's perplexity, so the iso-performance energy ratio is currently only a **lower bound** favoring CID; a rigorous ≥3× verdict needs larger-scale multi-scale curves.

---

## 5. Issues Found in the Repository

| # | Issue | Impact | Handling / Suggestion |
|---|---|---|---|
| 1 | `requirements.txt` pins `typeguard>=4.15.0`, but the package's highest version on PyPI is 4.5.2 | `pip install -r requirements.txt` fails outright | typeguard is not actually imported by the code; install 4.5.2 to work around. **Suggest upstream fix the version number** |
| 2 | `transformers` upper bound `<5.0`, while fresh environments often ship 5.x | `PreTrainedModel/Config` have breaking changes in 5.x | Pin to 4.57.6 in the dedicated venv |
| 3 | `protobuf>=7.35.0` is slightly above some distributions' default | minor | Upgrade to 7.35.1 in the venv |
| 4 | Script stdout is buffered under `nohup` | hard to observe progress live | Add `python -u`; or use the incremental `results.json` as a progress signal |
| 5 | `run_critical_exponents.py` default `n_sequences=10000` makes the downstream CPU statistics extremely slow | >3h without completing in practice | Reduce to `n_sequences=100` (still 6400 series samples). **Suggest a sampling cap or vectorization for that statistics step** |
| 6 | The docs don't highlight: ablation defaults `epochs=1`, `run_scaling_law` defaults `tpp=20`, `run_all` defaults `tpp=200` | different entry points give different ratios (3.1× vs 3.94×), easy to confuse | See §3. **Suggest documenting each entry point's default training budget in the README** |

---

## 6. Critical Exponents (UID Phase-Transition / Emergence Predictions)

```bash
python experiments/run_critical_exponents.py \
  --checkpoint <cid_full_10M_seed42.pt> --baseline_checkpoint <transformer_10M_seed42.pt> \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --max_seq_len 512 --n_sequences 100
```

| Test | Hurst H | β (spectral slope) | Avalanche α | Power law? | η |
|---|---|---|---|---|---|
| CID (noise-OFF) | 0.766 ± 0.14 | 0.513 | 2.819 | ✗ | 0.998 |
| CID (noise-ON) | 0.766 ± 0.14 | 0.513 | 2.819 | ✗ | 0.998 |
| Transformer (negative control) | 0.806 ± 0.11 | 0.639 | 2.524 | ✗ | 0.997 |
| shuffle surrogate | 0.519 | −0.001 | — | — | — |

**Verdict: `emergence_not_confirmed`.** Per-prediction check:

| Prediction | Theory range | Measured | Result |
|---|---|---|---|
| Hurst H | 0.6–0.8 | 0.77 (CID) / 0.81 (TF) | ✅ in range |
| 1/f spectral slope β | 0.7–1.3 | 0.51 / 0.64 | ❌ too low |
| Avalanche exponent τ | 1.5 ± 0.2 | α≈2.5–2.8, and KS rejects power law | ❌ not confirmed |
| Fisher anisotropy η | high | 0.998 | ✅ |

Key points:

1. The surrogate control works — after shuffling the time axis, H collapses 0.77→0.52 and β collapses 0.51→0, showing the hidden-state long-range temporal correlation structure is real, not coincidental.
2. The noise OFF vs ON difference is 0 on all three metrics, i.e. injecting colored noise at inference does not change the hidden-state statistics — "noise-driven emergence" has no supporting evidence at this scale.
3. **CID and Transformer have nearly identical critical exponents** — these long-range-correlation / anisotropy features are not unique to CID. The critical-exponent predictions cannot distinguish the two at the 10M single point.
4. This does not affect the parameter-efficiency conclusions of §2/§3, which are robust (3.1–3.94×).

---

## 7. Conclusions

1. **Core results reproduce**: in a clean independent environment, the key numbers from the ablation (11 variants × 3 seeds) and the full-training scaling law (3 seeds) match the repo's published values digit-for-digit (Comparison A 3.11× / z=182.2; scaling law cid 7.89 / tf 31.12).
2. **The parameter-efficiency ratio is a function of training budget**: single-epoch 3.1×, full-training (tpp=200) **3.94× ± 0.03** (≈4×), with CID using fewer parameters and very low cross-seed variance.
3. **Dimension distinction**: CID's advantage is parameter efficiency (lower perplexity at equal parameter count), not inference speed or iso-parameter energy — on the latter two CID actually carries ~20–27% overhead.
4. **Physics-term attribution**: the memory kernel contributes most; OU noise far outperforms FFT; the borrowed ET symmetric term brings no engineering benefit.
5. **Open items (consistent with the repo's own stance)**: the ≥3× iso-performance (iso-PPL) energy verdict and the critical-exponent emergence predictions **cannot hold or cannot be decided** at the 10M single point / the 10M–30M range; they require larger-scale, strictly iso-compute multi-scale experiments.

---

## Appendix: Traceable Data

All raw results are saved under `output/` in the reproduction working directory (paths relative to the working directory):

| Content | Path |
|---|---|
| Code / env / data provenance | `output/provenance/{git_head,pip_versions,data_checksum,gpu}.txt` |
| Ablation raw (per seed) / aggregate | `output/ablation_100k_seed{42,43,44}/results.json` · `output/combined_summary.json` |
| Scaling law tpp=200 (3 seeds) | `output/sl200_<family>_10M[_seed{43,44}]/results.json` · `output/sl200_3seed_summary.json` |
| Scaling law tpp=20 (10M+30M) | `output/sl_<family>_<scale>/results.json` · `output/scaling_summary.json` |
| Inference efficiency / energy | `output/infer_efficiency/infer_efficiency.json` · `output/energy/results.json` · `output/energy_summary.json` |
| Critical exponents | `output/critical_exponents/results.json` |

**Per-seed raw eval_ppl (ablation, key variants)**:

```
cid_full_no_et       [42,43,44] = [22.81, 23.10, 22.70]
cid_full             [42,43,44] = [23.76, 23.50, 23.59]
cid_no_memory        [42,43,44] = [28.74, 28.30, 28.91]
transformer_baseline [42,43,44] = [73.30, 73.66, 73.77]
cid_full_fft_noise   [42,43,44] = [160.83, 157.22, 153.80]
```

**Per-seed raw eval_ppl (scaling law tpp=200)**:

```
transformer  [42,43,44] = [31.35, 30.98, 31.03]
cid_full     [42,43,44] = [ 7.88,  7.90,  7.90]
```

---

*All figures in this report are independently measured in this run and can be re-computed via the paths and commands above.*
