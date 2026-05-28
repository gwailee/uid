<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-28

Index of empirical results published under this directory.
This file is the SINGLE SOURCE OF TRUTH for "which result files
are trustworthy and which are not", and must be kept in sync with
CHANGELOG.md and KNOWN_LIMITATIONS.md.
-->

# UID Empirical Results Index

> **English first; 中文紧随其后（同一段落先英后中）。本目录为 UID
> 项目所有实证结果的索引；任何引用本目录内文件的论文都应当先阅读本
> 文件以判断该文件的可信范围。**

This directory holds all empirical result files produced by the UID
Theory project. It is the **single source of truth** for "which result
files are trustworthy and at which version", and must be read alongside
[`../CHANGELOG.md`](../CHANGELOG.md) and
[`../KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) before any
result here is cited.

本目录存放 UID 理论项目产生的所有实证结果文件。它是"哪些结果文件可信、
在哪个版本下可信"的**单一可信源**，引用前必须与
[`../CHANGELOG.md`](../CHANGELOG.md) 与
[`../KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) 一并阅读。

---

## ⚠️ Cite-or-not quick reference

The single most important table in this file:

本文件中最重要的一张表：

| Version of result file | Citation policy | Reason |
|---|---|---|
| **Pre-Phase-1 (any v0.1 / v2.0 result file)** | ❌ **DO NOT CITE** | v0.1: ten methodological defects (see `KNOWN_LIMITATIONS.md` §A). v2.0: seven engineering bugs (see `KNOWN_LIMITATIONS.md` §B). |
| **Phase 1 v2.1 results** (when published under `phase1/`) | ✅ Citable, with caveat: must mention v2.1 commit hash | Phase 1 is the first set of results produced under the corrected v2.1 infrastructure. |
| **Phase 2+ v2.1 results** (when published under `phase2/`, `phase3/`, ...) | ✅ Citable | Validated at progressively larger scale and across hardware. |
| **Phase 4 independent reproductions** | ✅ Citable as INDEPENDENT confirmation | Reproduced by third parties without private communication. |
| **Phase 5 peer-reviewed paper** | ✅ Citable as PEER-REVIEWED record | Submitted and reviewed via standard journal channels. |

> **Current status (as of v2.1 release, 2026-05-28)**: Phase 0
> (infrastructure) is complete; **Phase 1 has NOT yet been run**. This
> directory therefore contains NO citable empirical claims yet.
> See [`../ROADMAP.md`](../ROADMAP.md) for the schedule.

> **当前状态（v2.1 发布时，2026-05-28）**：Phase 0（基础设施）已完成；
> **Phase 1 尚未运行**。因此本目录暂时**不包含任何可引用的实证主张**。
> 详见 [`../ROADMAP.md`](../ROADMAP.md)。

---

## Directory layout

When fully populated, this directory will mirror the phase structure
of `ROADMAP.md`:

完整填充后，本目录将镜像 `ROADMAP.md` 的阶段结构：

```
results/
├── README.md                        This file
│
├── phase1/                          Phase 1 (2026 Q2-Q3): 10M-100M scaling
│   ├── REPORT.md                    Phase 1 summary with F1-F8 pass/fail
│   ├── MANIFEST.json                Machine-readable index of all phase1 files
│   ├── scaling_law/
│   │   ├── results.json             Per-(family, scale, seed) loss / PPL
│   │   ├── scaling_curves.png       Iso-FLOP plot
│   │   └── checkpoints/             *_seed{seed}.pt files (>= 3 GB total)
│   ├── ablation/
│   │   ├── results.json             Per-(variant, seed) metrics
│   │   ├── summary.json             Aggregated + 3 critical-contrast verdicts
│   │   └── tables/                  Markdown tables for the report
│   ├── critical_exponents/
│   │   ├── results.json             beta / H / eta / tau per checkpoint
│   │   ├── verdict.md               Pass/fail of F3, F4, F5, F6
│   │   └── plots/                   Spectrum and DFA plots
│   ├── avalanche/
│   │   ├── results.json             Clauset-MLE fits with KS p-values
│   │   └── plots/                   Avalanche size distributions
│   └── energy/
│       ├── results.json             v2.1 energy meter output (raw + above-idle)
│       ├── verdict.md               Pass/fail of F7
│       └── traces/                  Power-vs-time traces per measurement
│
├── phase2/                          Phase 2 (2026 Q3-Q4): 300M-1B scaling
│   └── (same structure as phase1/)
│
├── phase3/                          Phase 3 (2026 Q4): Multi-hardware energy
│   ├── REPORT.md
│   ├── h100/
│   ├── a100/
│   ├── rtx4090/
│   └── jetson_orin/
│
├── phase4/                          Phase 4 (2027 Q1): Independent reproduction
│   ├── REPORT.md
│   └── teams/
│       ├── team_A/
│       ├── team_B/
│       └── team_C/
│
└── phase5/                          Phase 5 (2027 Q2+): Peer review
    ├── arxiv_v2.0_preprint/
    ├── submission_package/
    ├── reviewer_responses/
    └── (final accepted version when available)
```

