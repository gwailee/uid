<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-28

CHANGELOG for the UID Theory reference implementation.
Tracked using a hybrid of Keep a Changelog 1.1.0 + Semantic Versioning,
plus a "Theory mapping" column that records which §-section of the
theory paper each change targets.

中文与英文双语对照（同一段先英后中），便于跨地区审计与引用。
-->

# Changelog

All notable changes to this project are documented here. This file is
the **single source of truth** for what shipped in each release; any
empirical claim made in a paper or talk should cite the version it was
produced under.

本仓库所有重要变更均记录于此。本文件是**单一可信源**：任何论文 / 演讲
中提到的实验结果都应当注明它在哪个版本下产生。

Versioning policy:

* **Major bump** (`X.0.0`): incompatible API change OR a fundamental
  rewrite of the validation methodology (e.g. v0.1 → v2.0).
* **Minor bump** (`vX.Y.0`): backward-compatible new functionality or
  theory-paper-driven implementation fix that changes measured numbers
  but not the public API (e.g. v2.0 → v2.1).
* **Patch bump** (`vX.Y.Z`): bug fixes that do not affect measured
  numbers nor public API.

The latest entry is at the top.

---

## [v2.1] — 2026-05-28 — **§8.5 / §14.2 implementation fixes + full-stack infrastructure upgrade**

> **One-line summary**: v2.1 closes three concrete implementation gaps
> between v2.0 and the theory paper (HopfieldAttention, VortexField,
> colored noise), AND upgrades the entire validation infrastructure
> (CID/QID/FID parameter propagation, JSON-safe `info` dicts, η/Ricci
> direct measurement, unified checkpoint schema, real-hardware energy
> meter, 7 new test files with ~200+ test cases).

> **一句话总结**：v2.1 修复了 v2.0 与论文之间的三处具体实现缺陷
> （HopfieldAttention / VortexField / 色噪声），并完成了整套验证基础
> 设施的升级（CID/QID/FID 参数透传、`info` 字典 JSON 安全、η/Ricci
> 直接可测、统一 checkpoint schema、真实硬件能耗、7 个新测试文件含
> ~200+ 用例）。

### 🔴 Breaking (theory-paper alignment)

| Change | File(s) | Theory mapping |
|---|---|---|
| **`HopfieldAttention` now implements the ET symmetric dual-term update** (Lyapunov-guaranteed monotonic energy descent). Old behaviour available via `use_et_symmetric=False`. | `uid_theory/cid/hopfield_potential.py` | §8.5 (Hoover et al. 2023, arXiv:2302.07253) |
| **`VortexField` rebuilt from FFN antisymmetric projection** — `J = (W − W^T) / 2` — instead of two independent H×H matrices. Reduces extras from `2H²` to `+1` scalar per layer. | `uid_theory/cid/vortex_field.py` + `uid_theory/cid/cid_layer.py` | §14.2 (zero-extra-parameters principle) |
| **Default colored noise switched to Ornstein–Uhlenbeck physical SDE** (FFT version still selectable via `noise_type="fft"`). | `uid_theory/cid/colored_noise.py` + `uid_theory/cid/cid_layer.py` | §14.2 (physically self-consistent FDT) |

> **⚠ Re-run notice**: Any v2.0 benchmark using `VortexField` in
> `transformer_plus_linear` / `transformer_plus_all_tricks` was running
> a silent no-op (the curl term degenerated to zero because no
> `weight_ref` was passed). All such v2.0 numbers must be re-run on
> v2.1 before citation. See "Critical bugs fixed" below.

> **⚠ 重新跑分通告**：v2.0 中所有用到 `transformer_plus_linear` /
> `transformer_plus_all_tricks` 的基线对比都跑在了"linear extra 静默
> 退化为零"的状态下。这些 v2.0 数据必须在 v2.1 下重跑后才可引用。

### ✨ Added

#### CID tier
- New `HopfieldAttention.compute_energy(x, beta=1.0)` returns the ET
  energy value for any input, enabling end-to-end Lyapunov verification.
- New `CIDLayer.set_energy_monitoring(bool)`: per-layer `info` dict
  now carries `"et_energy"` when enabled.
