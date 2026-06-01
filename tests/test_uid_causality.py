"""
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>

Causality Regression Test Suite for UID v2.1
=============================================

PURPOSE:
    Prevent future-token leakage bugs from recurring. This suite ensures that
    modifying a FUTURE token has ZERO influence on PAST token predictions in
    every UID branch (ET symmetric, standard attention, full CID).

METHODOLOGY:
    For each configuration:
      1. Generate a random input sequence  [t0, t1, ..., t_{n-1}]
      2. logits_1 = model(input)
      3. Perturb the LAST token:  input'[-1] = (input[-1] + 1) % vocab_size
      4. logits_2 = model(input')
      5. Assert  max | logits_1[0:-1] - logits_2[0:-1] | < 1e-5

    If this fails, the model uses future information to predict past tokens.

DESIGN NOTES:
    * Causality is a STRUCTURAL property, so all tests run in eval() mode with
      colored-noise OFF and dropout=0. Training-mode stochasticity (noise /
      dropout) is unrelated to causality and would only add nondeterministic
      noise to the measurement.
    * The "Transformer baseline" is modelled via UIDModel with
      use_et_symmetric=False and all physical terms OFF, so the suite does not
      depend on the concrete class name in modern_transformer.py.
    * Empty-tensor edge case (seq_len == 1) is handled: there is no "past"
      position to leak into, so the test only checks that the model runs.

USAGE:
    pytest tests/test_uid_causality.py -v
    pytest tests/test_uid_causality.py::test_et_branch_causal -v

EXPECTED:
    All tests PASS with max_influence < 1e-5 (numerical zero).
    Any failure indicates a causal-masking bug and MUST be fixed before merge.
"""

import pytest
import torch

from model.model_uid import UIDConfig, UIDModel


# Numerical-zero threshold for "no future-token influence".
CAUSAL_TOL: float = 1e-5


# ============================================================================
# Helper: Measure Future-Token Influence
# ============================================================================

def _max_future_influence(
    use_et: bool,
    use_vortex: bool = False,
    use_memory: bool = False,
    use_colored_noise: bool = False,
    vocab_size: int = 100,
    seq_len: int = 10,
    hidden_size: int = 64,
    num_layers: int = 2,
    num_heads: int = 4,
    seed: int = 0,
    batch_size: int = 1,
    enable_grad: bool = False,
) -> float:
    """Return the max influence of the LAST token on EARLIER positions.

    A correct causal model yields ~0 (< CAUSAL_TOL). Any positive value means
    future tokens leak into past predictions.

    Args:
        use_et:            Enable ET symmetric term (§8.5).
        use_vortex:        Enable vortex term (§14.2).
        use_memory:        Enable memory kernel (colored damping).
        use_colored_noise: Enable colored-noise injection. Kept OFF by default
                           because noise is only injected in train() mode and
                           is irrelevant to the structural causality property.
        vocab_size:        Vocabulary size for random tokens.
        seq_len:           Sequence length.
        hidden_size:       Model hidden dimension.
        num_layers:        Number of CID layers.
        num_heads:         Number of attention heads.
        seed:              RNG seed for reproducibility.
        batch_size:        Batch size (perturbs the last token of every row).
        enable_grad:       If True, build the autograd graph (still eval mode)
                           to verify graph construction adds no future deps.

    Returns:
        max_influence: max |logits_1[:, :-1] - logits_2[:, :-1]|, or 0.0 if
        seq_len == 1 (no past positions exist).
    """
    torch.manual_seed(seed)

    cfg = UIDConfig(
        vocab_size=vocab_size,
        hidden_size=hidden_size,
        num_hidden_layers=num_layers,
        num_attention_heads=num_heads,
        use_et_symmetric=use_et,
        use_vortex=use_vortex,
        use_memory=use_memory,
        use_colored_noise=use_colored_noise,
        dropout=0.0,  # deterministic
    )
    # eval() guarantees determinism: no dropout, and add_noise=self.training
    # means colored noise is NOT injected in eval mode.
    model = UIDModel(cfg).eval()

    x = torch.randint(0, vocab_size, (batch_size, seq_len))

    grad_ctx = torch.enable_grad() if enable_grad else torch.no_grad()
    with grad_ctx:
        logits_1 = model(x).logits

        x_perturbed = x.clone()
        x_perturbed[:, -1] = (x_perturbed[:, -1] + 1) % vocab_size
        logits_2 = model(x_perturbed).logits

    # Compare EARLIER positions only (0 .. seq_len-2).
    diff = (logits_1[:, :-1] - logits_2[:, :-1]).abs()
    if enable_grad:
        diff = diff.detach()

    # seq_len == 1 -> diff is empty; no past positions to leak into.
    if diff.numel() == 0:
        return 0.0
    return diff.max().item()