The corresponding Python pseudo-tree (for tooling that walks the
directory):

对应的 Python 伪结构（供遍历工具使用）：

```python
RESULT_PHASES = {
    "phase1": {
        "subdirs": [
            "scaling_law", "ablation", "critical_exponents",
            "avalanche", "energy",
        ],
        "required_top_files": ["REPORT.md", "MANIFEST.json"],
    },
    "phase2": {"mirrors": "phase1"},
    "phase3": {
        "subdirs": ["h100", "a100", "rtx4090", "jetson_orin"],
        "required_top_files": ["REPORT.md", "MANIFEST.json"],
    },
    "phase4": {
        "subdirs": ["teams"],
        "required_top_files": ["REPORT.md"],
    },
    "phase5": {
        "subdirs": [
            "arxiv_v2.0_preprint", "submission_package",
            "reviewer_responses",
        ],
        "required_top_files": ["REPORT.md"],
    },
}
```

---

## File schemas

Every JSON file in this directory tree must conform to one of the
schemas below. Result files that do not conform should be flagged
as data-quality issues via the
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §D reporting channel.

本目录所有 JSON 文件都必须遵循下列 schema 之一。不符合的结果文件
应通过 [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §D 渠道
报告为数据质量问题。

### Schema 1 — Top-level `MANIFEST.json` (per phase)

```json
{
  "schema_version": "manifest_v1",
  "phase": "phase1",
  "uid_version": "v2.1",
  "uid_commit_hash": "abcdef1234567890...",
  "produced_on": "2026-07-15",
  "timezone": "Asia/Shanghai",
  "hardware_summary": {
    "gpu_model": "NVIDIA H100 80GB SXM5",
    "gpu_count": 8,
    "node_count": 4,
    "cuda_version": "12.4",
    "torch_version": "2.4.0+cu124",
    "driver_version": "555.42.06"
  },
  "tokenizer": {
    "name": "gpt2",
    "vocab_size": 50257
  },
  "datasets": [
    {
      "name": "wikitext-103",
      "version": "raw-v1",
      "path_in_repo": "data/wikitext-103/",
      "sha256_train": "..."
    }
  ],
  "seeds": [42, 43, 44],
  "files": [
    {
      "path": "scaling_law/results.json",
      "schema": "scaling_law_v1",
      "sha256": "...",
      "size_bytes": 12345,
      "produced_by": "experiments/run_scaling_law.py",
      "cli_args": {...}
    }
  ],
  "falsification_outcomes": {
    "F1": "PASS",
    "F2": "PASS",
    "F3": "PASS",
    "F4": "PASS",
    "F5": "PASS",
    "F6": "ABSTAIN_rank_deficient",
    "F7": "PASS",
    "F8": "FAIL"
  }
}
```

**Required fields**: every key shown above. The `falsification_outcomes`
block must list every F-condition that the phase claimed to test in
`ROADMAP.md`, with one of these values:

- `"PASS"` — the condition was met
- `"FAIL"` — the condition was not met (UID claim falsified)
- `"ABSTAIN_rank_deficient"` — measurement was inconclusive because
  of a data-quality issue (e.g. seq_len < hidden_size for η)
- `"ABSTAIN_not_measured"` — the condition was not tested in this phase
- `"PARTIAL"` — pass on some seeds / hardware, fail on others
  (must be accompanied by per-seed / per-hardware breakdown in the
  REPORT.md)

### Schema 2 — `scaling_law_v1` (matches `experiments/run_scaling_law.py`)

```json
{
  "experiment": "scaling_law_v2.1",
  "timestamp": "2026-07-15 12:34:56",
  "n_results": 45,
  "results": [
    {
      "model_family": "cid_full",
      "scale_name": "100M",
      "non_emb_params": 124562304,
      "train_flops": 1.49e+19,
      "final_train_loss": 2.1234,
      "final_eval_loss": 2.3456,
      "final_eval_ppl": 10.44,
      "wall_clock_seconds": 8421.5,
      "seed": 42,
      "v21_keys": {
        "family": "cid_full",
        "scale": "100M",
        "vocab_size": 50257,
        "max_seq_len": 1024,
        "noise_type": "ou",
        "noise_tau": 10.0,
        "noise_beta": 1.0,
        "use_et_symmetric": true
      }
    }
  ]
}
```

### Schema 3 — `ablation_summary_v1` (matches `experiments/run_ablation.py`)

```json
{
  "summary": [
    {
      "ablation": "cid_full",
      "n_seeds": 3,
      "eval_loss_mean": 2.345,
      "eval_loss_std": 0.012,
      "eval_ppl_mean": 10.43,
      "eval_ppl_std": 0.13
    }
  ],
  "critical_comparisons": [
    {
      "title": "CRITICAL COMPARISON A: cid_full vs transformer_plus_all_tricks",
      "name_a": "cid_full",
      "name_b": "transformer_plus_all_tricks",
      "loss_a": 2.345,
      "loss_b": 2.567,
      "advantage": 0.222,
      "z_score": 4.81,
      "verdict": "supported"
    }
  ]
}
```

### Schema 4 — `critical_exponents_v1` (matches `run_critical_exponents.py`)

```json
{
  "cid_emergence": {
    "model_name": "cid_full_noise_OFF",
    "noise_injection_on": false,
    "hurst": {
      "hurst_mean": 0.712, "hurst_std": 0.041,
      "n_series": 320, "sample_length": 4096, "method": "DFA"
    },
    "spectrum": {
      "beta_mean": 0.982, "beta_std": 0.087,
      "n_series": 320, "sample_length": 4096, "r_squared_mean": 0.94
    },
    "avalanche": {
      "alpha": 1.51, "alpha_se": 0.06,
      "xmin": 12.0, "n_tail": 4321,
      "ks_statistic": 0.018, "p_value": 0.34,
      "is_power_law": true
    },
    "eta": {
      "eta_mean": 0.71, "eta_std": 0.05,
      "eta_in_range": true,
      "n_samples": 256,
      "hidden_size": 768, "seq_len": 4096,
      "rank_deficient": false
    }
  },
  "cid_with_noise": {"...": "same shape, noise_injection_on=true"},
  "baseline": {"...": "optional negative-control result"},
  "verdict": {
    "beta_off": 0.982, "beta_on": 0.991,
    "hurst_off": 0.712, "hurst_on": 0.708,
    "eta_off": 0.71, "eta_on": 0.99,
    "beta_diff": 0.009, "hurst_diff": 0.004, "eta_diff": 0.28,
    "beta_in_range": true,
    "hurst_in_range": true,
    "eta_state": "pass",
    "eta_threshold": 0.5,
    "eta_rank_deficient": false,
    "noise_diff_tol": 0.05,
    "verdict": "emergence_confirmed"
  }
}
```

### Schema 5 — `energy_v2.1_batch4` (matches `run_energy_benchmark.py`)

```json
{
  "schema_version": "energy_v2.1_batch4",
  "timestamp": "2026-07-15 14:00:00",
  "metadata": {
    "python_version": "3.11.9",
    "platform": "Linux-5.15.0-...-x86_64",
    "torch_version": "2.4.0+cu124",
    "cuda_version": "12.4",
    "device_name": "NVIDIA H100 80GB HBM3",
    "cli_args": {...}
  },
  "results": {
    "cid_full": {
      "model_name": "cid_full",
      "mode": "decode",
      "device": "cuda:0",
      "gpu_name": "NVIDIA H100 80GB HBM3",
      "sampler": "pynvml",
      "sample_rate_hz": 24.7,
      "n_samples": 1234,
      "n_warmup": 50, "n_measure": 500,
      "batch_size": 16, "seq_len": 1024,
      "total_tokens": 524288,
      "new_tokens_per_decode": 64,
      "wall_clock_seconds": 50.21,
      "idle_power_watts": 78.4,
      "idle_window_seconds": 2.0,
      "avg_power_watts": 412.3,
      "max_power_watts": 487.1,
      "power_above_idle_watts": 333.9,
      "total_energy_joules": 20712.4,
      "energy_above_idle_joules": 16769.2,
      "energy_per_token_joules": 0.03951,
      "energy_per_token_above_idle_joules": 0.03199,
      "notes": ["sampler=pynvml", "requested_rate_hz=25.00"],
      "checkpoint": "results/phase1/scaling_law/checkpoints/cid_full_100M_seed42.pt",
      "loaded_family": "cid_full"
    },
    "transformer": {"...": "same shape"}
  }
}
```

### Schema 6 — `REPORT.md` (per phase)

Every phase's `REPORT.md` must contain at least these sections, in
this order:

每个阶段的 `REPORT.md` 必须按以下顺序至少包含这些章节：

1. **Phase metadata**: phase name, dates (start / end), UID version,
   commit hash, total compute used (GPU-hours).
2. **Falsification scorecard**: a table listing every F-condition
   this phase tested, with the verdict (`PASS` / `FAIL` /
   `ABSTAIN_*` / `PARTIAL`) and a one-sentence justification.
3. **Per-experiment summaries**: one subsection per result type
   (scaling, ablation, critical exponents, avalanche, energy),
   each linking to the underlying JSON and any plots.
4. **Anomalies and surprises**: any result that deviates by more
   than 20% from the pre-registered expectation, with hypothesis on
   the cause and proposed follow-up.
5. **Implications for downstream phases**: how this phase's outcome
   modifies Phase N+1's plan.
6. **Limitations**: what this phase did NOT test, and what its
   results cannot be used to conclude.
7. **Reproducibility appendix**: exact CLI invocations, seed list,
   total wall-clock per experiment, link to MANIFEST.json sha256.

---

## How to cite a result from this directory

The canonical citation format is:

引用本目录文件的标准格式：

> LI, Gui, JIE, Dangyang, & KANG, Haitao. (2026). Intelligence Is a
> Non-Equilibrium Field: A Three-Tier Physical Theory of Unified
> Intelligo-Dynamics (UID), v2.1 reference implementation,
> Phase {N} empirical results, file
> `results/phase{N}/{subdir}/{file}` (commit `{hash}`).
> Zenodo. https://doi.org/10.5281/zenodo.20372493

When citing a single number (e.g. "η = 0.71"), please add:

引用具体数值时（例如 "η = 0.71"），请补充：

* the v2.1 commit hash that produced the file,
* the seed (or "averaged over seeds 42, 43, 44"),
* the hardware platform (relevant for energy numbers),
* the v2.1 batch number of the producing script
  (e.g. "energy v2.1 batch 4"),
* and the relevant `KNOWN_LIMITATIONS.md` §-entry if any limitation
  applies (e.g. for η, the surrogate-status note in §C3).

Example:

引用示例：

> "We measured η = 0.71 ± 0.05 (UID v2.1, commit `abcdef1`,
> averaged over seeds {42, 43, 44}, H100 80GB, energy meter v2.1
> batch 4; note that η is computed on the hidden-state empirical
> covariance per `KNOWN_LIMITATIONS.md` §C3, not on the
> parameter-space true Fisher matrix)."