- New `CIDLayer.fluctuation_dissipation_consistency()`: per-layer
  diagnostic of the FDT relation between sub-Ohmic memory α and
  colored-noise β.
- `cid_layer.py` adds `noise_type` (`"ou"` / `"fft"`), `noise_tau`,
  `noise_beta`, `use_et_symmetric` parameters — all defaulting to v2.1
  recommended values.

#### QID tier
- `qid_layer.py` now propagates all v2.1 CID keys (`noise_type`,
  `noise_tau`, `noise_beta`, `use_et_symmetric`) down to the embedded
  `CIDLayer`.
- New `hamiltonian_mode='shared_with_ffn'` (default, zero-extra-params)
  and `'dedicated'` (legacy H×H matrix).
- New `lindblad_mode='off'` (default, zero-extra-params), `'shared'`
  (1 shared H×H), `'independent'` (K H×H, legacy).
- New `quantum_noise_mode='ou'` (default, v2.1) and `'fft'` (legacy).
- New `QIDLayer.set_noise_injection(bool)`, `.set_energy_monitoring(bool)`,
  `.count_extras()` for diagnostics.
- `BerryPhaseLayer(weight_ref=...)`: zero-extra-params mode via
  reference to an external weight (e.g. attention K projection).
  Output phases bounded to `(-strength·π, +strength·π)` via `tanh*π`
  to avoid high-frequency oscillation failure modes.
- `QuantumColoredNoise.set_temperature(T)` / `.get_temperature()` for
  clean parameter sweeps.

#### FID tier
- New `ScalarCurvatureProbe.compute_anisotropy_eta(metric)` directly
  implements `η = (λ_max − λ_min) / (λ_max + λ_min)` per Theory §6.1 /
  README prediction 4. UID predicts η > 0.5 after training.
- New `ScalarCurvatureProbe.compute_ricci_scalar_surrogate(metric)`
  implements the log-det volume-element surrogate per Theory §6.2.
- Legacy `trace(g²)/trace(g)² − 1/H` preserved as
  `compute_legacy_anisotropy()` for back-compat with v2.0 result files.
- `FIDLayer` reports all three diagnostics in `info`:
  `fisher_anisotropy_eta`, `ricci_scalar_surrogate`, `anisotropy_legacy`.
- `FIDLayer` exposes `set_noise_injection`, `set_energy_monitoring`,
  `set_temperature`, `count_extras` at the top level.
- New `LOSS_PREFIX` constant + `extract_loss_tensors(info)` helper:
  cleanly separates autograd-bearing loss tensors from JSON-safe scalar
  diagnostics in the `info` dict.
- `FisherMetric.compute_true_fisher_diagonal(model, batch_input_ids)`:
  O(M) parameter-space diagonal Fisher via backprop trick, available
  for small-batch calibration of the empirical-covariance surrogate.
- `FisherMetric.compute(jitter=None)`: optional per-call jitter override.

#### Verification suite
- New `measure_fisher_anisotropy_eta(hidden_states, ...)`: standalone
  function for README prediction 4. Returns an `EtaResult` dataclass
  with `eta_mean`, `eta_std`, `eta_in_range`, `rank_deficient` etc.
- `run_critical_exponent_battery(..., include_eta=True, ...)`: η
  measurement integrated by default; backward-compat via
  `include_eta=False`.
- `energy_meter.py` rewritten as **v2.1 batch 4**:
  - `pynvml` high-frequency sampler (25 Hz default), `nvidia-smi`
    subprocess fallback (10 Hz cap)
  - Explicit `torch.cuda.synchronize()` + `time.perf_counter_ns()`
    boundaries
  - Independent idle-baseline measurement; reports
    `idle_power_watts`, `power_above_idle_watts`,
    `energy_above_idle_joules`, `energy_per_token_above_idle_joules`
  - New `mode='prefill'` (full-forward per iter) vs `mode='decode'`
    (token-by-token autoregressive)
  - CPU platform `RuntimeError` instead of fabricated numbers
  - `sampler_preference` switch (`"auto"` / `"pynvml"` / `"nvidia_smi"`)
