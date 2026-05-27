# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
UID verification suite v2.0.

This version was rewritten in response to detailed peer review feedback. 
See KNOWN_LIMITATIONS.md for the complete acknowledgment of v0.1 issues 
and how each is addressed in v2.0.

Key modules:
    powerlaw_estimator: Clauset-Shalizi-Newman MLE for power-law fitting
    critical_exponents: Measure emergent signatures with noise-injection OFF
    avalanche_detector: Proper spatio-temporal avalanche detection
    energy_meter: Real hardware energy measurement (not theoretical)
    ablation_suite: Full 5+ way ablation (includes cid_no_memory)
"""

from .powerlaw_estimator import (
    PowerLawFit, fit_power_law, compare_with_exponential,
)

__all__ = [
    "PowerLawFit",
    "fit_power_law",
    "compare_with_exponential",
]
