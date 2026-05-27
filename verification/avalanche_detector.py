# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-25
"""
Proper avalanche detection following Beggs & Plenz (2003).

This module FIXES the v0.1 implementation that measured 
|logits_a - logits_b| distribution (which is noise differences, 
NOT avalanches).

A neural avalanche is a SPATIO-TEMPORAL CASCADE of activations:
1. Define an activation threshold θ (typically 2σ above mean)
2. A "frame" has activity if ANY unit exceeds θ
3. An avalanche = sequence of consecutive active frames bracketed 
   by quiescent frames
4. Avalanche size = total number of supra-threshold events in the 
   avalanche
5. Avalanche duration = number of frames in the avalanche

Reference:
    Beggs, J. M., & Plenz, D. (2003). Neuronal avalanches in 
    neocortical circuits. J. Neurosci., 23(35), 11167-11177.
"""

from __future__ import annotations

import numpy as np


def detect_avalanches(
    hidden_states: np.ndarray,
    threshold_sigma: float = 2.0,
) -> np.ndarray:
    """
    Detect spatio-temporal avalanches in hidden-state activations.
    
    Args:
        hidden_states: Array of shape (n_sequences, seq_len, hidden_dim) 
            with activations from a trained model.
        threshold_sigma: Activation threshold in units of std above mean.
    
    Returns:
        Array of avalanche sizes (number of supra-threshold events 
        per avalanche).
    """
    n_seq, seq_len, hidden_dim = hidden_states.shape
    
    # Per-channel z-score normalization
    mean = hidden_states.mean(axis=(0, 1), keepdims=True)
    std = hidden_states.std(axis=(0, 1), keepdims=True) + 1e-8
    z = (hidden_states - mean) / std
    
    all_sizes = []
    
    for i in range(n_seq):
        seq = z[i]  # (seq_len, hidden_dim)
        # Per-frame activity: number of supra-threshold units
        activity = (np.abs(seq) > threshold_sigma).sum(axis=1)  # (seq_len,)
        
        # Detect avalanches: consecutive frames with activity > 0,
        # bracketed by quiescent frames (activity == 0)
        in_aval = False
        current_size = 0
        for a in activity:
            if a > 0:
                if not in_aval:
                    in_aval = True
                    current_size = 0
                current_size += int(a)
            else:
                if in_aval:
                    all_sizes.append(current_size)
                    in_aval = False
                    current_size = 0
        # Handle avalanche extending to end of sequence
        if in_aval and current_size > 0:
            all_sizes.append(current_size)
    
    return np.array(all_sizes, dtype=float)
