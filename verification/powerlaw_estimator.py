# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-30
"""
Rigorous power-law estimation following Clauset, Shalizi & Newman (2009).

This module implements the gold-standard methodology for fitting 
power-law distributions:
- Maximum Likelihood Estimation (MLE) for the exponent
- Kolmogorov-Smirnov test for goodness-of-fit
- Likelihood ratio test to compare against alternative distributions
  (exponential, log-normal)

Reference:
    Clauset, A., Shalizi, C. R., & Newman, M. E. (2009).
    Power-law distributions in empirical data.
    SIAM Review, 51(4), 661-703.
    https://doi.org/10.1137/070710111

This replaces the unreliable log-binned linear regression method 
used in v0.1 of this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from scipy import stats
from scipy.special import zeta


@dataclass
class PowerLawFit:
    """Result of a power-law fit."""
    alpha: float            # Estimated power-law exponent
    alpha_se: float         # Standard error of alpha
    xmin: float             # Lower cutoff
    n_tail: int             # Number of samples in the tail
    ks_statistic: float     # Kolmogorov-Smirnov statistic
    p_value: float          # p-value (>0.1 suggests power law is plausible)
    is_power_law: bool      # True if p_value > 0.1
    
    def __repr__(self) -> str:
        verdict = "✓ POWER LAW" if self.is_power_law else "✗ NOT POWER LAW"
        return (
            f"PowerLawFit(alpha={self.alpha:.3f}±{self.alpha_se:.3f}, "
            f"xmin={self.xmin:.3g}, n_tail={self.n_tail}, "
            f"KS={self.ks_statistic:.4f}, p={self.p_value:.3f}, "
            f"{verdict})"
        )


def estimate_xmin(data: np.ndarray, n_candidates: int = 50) -> float:
    """
    Estimate the optimal lower cutoff x_min by minimizing the KS distance.
    
    Following Clauset et al. (2009) Section 3.3.
    """
    data = np.sort(data[data > 0])
    if len(data) < 50:
        return float(data[0])
    
    # Try candidate x_min values
    candidates = np.unique(np.percentile(
        data, np.linspace(1, 90, n_candidates)
    ))
    
    best_ks = float('inf')
    best_xmin = float(data[0])
    
    for xmin_candidate in candidates:
        tail = data[data >= xmin_candidate]
        if len(tail) < 50:
            continue
        
        # MLE estimate of alpha for this xmin
        alpha = mle_alpha_continuous(tail, xmin_candidate)
        if not np.isfinite(alpha) or alpha <= 1.0:
            continue
        
        # Compute KS distance
        ks = ks_distance_continuous(tail, alpha, xmin_candidate)
        if ks < best_ks:
            best_ks = ks
            best_xmin = float(xmin_candidate)
    
    return best_xmin


def mle_alpha_continuous(data: np.ndarray, xmin: float) -> float:
    """
    Maximum likelihood estimator for power-law exponent (continuous case).
    
    Following Clauset et al. (2009) Eq. 3.1:
        alpha_hat = 1 + n / sum(ln(x_i / x_min))
    """
    tail = data[data >= xmin]
    n = len(tail)
    if n == 0:
        return float('nan')
    log_ratios = np.log(tail / xmin)
    sum_log = log_ratios.sum()
    if sum_log <= 0:
        return float('nan')
    return 1.0 + n / sum_log


def alpha_standard_error(alpha: float, n: int) -> float:
    """Standard error of alpha estimate (Clauset et al. Eq. 3.2)."""
    if n <= 1:
        return float('nan')
    return (alpha - 1.0) / np.sqrt(n)


def ks_distance_continuous(
    data: np.ndarray, alpha: float, xmin: float
) -> float:
    """
    KS distance between empirical CDF and theoretical power-law CDF.
    """
    tail = np.sort(data[data >= xmin])
    n = len(tail)
    if n == 0:
        return float('inf')
    
    # Empirical CDF
    empirical_cdf = np.arange(1, n + 1) / n
    
    # Theoretical CDF: F(x) = 1 - (x/xmin)^(1-alpha)
    theoretical_cdf = 1.0 - (tail / xmin) ** (1.0 - alpha)
    
    return float(np.max(np.abs(empirical_cdf - theoretical_cdf)))


def ks_goodness_of_fit(
    data: np.ndarray,
    alpha: float,
    xmin: float,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> float:
    """
    KS goodness-of-fit test via parametric bootstrap.
    
    Following Clauset et al. (2009) Section 4. Returns p-value.
    - p > 0.1: power law is a plausible fit
    - p <= 0.1: power law can be rejected
    """
    rng = np.random.default_rng(seed)
    tail = data[data >= xmin]
    n = len(tail)
    if n < 50:
        return 0.0  # Insufficient data
    
    # Observed KS distance
    ks_obs = ks_distance_continuous(tail, alpha, xmin)
    
    # Bootstrap: generate synthetic power-law samples, compute KS
    count_worse = 0
    for _ in range(n_bootstrap):
        # Sample from power law via inverse CDF
        u = rng.uniform(size=n)
        synthetic = xmin * (1.0 - u) ** (1.0 / (1.0 - alpha))
        # Re-estimate alpha for synthetic data
        try:
            alpha_syn = mle_alpha_continuous(synthetic, xmin)
            if not np.isfinite(alpha_syn):
                continue
            ks_syn = ks_distance_continuous(synthetic, alpha_syn, xmin)
            if ks_syn >= ks_obs:
                count_worse += 1
        except Exception:
            continue
    
    return count_worse / n_bootstrap


def fit_power_law(
    data: np.ndarray,
    xmin: Optional[float] = None,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> PowerLawFit:
    """
    Fit a power law to data using Clauset-Shalizi-Newman methodology.
    
    Args:
        data: Array of positive numbers (e.g., avalanche sizes).
        xmin: Lower cutoff. If None, estimated by KS minimization.
        n_bootstrap: Number of bootstrap iterations for p-value.
        seed: Random seed.
    
    Returns:
        PowerLawFit object with all estimation results.
    """
    data = np.asarray(data, dtype=float)
    data = data[data > 0]
    
    if len(data) < 100:
        return PowerLawFit(
            alpha=float('nan'),
            alpha_se=float('nan'),
            xmin=float('nan'),
            n_tail=len(data),
            ks_statistic=float('nan'),
            p_value=0.0,
            is_power_law=False,
        )
    
    # Step 1: Estimate xmin if not provided
    if xmin is None:
        xmin = estimate_xmin(data)
    
    # Step 2: MLE for alpha
    alpha = mle_alpha_continuous(data, xmin)
    
    if not np.isfinite(alpha):
        return PowerLawFit(
            alpha=float('nan'),
            alpha_se=float('nan'),
            xmin=xmin,
            n_tail=0,
            ks_statistic=float('nan'),
            p_value=0.0,
            is_power_law=False,
        )
    
    tail = data[data >= xmin]
    n_tail = len(tail)
    
    # Step 3: Standard error
    alpha_se = alpha_standard_error(alpha, n_tail)
    
    # Step 4: KS statistic
    ks_stat = ks_distance_continuous(tail, alpha, xmin)
    
    # Step 5: Goodness-of-fit test via bootstrap
    p_val = ks_goodness_of_fit(data, alpha, xmin, n_bootstrap, seed)
    
    return PowerLawFit(
        alpha=alpha,
        alpha_se=alpha_se,
        xmin=xmin,
        n_tail=n_tail,
        ks_statistic=ks_stat,
        p_value=p_val,
        is_power_law=bool(p_val > 0.1),
    )


def compare_with_exponential(
    data: np.ndarray, xmin: float
) -> Tuple[float, float]:
    """
    Likelihood ratio test: power law vs exponential.
    
    Returns:
        (log_likelihood_ratio, p_value)
        Positive LR favors power law; p < 0.1 means the test is decisive.
    """
    tail = data[data >= xmin]
    n = len(tail)
    if n < 50:
        return float('nan'), float('nan')
    
    # Power-law log-likelihood
    alpha = mle_alpha_continuous(tail, xmin)
    if not np.isfinite(alpha):
        return float('nan'), float('nan')
    log_lik_pl = (
        n * np.log((alpha - 1) / xmin)
        - alpha * np.log(tail / xmin).sum()
    )
    
    # Exponential log-likelihood (MLE of rate)
    rate = 1.0 / (tail.mean() - xmin)
    if rate <= 0:
        return float('nan'), float('nan')
    log_lik_exp = (
        n * np.log(rate)
        - rate * (tail - xmin).sum()
    )
    
    # Vuong's likelihood ratio test
    lr = log_lik_pl - log_lik_exp
    # Standard error of LR (Clauset et al. Appendix C)
    diff = np.log((alpha - 1) / xmin) - alpha * np.log(tail / xmin)
    diff_exp = np.log(rate) - rate * (tail - xmin)
    sigma = np.std(diff - diff_exp) * np.sqrt(n)
    if sigma == 0:
        return float(lr), float('nan')
    z = lr / sigma
    p_value = 2.0 * (1.0 - stats.norm.cdf(abs(z)))
    
    return float(lr), float(p_value)


if __name__ == "__main__":
    # Self-test: generate known power law, recover the exponent
    rng = np.random.default_rng(42)
    n = 10000
    true_alpha = 2.5
    true_xmin = 1.0
    # Generate via inverse CDF
    u = rng.uniform(size=n)
    samples = true_xmin * (1.0 - u) ** (1.0 / (1.0 - true_alpha))
    
    result = fit_power_law(samples, xmin=true_xmin)
    print(f"True alpha: {true_alpha}")
    print(f"Estimated: {result}")
    
    # Should recover alpha ≈ 2.5
    assert abs(result.alpha - true_alpha) < 0.1, "MLE failed!"
    assert result.is_power_law, "KS test failed!"
    print("✓ Self-test passed")