---

## Verifying result-file integrity

Every JSON result file should match the SHA-256 recorded in the same
phase's `MANIFEST.json`. To verify locally:

每个 JSON 结果文件都应与同阶段 `MANIFEST.json` 中记录的 SHA-256 一致。
本地校验：

```bash
# Single file:
sha256sum results/phase1/scaling_law/results.json

# All files in a phase (compare against MANIFEST.json):
python -c "
import json, hashlib, sys
from pathlib import Path
phase = sys.argv[1]
manifest = json.loads(Path(f'results/{phase}/MANIFEST.json').read_text())
ok = True
for entry in manifest['files']:
    p = Path('results') / phase / entry['path']
    if not p.exists():
        print(f'MISSING: {p}')
        ok = False
        continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != entry['sha256']:
        print(f'HASH MISMATCH: {p}')
        print(f'  expected: {entry[\"sha256\"]}')
        print(f'  actual:   {h}')
        ok = False
sys.exit(0 if ok else 1)
" phase1
```

A successful run prints nothing and exits 0; any failure prints the
offending file(s) and exits 1.

---

## Current snapshot (2026-05-28, v2.1 release)

> **Status: pre-Phase-1.**
>
> This directory currently contains only this `README.md` and (if
> committed) a single `phase1/MANIFEST.json` placeholder. No
> empirical claims can be cited from this directory yet. See
> [`../ROADMAP.md`](../ROADMAP.md) §Phase 1 for the running schedule.

