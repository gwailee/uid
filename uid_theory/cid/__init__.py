# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
#
# This file is part of the UID Theory reference implementation.
#
# DUAL LICENSE:
#   - PolyForm Noncommercial License 1.0.0  (academic / personal use)
#     see LICENSE-NONCOMMERCIAL in the project root
#   - Commercial License from Suzhou Jodell Robotics Co., Ltd.
#     (required for any commercial / for-profit / production use)
#     see LICENSE-COMMERCIAL in the project root
#
# For commercial licensing inquiries, contact: lig@jodell.cn
# 本文件采用双许可证发布；商业使用须先获得苏州机器人有限公司书面授权，
# 商业授权联系: lig@jodell.cn

"""Classical Intelligo-Dynamics (CID) subpackage.

CID 子包：经典智动力学层与各物理项的独立模块。
"""

from .colored_noise import FastColoredNoise
from .vortex_field import VortexField
from .memory_kernel import MemoryKernel
from .hopfield_potential import HopfieldAttention
from .cid_layer import CIDLayer, CIDBlock

__all__ = [
    "FastColoredNoise",
    "VortexField",
    "MemoryKernel",
    "HopfieldAttention",
    "CIDLayer",
    "CIDBlock",
]
