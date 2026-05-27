# Known Limitations and Validation Roadmap

**Last updated**: 2026-05-25

This document **honestly acknowledges the methodological limitations** 
of the current UID validation suite, in response to detailed peer 
review feedback. We commit to addressing each issue with the 
roadmap below.

## 1. Acknowledged Limitations

### 1.1 Parameter Efficiency Test (CRITICAL)

**Current code** (in v0.1): The `test_parameter_efficiency` function 
compares **equal-sized** CID and Transformer models, and only checks 
`cid_ppl <= trans_ppl`. The `theory_min=5.0` and `theory_target=10.0` 
values are stored but **never used in the actual pass/fail decision**.

**Why this is wrong**: This does not measure parameter efficiency at 
all. To measure "5× parameter efficiency", we need a *small CID 
model* to match a *large Transformer model* in performance, then 
compute the ratio of their parameter counts.

**Fix in v1.0** (this version): Replaced with `run_scaling_law.py`, 
which trains model families of multiple sizes (10M, 30M, 100M, 
300M, 1B) and measures the horizontal shift between scaling curves 
at equal loss levels (Chinchilla-style methodology).

### 1.2 Critical Exponents are Circular

**Current code** (in v0.1): The `test_power_spectrum` and 
`test_hurst_exponent` functions measure spectral properties of 
hidden states **while colored noise is being actively injected 
into those same hidden states**. This is circular: the answer is 
planted before measurement.

**Why this is wrong**: This cannot prove that 1/f spectra or 
H≈0.7 are *emergent* properties of CID dynamics; they are simply 
*echoes* of what was injected.

**Fix in v1.0** (this version): 
- Added `--disable_noise_injection` mode to `cid_layer.py`
- Critical exponents are now measured **after training, with noise 
  injection turned off**, to test for genuine emergence
- Sample size increased from 1 sequence × 256 timesteps to 
  10,000+ sequences with proper time-series of length ≥ 4096

### 1.3 Avalanche Exponent τ Measurement is Wrong

**Current code** (in v0.1): Measures `|logits_a - logits_b|` 
distribution between two noisy forward passes, then fits a power 
law via log-binned linear regression.

**Why this is wrong**: 
- This measures noise difference distribution, not Beggs-Plenz 
  neural avalanches (which are spatio-temporal cascades)
- Log-binned linear regression for power-law fitting is **known 
  to be statistically unreliable** (see Clauset, Shalizi & Newman 
  2009, SIAM Review 51(4): 661-703)

**Fix in v1.0** (this version): 
- Implemented proper avalanche detection based on activation 
  threshold crossings (following Beggs & Plenz 2003)
- Replaced log-binned regression with **MLE + Kolmogorov-Smirnov 
  test** following Clauset-Shalizi-Newman (2009)
- Increased sample size to 10,000+ avalanches

### 1.4 "Physical Terms" are Known Techniques

**Honest acknowledgment**: 
- The "associative memory" term is **mathematically equivalent** to 
  standard scaled dot-product attention (Ramsauer et al. 2020 proved 
  this equivalence)
- The "memory kernel" (depthwise causal conv) is **structurally 
  similar** to Mamba/SSM components
- The "colored noise" is a form of **noise regularization** known 
  in the literature
- The "vortex field" (commutator of two linear maps) is a **simple 
  linear transformation**

**What UID claims to add**: A unified physical framework that 
*organizes* these components in a way that yields **measurable 
gains beyond their naive combination**. This claim must be tested 
against a strong baseline that includes all these tricks.

**Fix in v1.0** (this version): Added `known_tricks_baseline.py` 
which combines a modern Transformer with colored noise injection, 
depthwise causal convolution, and an extra linear projection term. 
**If full CID does not outperform this baseline at the same FLOP 
budget, the "physical framework" claim is falsified.**

### 1.5 No Real Experimental Results Published

**Current code** (in v0.1): The README shows "expected results" 
that are projections, not measurements. No real `results.json`, 
no training curves, no checkpoints.