# ============================================================================
# Test Suite: Core Causality Checks
# ============================================================================

def test_et_branch_causal():
    """ET symmetric branch (§8.5) must not leak future tokens.

    CRITICAL: this is the branch that exercises the dual-term update. It must
    use [query, key] layout + causal mask so that output position t depends
    only on inputs <= t.
    """
    max_inf = _max_future_influence(use_et=True)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future tokens! max_influence={max_inf:.2e}. "
        f"Check hopfield_potential.py::_forward_et() causal mask & layout."
    )


def test_standard_branch_causal():
    """Standard attention branch must not leak future tokens."""
    max_inf = _max_future_influence(use_et=False)
    assert max_inf < CAUSAL_TOL, (
        f"Standard branch leaks future tokens! max_influence={max_inf:.2e}. "
        f"Check hopfield_potential.py::_forward_standard() causal mask."
    )


def test_full_cid_causal():
    """Full CID (ET + vortex + memory + noise-capable) must not leak future.

    Note: noise is OFF here because eval() does not inject it; this isolates
    the structural causality of ET + vortex + memory.
    """
    max_inf = _max_future_influence(
        use_et=True, use_vortex=True, use_memory=True, use_colored_noise=True,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Full CID leaks future tokens! max_influence={max_inf:.2e}. "
        f"Check cid_layer.py::forward() for causal violations in any term."
    )


def test_cid_no_et_causal():
    """CID without ET (standard attn + vortex + memory + noise) must be causal.

    This is the `cid_full_no_et` ablation variant (Phase 1 best performer).
    """
    max_inf = _max_future_influence(
        use_et=False, use_vortex=True, use_memory=True, use_colored_noise=True,
    )
    assert max_inf < CAUSAL_TOL, (
        f"CID (no ET) leaks future tokens! max_influence={max_inf:.2e}. "
        f"Check vortex/memory terms respect causality."
    )


def test_transformer_equivalent_causal():
    """Transformer-equivalent (standard attn, no UID terms) must be causal.

    Modelled via UIDModel with use_et_symmetric=False and all physical terms
    OFF, so the suite does not depend on modern_transformer.py's class names.
    """
    max_inf = _max_future_influence(
        use_et=False, use_vortex=False, use_memory=False, use_colored_noise=False,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Transformer-equivalent leaks future tokens! "
        f"max_influence={max_inf:.2e}."
    )


# ============================================================================
# Test Suite: Multi-Seed Robustness
# ============================================================================

@pytest.mark.parametrize("seed", [0, 42, 123, 456, 789])
def test_et_causal_multi_seed(seed):
    """ET branch causality must hold across random seeds."""
    max_inf = _max_future_influence(use_et=True, seed=seed)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future tokens at seed={seed}! "
        f"max_influence={max_inf:.2e}"
    )


@pytest.mark.parametrize("seed", [0, 42, 123, 456, 789])
def test_full_cid_causal_multi_seed(seed):
    """Full CID causality must hold across random seeds."""
    max_inf = _max_future_influence(
        use_et=True, use_vortex=True, use_memory=True,
        use_colored_noise=True, seed=seed,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Full CID leaks future tokens at seed={seed}! "
        f"max_influence={max_inf:.2e}"
    )


# ============================================================================
# Test Suite: Varying Sequence Lengths
# ============================================================================

@pytest.mark.parametrize("seq_len", [4, 8, 16, 32, 64])
def test_et_causal_varying_length(seq_len):
    """ET branch causality must hold for different sequence lengths."""
    max_inf = _max_future_influence(use_et=True, seq_len=seq_len)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future tokens at seq_len={seq_len}! "
        f"max_influence={max_inf:.2e}"
    )