- `ablation_suite.py` extended from 9 to **11 variants**:
  new `cid_full_no_et` (§8.5 isolation) and `cid_full_fft_noise`
  (§14.2 isolation). All v2.1 keys properly propagated through
  `build_ablation_model`.

#### Experiment scripts
- `run_scaling_law.py`:
  - New CLI args: `--noise_type`, `--noise_tau`, `--noise_beta`,
    `--no_et_symmetric`
  - **Now saves checkpoints** in a unified v2.1 schema
    `{family}_{scale}_seed{seed}.pt` (this was previously missing,
    silently breaking downstream `run_critical_exponents.py` /
    `run_energy_benchmark.py`)
  - Adds the `cid_full_no_et` and `cid_full_fft_noise` families
- `run_critical_exponents.py`:
  - New CLI args: `--eta_threshold`, `--eta_max_samples`,
    `--noise_diff_tol`
  - Verdict table adds an η row with three-state classification:
    `pass` / `fail` / `abstain_rank_deficient` / `abstain_missing`
  - `emergence_confirmed` now requires β AND H AND η to all pass
    (or η to abstain due to rank deficiency)
  - Loud data-quality warning when `max_seq_len < hidden_size`
- `run_ablation.py`:
  - Now reports **three critical contrasts** automatically:
    A. `cid_full` vs `transformer_plus_all_tricks`
    B. `cid_full` vs `cid_full_no_et` (§8.5 contribution)
    C. `cid_full` vs `cid_full_fft_noise` (§14.2 contribution)
- `run_energy_benchmark.py`:
  - New CLI args: `--mode`, `--new_tokens_per_decode`,
    `--sample_rate_hz`, `--idle_window_seconds`, `--sampler_preference`,
    `--scale`, `--seeds`
  - Verdict shows BOTH raw and above-idle ratios; warns when idle
    floor > 30% of total
  - Top-level JSON `metadata` block (torch/cuda versions, GPU name,
    CLI args) for reproducibility
- `run_all.py`:
  - Fixed checkpoint-path search: uses
    `find_checkpoint(family, scale, seed_preference)` instead of the
    broken hard-coded `cid_full_{scale}.pt` lookup
  - Now reports skipped experiments loudly instead of silently

#### Data loaders
- **`test_uid_on_minimind.py` renamed to `data_loaders.py`** (the
  `test_` prefix risked accidental pytest collection; the rename
  removes that risk).
- New `SftJsonl` dataset: supervised fine-tuning over
  `{"prompt": ..., "response": ...}` JSONL. Prompt positions are
  masked (`labels = IGNORE_INDEX`), response positions are supervised.
- **Truncation policy**: when the prompt is too long to fit, the
  truncator preserves the **tail** of the prompt (most-recent context),
  matching the instruction-tuning convention.
- New `make_collate_fn()` factory for `DataLoader` integration.
- `__main__` self-check entry point.

#### Test suite
Seven new v2.1 test files, ~200+ test cases in total:
- `tests/test_et_lyapunov.py` — §8.5 ET monotonic descent + §14.2
  zero-extra-params vortex.
- `tests/test_run_scaling_law.py` — v2.1 key propagation + unified
  checkpoint schema round-trip.
- `tests/test_qid_layer.py` — QID v2.1 propagation + zero-extra-params
  modes + bounded Berry phase + QFDT.
- `tests/test_fid_layer.py` — FID three-level propagation + JSON-safe
  info + η/Ricci/legacy surrogates.
- `tests/test_critical_exponents.py` — adds `TestFisherAnisotropyEta`
  (15+ cases) and `TestEtaInBattery` (5 cases); existing tests
  preserved.
- `tests/test_energy_meter.py` — trapezoidal integration, window
  filtering, sampler dispatch, CPU-refusal contract, GPU smoke
  (auto-skipped without CUDA).
- `tests/test_data_loaders.py` — covers `PretrainJsonl` + `SftJsonl`
  edge cases, including **`test_truncation_keeps_recent_prompt`** to
  pin down the v2.1 tail-keeping contract.

### 🐛 Critical bugs fixed