**Fix in v1.0** (this version): 
- Real results are committed to `results/` directory
- All experiments include random seed control (3+ seeds)
- All configs, logs, curves, and checkpoints are version-controlled
- CI runs nightly smoke tests on small models

### 1.6 Weak Baseline

**Current code** (in v0.1): The baseline is `TinyTransformerLM`, a 
toy implementation without modern best practices.

**Fix in v1.0** (this version): Replaced with `modern_transformer.py`:
- RoPE positional encoding
- RMSNorm (instead of LayerNorm)
- SwiGLU FFN (instead of GELU)
- Tuned learning-rate schedule (cosine + warmup)
- Comparable to Llama-2/3 architecture conventions

### 1.7 Synthetic Data Fallback is Misleading

**Current code** (in v0.1): When real data is unavailable, the 
`--quick` mode trains on randomly generated tokens, which is 
meaningless.

**Fix in v1.0** (this version):
- Removed synthetic data fallback from CI tests
- CI requires a small but real text dataset (WikiText-2)
- `--quick` mode now does smoke-testing only, with explicit warning 
  that results are not scientifically valid

### 1.8 Missing Ablation Group

**Current code** (in v0.1): Has 4 ablation variants, missing 
`cid_no_memory`.

**Fix in v1.0** (this version): Now has 5 ablation variants:
- `baseline` (modern Transformer)
- `cid_no_vortex` 
- `cid_no_noise`
- `cid_no_memory` (NEW)
- `cid_full`

Plus 3 additional "known tricks" baselines:
- `transformer_plus_noise`
- `transformer_plus_conv`
- `transformer_plus_all_tricks`

## 2. QID and FID Layers: Honest Scope

**QID layer**: This is a **classical emulation** using neural 
networks to simulate quantum coherence (Berry phase, colored 
quantum noise, phenomenological Lindblad channels). It is **NOT** 
a faithful Kraus decomposition. True quantum advantage requires 
actual quantum hardware. **This code cannot verify QID's quantum 
claims.**

**FID layer**: The Fisher metric and curvature surrogates serve as 
**diagnostic probes and soft regularizers**, not as numerical 
solutions of any rigorously defined field equation. **This code 
cannot verify FID's field-theoretic claims.**

## 3. Validation Roadmap

| Phase | Timeline | Goal |
|---|---|---|
| Phase 0 | 2026.05 | ✅ Publish this acknowledgment + v1.0 code |
| Phase 1 | 2026.06-08 | Run scaling law experiments at 10M-100M scale |
| Phase 2 | 2026.09-11 | Scale to 300M-1B with proper baselines |
| Phase 3 | 2026.12 | Energy measurement on real hardware |
| Phase 4 | 2027.01-03 | Invite independent reproduction |
| Phase 5 | 2027.04+ | Publish full results, update theory paper |

## 4. Falsification Criteria (Pre-Registered)

We commit to the following falsification thresholds. If any of 
these are not met after Phase 2, we will publicly acknowledge that 
the corresponding UID claim is **falsified**:

1. **Parameter efficiency**: Full CID's scaling curve must be 
   ≥3× to the left of the modern Transformer baseline at equal 
   loss, AND ≥1.5× to the left of "Transformer + all known tricks" 
   baseline.
2. **Critical exponents** (with noise injection OFF): Trained CID 
   models must exhibit β ∈ [0.7, 1.3] in ≥80% of layers and 
   τ ∈ [1.3, 1.7] estimated via Clauset MLE.
3. **Energy efficiency**: Measured Wh per token must be ≤1/3 of 
   the modern Transformer baseline at equal perplexity.

## 5. Acknowledgments

We thank the peer reviewers who identified these issues. Their 
feedback has made UID a stronger, more scientifically rigorous 
project. We particularly thank the anonymous reviewer who 
provided the detailed critique that motivated this v1.0 rewrite.

---

**Contact**: guilichina@163.com | lig@jodell.cn  
**License**: PolyForm Noncommercial 1.0.0 / Commercial License