@pytest.mark.parametrize("seq_len", [4, 8, 16, 32, 64])
def test_full_cid_causal_varying_length(seq_len):
    """Full CID causality must hold for different sequence lengths."""
    max_inf = _max_future_influence(
        use_et=True, use_vortex=True, use_memory=True,
        use_colored_noise=True, seq_len=seq_len,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Full CID leaks future tokens at seq_len={seq_len}! "
        f"max_influence={max_inf:.2e}"
    )


# ============================================================================
# Test Suite: Label Alignment (No Double-Shift)
# ============================================================================

def test_label_no_double_shift():
    """model_uid.py must NOT double-shift labels.

    data_loaders.py already shifts: labels[i] = input_ids[i+1]. The loss in
    model_uid.py must be cross_entropy(logits, labels) WITHOUT a second shift
    (no labels[..., 1:]). This is a regression guard against double-shift.
    """
    torch.manual_seed(0)
    cfg = UIDConfig(
        vocab_size=50, hidden_size=32, num_hidden_layers=1,
        num_attention_heads=4, use_et_symmetric=True,
        use_vortex=False, use_memory=False, use_colored_noise=False,
        dropout=0.0,
    )
    model = UIDModel(cfg).eval()

    # Labels already left-shifted by data_loaders:
    #   input:  [1, 2, 3, 4, 5]
    #   labels: [2, 3, 4, 5, -100]
    input_ids = torch.tensor([[1, 2, 3, 4, 5]])
    labels = torch.tensor([[2, 3, 4, 5, -100]])

    with torch.no_grad():
        out = model(input_ids=input_ids, labels=labels)

    assert out.loss is not None, "Model returned no loss with labels provided."
    assert torch.isfinite(out.loss), f"Loss not finite: {out.loss.item()}"
    assert out.loss.item() > 0, f"Loss is zero/negative: {out.loss.item()}"

    # Manual cross-entropy WITHOUT extra shift must match the model's loss.
    logits_flat = out.logits.view(-1, cfg.vocab_size)
    labels_flat = labels.view(-1)
    loss_manual = torch.nn.functional.cross_entropy(
        logits_flat, labels_flat, ignore_index=-100, reduction="mean",
    )
    assert torch.allclose(out.loss, loss_manual, atol=1e-5), (
        f"Model loss {out.loss.item():.6f} != manual {loss_manual.item():.6f}. "
        f"Possible double-shift bug in model_uid.py loss computation!"
    )


def test_label_alignment_with_padding():
    """Label alignment must hold with padded positions (-100)."""
    torch.manual_seed(42)
    cfg = UIDConfig(
        vocab_size=50, hidden_size=32, num_hidden_layers=1,
        num_attention_heads=4, use_et_symmetric=False,
        dropout=0.0,
    )
    model = UIDModel(cfg).eval()

    # input:  [1, 2, 3, 0, 0]
    # labels: [2, 3, -100, -100, -100]
    input_ids = torch.tensor([[1, 2, 3, 0, 0]])
    labels = torch.tensor([[2, 3, -100, -100, -100]])

    with torch.no_grad():
        out = model(input_ids=input_ids, labels=labels)

    assert out.loss is not None
    assert torch.isfinite(out.loss)
    assert out.loss.item() > 0

    logits_flat = out.logits.view(-1, cfg.vocab_size)
    labels_flat = labels.view(-1)
    loss_manual = torch.nn.functional.cross_entropy(
        logits_flat, labels_flat, ignore_index=-100, reduction="mean",
    )
    assert torch.allclose(out.loss, loss_manual, atol=1e-5), (
        f"Loss mismatch with padding: model={out.loss.item():.6f}, "
        f"manual={loss_manual.item():.6f}"
    )


# ============================================================================
# Test Suite: Batch Causality
# ============================================================================

def test_et_causal_batch():
    """ET branch causality must hold in batch mode (multiple sequences)."""
    max_inf = _max_future_influence(use_et=True, batch_size=4, seq_len=10)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future tokens in batch mode! "
        f"max_influence={max_inf:.2e}"
    )


def test_full_cid_causal_batch():
    """Full CID causality must hold in batch mode."""
    max_inf = _max_future_influence(
        use_et=True, use_vortex=True, use_memory=True,
        use_colored_noise=True, batch_size=4, seq_len=10,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Full CID leaks future tokens in batch mode! "
        f"max_influence={max_inf:.2e}"
    )


# ============================================================================
# Test Suite: Gradient Graph (eval mode, grad enabled)
# ============================================================================

