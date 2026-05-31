#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date:   2026-05-25
# UPDATE: 2026-05-28
"""Setup script for UID Theory implementation v2.1

完整的安装配置，解决所有模块导入问题。
"""

from setuptools import setup, find_packages
from pathlib import Path

# 读取 README
readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    try:
        long_description = readme_file.read_text(encoding="utf-8")
    except:
        pass

# 读取依赖
requirements_file = Path(__file__).parent / "requirements.txt"
install_requires = [
    "torch>=2.0.0",
    "transformers>=4.30.0",
    "numpy>=1.20.0",
    "tqdm>=4.60.0",
    "matplotlib>=3.3.0",
    "scipy>=1.7.0",
]

if requirements_file.exists():
    try:
        install_requires = [
            line.strip() 
            for line in requirements_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith('#')
        ]
    except:
        pass

setup(
    name="uid-theory",
    version="2.1.0",
    description="Unified Intelligo-Dynamics (UID) Theory Implementation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Gui LI",
    author_email="guilichina@163.com",
    url="https://github.com/gwailee/uid",
    license="PolyForm Noncommercial License 1.0.0",
    
    # 自动发现所有包（包括嵌套子包）
    # 这会找到 uid_theory, uid_theory.cid, uid_theory.qid 等
    packages=find_packages(include=[
        'uid_theory',
        'uid_theory.*',
        'model',
        'model.*',
        'experiments',
        'experiments.*',
        'tests',
        'tests.*',
    ]),
    
    # 包含根目录的独立模块文件
    # 这解决了 data_loaders.py 的导入问题
    py_modules=[
        'data_loaders',
        'convert_minimind_data',
        'convert_sft_conversations',
    ],
    
    # 包含数据文件
    package_data={
        '': ['*.md', '*.txt', '*.json', '*.yaml', '*.yml'],
    },
    
    # 包含非 Python 文件
    include_package_data=True,
    
    python_requires=">=3.8",
    
    install_requires=install_requires,
    
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "flake8>=4.0.0",
            "isort>=5.0.0",
        ],
        "energy": [
            "pynvml>=11.0.0",
        ],
        "all": [
            "pytest>=7.0.0",
            "pytest-cov>=3.0.0",
            "black>=22.0.0",
            "flake8>=4.0.0",
            "isort>=5.0.0",
            "pynvml>=11.0.0",
        ],
    },
    
    # 命令行入口点（可选，方便使用）
    entry_points={
        'console_scripts': [
            'uid-train=experiments.run_ablation:main',
            'uid-scaling=experiments.run_scaling_law:main',
        ],
    },
    
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Physics",
    ],
    
    keywords="deep-learning transformer uid physics non-equilibrium",
)