> **状态：Phase-1 前。**
>
> 本目录当前仅含本 `README.md` 及（如已提交）一个 `phase1/MANIFEST.json`
> 占位文件。本目录暂时不含任何可引用的实证主张。
> 详见 [`../ROADMAP.md`](../ROADMAP.md) §Phase 1 的进度。

### Files known to be present at v2.1 release

| File | Purpose | Status |
|---|---|---|
| `results/README.md` | This file | ✅ Present |
| `results/phase1/MANIFEST.json` | Placeholder; will be regenerated when Phase 1 results land | ⏳ Placeholder only |
| `results/phase1/REPORT.md` | Will be authored when Phase 1 results land | ⏳ Not yet authored |

### Files INTENTIONALLY NOT present

The following files **must never** appear in this directory:

下列文件**绝对不应**出现在本目录中：

| File pattern | Why excluded |
|---|---|
| `results/*_v0.1_*` | v0.1 results are unciteable per `KNOWN_LIMITATIONS.md` §A |
| `results/*_v2.0_*` | v2.0 results are invalidated per `KNOWN_LIMITATIONS.md` §B |
| `results/*expected*.json` | Projected (not measured) numbers; belong in `theory.md`, not `results/` |
| `results/*proprietary*` | Anything covered by a non-disclosure agreement; cannot be opened |
| Raw checkpoints `> 10 GB` | Push to Hugging Face Hub or Zenodo instead; link from the relevant `MANIFEST.json` |