1. **`VortexField` silent no-op in baselines.**
   v2.0 instantiated `VortexField(hidden_size)` in
   `model/known_tricks_baseline.py` without passing `weight_ref`, so
   the curl operator was zero. This made `transformer_plus_linear`
   and `transformer_plus_all_tricks` silently degenerate, breaking
   the key falsification contrast. v2.1 passes
   `weight_ref=ffn.W1.weight` and adds a regression test.
2. **`UIDConfig` field loss across `save_pretrained` / `from_pretrained`.**
   v2.0 did not declare `noise_type`, `noise_tau`, `use_et_symmetric`
   in `UIDConfig.__init__`, so any HuggingFace-style serialise/load
   cycle silently dropped them. v2.1 adds all three to `__init__`.
3. **`collect_hidden_states` state corruption.**
   v2.0 always force-set noise injection back to `True` after
   measurement, even if the caller had set it to `False`. v2.1 saves
   and restores the original per-layer state.
4. **`run_scaling_law.py` didn't save checkpoints.**
   v2.0's `run_scaling_law.py` produced only `results.json` and
   `scaling_curves.png` — but `run_critical_exponents.py` and
   `run_energy_benchmark.py` both required checkpoint files. As a
   result, `run_all.py` silently skipped the latter two experiments.
   v2.1 saves checkpoints in a unified schema and `run_all.py`
   discovers them correctly.
5. **`prediction_test.py` circular measurement.**
   The v0.1 implementation enabled noise injection during
   measurement and used `|logits_a − logits_b|` as the "avalanche"
   signal. v2.1 demotes the whole file to a deprecated wrapper that
   auto-routes to the corrected v2.0+ toolchain and emits a
   `DeprecationWarning`.
6. **`FIDLayer.info["curvature_loss"]` JSON crash.**
   v2.0 returned a Tensor under that key, which broke `json.dumps`
   downstream. v2.1 introduces `LOSS_PREFIX` separation and the
   `extract_loss_tensors()` helper; `info` is now strictly
   JSON-safe.

### 🔧 Changed (behavioural)

- `CIDLayer` default `noise_type` is now `"ou"` (was implicit FFT).
- `CIDLayer.attn` defaults to `use_et_symmetric=True` (was always
  standard attention).
- `FisherMetric.compute` now requires `seq_len >= 2` and emits a
  `RuntimeWarning` (once per `(H, S)` pair) when
  `seq_len < hidden_size`, because the empirical covariance is
  rank-deficient in that regime and downstream η values are biased
  upward toward 1.0.
- `EnergyMeasurement.to_dict()` schema extended from 3 fields to 23
  (idle / above-idle / sampler metadata / etc.). Backwards-compatible:
  old fields preserved at the same keys with the same units.

### 📚 Documentation

- `README.md` (Chinese) and `README_en.md` (English) fully rewritten
  for v2.1; new sections include the v2.1 fix table, η as
  prediction 4, three critical contrasts, above-idle energy
  comparison, etc.
- This `CHANGELOG.md` rewritten as a tri-version document
  (v0.1 → v2.0 → v2.1).
- `KNOWN_LIMITATIONS.md` updated to include all v0.1 and v2.0
  methodological / engineering defects.
- `ROADMAP.md` updated to reflect Phase 0 completion (v2.1) and
  Phase 1 plan.

### 🔒 Security

No security-relevant changes in v2.1.

---

## [v2.0] — 2026-05-15 — **Honest validation rewrite**

> **One-line summary**: v2.0 was a complete methodological rewrite of
> v0.1's validation suite, motivated by detailed peer-review feedback
> exposing five categories of methodological defect in v0.1's
> "validated" claims.

> **一句话总结**：v2.0 是基于同行评审反馈对 v0.1 验证套件的完整方法学
> 重写，针对 v0.1 中"已验证"声明的五类方法学缺陷。

### 🔴 Breaking