def test_et_causal_with_gradients():
    """ET branch causality must hold when the autograd graph is built.

    Run in eval() mode (no noise/dropout) but with grad enabled, to verify
    that autograd-graph construction introduces no future-token dependency.
    Training-mode stochasticity is intentionally excluded — it is unrelated
    to the structural causality property and would only add nondeterminism.
    """
    max_inf = _max_future_influence(use_et=True, enable_grad=True)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future tokens with grad enabled! "
        f"max_influence={max_inf:.2e}"
    )


def test_full_cid_causal_with_gradients():
    """Full CID causality must hold when the autograd graph is built."""
    max_inf = _max_future_influence(
        use_et=True, use_vortex=True, use_memory=True,
        use_colored_noise=True, enable_grad=True,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Full CID leaks future tokens with grad enabled! "
        f"max_influence={max_inf:.2e}"
    )


# ============================================================================
# Test Suite: Edge Cases
# ============================================================================

def test_causality_single_token_sequence():
    """seq_len == 1: no past positions exist; model must just run cleanly."""
    torch.manual_seed(0)
    cfg = UIDConfig(
        vocab_size=100, hidden_size=64, num_hidden_layers=2,
        num_attention_heads=4, use_et_symmetric=True,
        use_vortex=False, use_memory=False, use_colored_noise=False,
        dropout=0.0,
    )
    model = UIDModel(cfg).eval()

    x = torch.randint(0, 100, (1, 1))
    with torch.no_grad():
        logits = model(x).logits

    assert logits.shape == (1, 1, 100), (
        f"Single-token output shape wrong: {logits.shape}"
    )
    # No past position -> causality trivially satisfied.
    assert _max_future_influence(use_et=True, seq_len=1) == 0.0


def test_causality_two_token_sequence():
    """seq_len == 2: perturbing token[1] must not affect logits[0]."""
    max_inf = _max_future_influence(use_et=True, seq_len=2)
    assert max_inf < CAUSAL_TOL, (
        f"ET branch leaks future token in 2-token sequence! "
        f"max_influence={max_inf:.2e}"
    )


# ============================================================================
# Test Suite: Component Isolation
# ============================================================================

def test_vortex_alone_causal():
    """Vortex term alone must be causal."""
    max_inf = _max_future_influence(
        use_et=False, use_vortex=True, use_memory=False, use_colored_noise=False,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Vortex term leaks future tokens! max_influence={max_inf:.2e}"
    )


def test_memory_alone_causal():
    """Memory kernel alone must be causal (looks backward by construction)."""
    max_inf = _max_future_influence(
        use_et=False, use_vortex=False, use_memory=True, use_colored_noise=False,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Memory kernel leaks future tokens! max_influence={max_inf:.2e}"
    )


def test_noise_alone_causal():
    """Colored-noise-capable config must be causal in eval mode.

    Noise is per-position and only injected in train() mode; in eval() it is
    off, so this verifies the noise-enabled config has no structural leak.
    """
    max_inf = _max_future_influence(
        use_et=False, use_vortex=False, use_memory=False, use_colored_noise=True,
    )
    assert max_inf < CAUSAL_TOL, (
        f"Colored-noise config leaks future tokens! max_influence={max_inf:.2e}"
    )


# ============================================================================
# Optional sanity check: eval-mode determinism
# ============================================================================

def test_eval_mode_is_deterministic():
    """Two identical forward passes in eval() must be bit-identical.

    This guards the whole suite: if eval() were nondeterministic, every
    causality measurement above would be polluted. (Also explains why the
    causality tests deliberately avoid train() mode.)
    """
    torch.manual_seed(0)
    cfg = UIDConfig(
        vocab_size=100, hidden_size=64, num_hidden_layers=2,
        num_attention_heads=4, use_et_symmetric=True,
        use_vortex=True, use_memory=True, use_colored_noise=True,
        dropout=0.0,
    )
    model = UIDModel(cfg).eval()
    x = torch.randint(0, 100, (1, 10))
    with torch.no_grad():
        a = model(x).logits
        b = model(x).logits
    diff = (a - b).abs().max().item()
    assert diff < 1e-6, (
        f"eval() mode is nondeterministic (diff={diff:.2e}); causality tests "
        f"would be unreliable. Ensure noise is gated by self.training."
    )


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