If you discover any of the above in a fresh clone, please report it
via [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §D.

---

## Negative-result policy

If a Phase-1 (or later) experiment produces a result that **falsifies**
a UID prediction (i.e. F-condition verdict = `FAIL`), we commit to:

如果 Phase 1（或更后）的实验产生了**证伪** UID 预言的结果（即 F-条件
verdict = `FAIL`），我们承诺：

1. **Publish the negative result with the same prominence as a
   positive one** — on the front page of `README.md`, the
   corresponding `REPORT.md`, and the project's Zenodo description.
2. **Do not delete or hide the result file**. Even if a later phase
   re-tests and passes, the failing result stays in
   `results/phase{N}/` permanently.
3. **Update `KNOWN_LIMITATIONS.md` §C** to note which UID claim was
   falsified at which scale.
4. **Update the theory paper** in Phase 5 to acknowledge the
   falsification and to explain which part of the theory survives
   and which needs revision.

These commitments are part of the pre-registered open-science
contract; violating them would invalidate the entire validation
programme.

这些承诺是预注册开放科学契约的一部分；违反将使整个验证计划失去意义。

---

## Contact

For questions about this directory's contents or about how to
reproduce any published result:

关于本目录内容或如何复现已发布结果的问题：

* **GitHub Issues** (preferred for technical reproducibility
  questions) — please tag with `results-question`.
* **Email** `lig@jodell.cn` (Suzhou Jodell Robotics Co., Ltd.) with
  subject prefix `[UID Results]`.

For Phase 4 independent-reproduction enquiries, see
[`../ROADMAP.md`](../ROADMAP.md) §"How to follow / contribute".

Phase 4 独立复现合作详见 [`../ROADMAP.md`](../ROADMAP.md)
"How to follow / contribute" 章节。

---

## Closing statement

> The integrity of a research programme is measured not by how many
> results it publishes, but by how clearly it labels which results
> are trustworthy and which are not. This directory's index — and
> especially the "cite-or-not quick reference" table — is the
> instrument by which UID makes that distinction explicit.
>
> If a future reader cites a UID result without checking the
> corresponding entry in this file, that is a citation we cannot
> defend. If a future reader cites it WITH the corresponding entry,
> we will defend it to the end.
>
> 一个研究计划的诚信，不取决于它发布了多少结果，而取决于它有多么清晰
> 地标注了哪些结果可信、哪些不可信。本目录的索引——尤其是"引或不引
> 快速参考表"——就是 UID 把这一区分显性化的工具。
>
> 如果未来读者引用 UID 结果时没有查阅本文件对应条目，那不是我们能为
> 之辩护的引用。如果引用时**附带**了本文件的对应条目，我们会一辩到底。
```

---

## ✅ 复制清单

新增**单个文件**：

```
results/README.md
```

如果 `results/` 目录尚不存在，先：

```bash
mkdir -p results
mkdir -p results/phase1