- **`prediction_test.py` declared deprecated** (full removal scheduled
  for v3.0). Replaced by:
  - `verification/critical_exponents.py` (DFA + spectrum + battery)
  - `verification/avalanche_detector.py` (proper Beggs-Plenz protocol)
  - `verification/powerlaw_estimator.py` (Clauset-Shalizi-Newman MLE)
  - `verification/energy_meter.py` (real `nvidia-smi` measurement)
  - `verification/ablation_suite.py` (9-way ablation matrix)

### ✨ Added

- **Modern Transformer baseline** with RoPE + RMSNorm + SwiGLU
  (`model/modern_transformer.py`). v0.1's `TinyTransformerLM` was a toy.
- **`TransformerPlusTricksLM`** (`model/known_tricks_baseline.py`):
  the same Transformer with optional colored noise, depthwise conv,
  and extra linear term — the critical contrast for UID's "physical
  framework" claim.
- **9-way ablation suite** (`verification/ablation_suite.py`):
  4 CID component ablations + 5 known-tricks baselines, including
  the previously-missing `cid_no_memory`.
- **Iso-FLOP scaling-law experiment** (`experiments/run_scaling_law.py`)
  spanning 10M–1B model families with multiple seeds per cell.
- **`CIDLayer.set_noise_injection(bool)` API** to prevent the
  circular-measurement problem when measuring emergent critical
  exponents on trained models.
- **GitHub Actions CI/CD**: lint + unit tests + smoke test + nightly
  small-scale training.

### 🐛 Fixed (v0.1 methodological defects)

| Defect (v0.1) | Fix (v2.0) | Theory link |
|---|---|---|
| Critical-exponent measurement was circular: the noise pattern was injected at train time AND used during measurement, so the measured 1/f / Hurst were just echoes of the injection. | New `set_noise_injection(False)` API; battery driver disables injection before measurement. | §5 / Predictions 1-3 |
| Avalanche detection used `\|logits_a − logits_b\|` distribution (just noise differences, not avalanches). | Proper Beggs-Plenz protocol: z-score threshold crossings on hidden-state activations. | Prediction 1 |
| Power-law fitting used log-binned linear regression (known unreliable; see Clauset et al. 2009). | Clauset-Shalizi-Newman MLE + KS goodness-of-fit + bootstrap p-value. | Methodology |
| Sample size was 1 sequence × 256 timesteps. | Default 10,000+ sequences × 4096+ timesteps; `n_sequences` is now a CLI arg. | Methodology |
| Hurst exponent used R/S analysis (older method, less reliable). | DFA (Detrended Fluctuation Analysis) per Peng et al. 1994. | Prediction 2 |
| Baseline was `TinyTransformerLM` (toy with no RoPE/RMSNorm/SwiGLU). | Modern Transformer baseline. | Fair contrast |
| Ablation was 4-way (missing `cid_no_memory` and ALL "known tricks" baselines). | 9-way ablation including `transformer_plus_all_tricks`. | Falsification |
| Energy measurement was Landauer-limit theoretical arithmetic. | `nvidia-smi` real measurement; `energy_per_token_joules`. | Prediction 5 |
| Parameter efficiency claim compared equal model sizes (no scaling law). | iso-FLOP scaling-law study; the "≥ 5×" target is operationalised as horizontal distance between curves at iso-loss. | Prediction 4 |
| No published results, only "expected" projections. | `results/` directory committed with real result files (where they exist). | Open science |
| No CI/CD. | GitHub Actions: lint + tests + smoke + nightly. | Reproducibility |

### 🔧 Changed

- Project structure reorganised into `uid_theory/{cid,qid,fid,verification}/`
  with `model/` for baselines and `experiments/` for scripts.
- `requirements.txt` consolidated; added `requirements-dev.txt` for
  pytest / ruff.
- README rewritten with the "Honest v2.0 release" notice and
  pre-registered falsification conditions.

### 📚 Documentation

- New `KNOWN_LIMITATIONS.md`: honest declaration of v0.1's
  methodological defects.
- New `ROADMAP.md`: validation roadmap with pre-registered conditions.
- New `CHANGELOG.md`: this file (first edition).

### ⚠ Known issues at v2.0 release (all fixed in v2.1)

These were identified post-release and **invalidate any v2.0 numbers**
that depended on them:

1. `HopfieldAttention` was standard scaled dot-product attention, not
   the ET symmetric dual-term form mandated by Theory §8.5.
2. `VortexField` introduced two new H×H matrices, violating Theory
   §14.2's zero-extra-parameter principle and inflating per-layer
   parameter count by ~2H².
3. Default colored noise was FFT shaping, which created a
   circular-measurement risk even with `set_noise_injection(False)`.
4. `VortexField` in `transformer_plus_linear` /
   `transformer_plus_all_tricks` did not receive a `weight_ref`,
   silently degenerating to zero — meaning the v2.0 contrast did NOT
   actually test "all known tricks combined".
5. `UIDConfig` did not declare the new fields, so `save_pretrained` /
   `from_pretrained` silently dropped them.
6. `run_scaling_law.py` did not save checkpoints; downstream
   `run_critical_exponents.py` / `run_energy_benchmark.py` were
   skipped silently by `run_all.py`.
7. `FIDLayer.info["curvature_loss"]` was a `torch.Tensor`, breaking
   `json.dumps` downstream when `curvature_weight > 0`.

See the v2.1 entry above for the corresponding fixes.

---

## [v0.1] — 2026-03-01 — **Initial public release**

> **One-line summary**: First public release of the UID Theory
> reference implementation, alongside the v0.1 paper preprint.
> Subsequent peer review revealed that the validation suite suffered
> from circular reasoning and insufficient statistical rigour; v0.1
> "validated" claims should not be cited.

> **一句话总结**：UID 理论参考实现首次公开发布，与 v0.1 论文预印本同步
> 提交。后续同行评审发现验证套件存在循环论证与统计不足问题，v0.1 的
> "已验证"声明不应被引用。

### ✨ Initial features

- CID master-equation reference implementation:
  - `cid_layer.py` with associative memory, vortex, memory kernel,
    colored noise terms.
  - `model_uid.py`: HuggingFace-compatible causal LM wrapper.
- QID layer (classical simulation): Hamiltonian flow, phenomenological
  Lindblad channels, Berry-phase layer, quantum colored noise.
- FID layer: Fisher metric probe + scalar curvature surrogate.
- `prediction_test.py`: four falsification tests (avalanche τ,
  Hurst H, spectrum β, parameter efficiency).
- `TinyTransformerLM` baseline.
- v0.1 paper preprint with three claimed "validated" predictions.

### ⚠ Methodological defects identified during peer review

(See [`KNOWN_LIMITATIONS.md`](./KNOWN_LIMITATIONS.md) for the full list
and v2.0 / v2.1 for the fixes.)

1. Critical-exponent measurement is circular (noise injected at both
   train and measure time).
2. Avalanche detection uses an incorrect quantity (`|logits diff|`).
3. Power-law fitting uses log-binned linear regression (known
   unreliable).
4. Sample size of 1 × 256 is far below the regime where the fit is
   meaningful.
5. Hurst via R/S, not DFA.
6. Baseline is a toy Transformer.
7. Ablation matrix is incomplete (missing critical contrasts).
8. Energy comparison is theoretical, not measured.
9. Parameter-efficiency claim is single-point, not iso-FLOP.
10. No CI/CD; no published results; no pre-registered falsification
    conditions.

**Verdict on v0.1 empirical claims**: ❌ should not be cited.

---

## Conventions

* All dates are in `YYYY-MM-DD` ISO format.
* Theory section references (`§N.M`) refer to the version of the
  theory paper in this repository at the time of the release.
* Each version's "One-line summary" can be quoted standalone in
  release notes and Zenodo descriptions.
* "Re-run notice" boxes indicate that empirical numbers produced under
  the previous version are invalidated by a v-bump.
* Empirical-evidence grades (A / B / C / D) follow the convention
  established in the theory paper's Abstract.

---

## Contact

For commercial licensing or release-process questions:
**lig@jodell.cn** (Suzhou Jodell Robotics Co., Ltd.) — please prefix
the email subject with `[UID Changelog]`.

商业授权或发布流程问题：**lig@jodell.cn**（苏州钧舵机器人有限公司）。
邮件主题请以 `[UID Changelog]` 开头。
