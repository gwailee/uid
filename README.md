<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-30
UPDATE: 2026-05-28 (v2.1 全量整合)
  * 三层架构 (CID/QID/FID) 全部完成 v2.1 修正:
      - HopfieldAttention 实现 §8.5 ET 对称双项 (Lyapunov 保证)
      - VortexField 改为 FFN 反对称投影 (§14.2 零额外参数)
      - 色噪声默认改为 OU 物理 SDE (§14.2; FFT 保留为 legacy)
      - QID/FID 同步透传上述 v2.1 关键参数到 CIDLayer
      - FID info 字典 JSON 安全 (LOSS_PREFIX 分离 autograd 张量)
      - FID 新增 §6.1 η 与 §6.2 Ricci 标量代理
  * 顶层 API 全面暴露:
      - UIDModel.set_noise_injection / set_energy_monitoring
      - QIDLayer / FIDLayer 同样暴露顶层开关
      - 新增 fluctuation_dissipation_consistency 诊断
  * 实验脚本流水线打通:
      - run_scaling_law.py 保存统一 v2.1 checkpoint schema
      - run_all.py 修复 checkpoint 路径裂缝
      - run_critical_exponents.py 增加 η verdict 与三态分类
        (pass / fail / abstain_rd / abstain_missing)
      - run_ablation.py 报告 11 组消融的 3 个关键对照
      - run_energy_benchmark.py 升级到 energy_meter v2.1 batch 4
        (idle 基线 + above-idle 字段 + prefill/decode 模式)
  * 验证套件升级:
      - measure_fisher_anisotropy_eta() 让 §6.1 预言 4 真正可测
      - energy_meter v2.1: pynvml 高频采样 + above-idle 报告
      - prediction_test.py 改为 deprecated wrapper, 路由到新工具链
  * 数据加载脚本规范化:
      - test_uid_on_minimind.py -> data_loaders.py 重命名
      - 提供 PretrainJsonl + SftJsonl 双数据集
      - SFT 截断保留 prompt 尾部 (instruction-tuning 公认惯例)
  * 测试套件覆盖全栈:
      - tests/test_et_lyapunov.py        (§8.5 ET 单调下降)
      - tests/test_run_scaling_law.py    (v2.1 参数透传)
      - tests/test_qid_layer.py          (QID v2.1 + 零参数)
      - tests/test_fid_layer.py          (FID 三级透传 + JSON 安全)
      - tests/test_critical_exponents.py (新增 η 回归 + 集成)
      - tests/test_energy_meter.py       (能量积分 + 平台兼容)
      - tests/test_data_loaders.py       (含 SFT tail 截断)

This README is part of the UID Theory reference implementation (v2.1).

DUAL LICENSE:
  - PolyForm Noncommercial License 1.0.0  (free for academic / personal use)
    see LICENSE-NONCOMMERCIAL in the project root
  - Commercial License from Suzhou Jodell Robotics Co., Ltd.
    (required for any commercial / for-profit / production use)
    see LICENSE-COMMERCIAL in the project root

For commercial licensing inquiries, contact: lig@jodell.cn
本文件采用双许可证发布；商业使用须先获得苏州钧舵机器人有限公司书面授权。
-->

<div align="center">

![logo](./images/logo.png)

</div>

<div align="center">
<a href="./README.md"><b>README（中文）</b></a> | <a href="./README_en.md">README（English）</a>
</div>

<div align="center">
<a href="./30minutes_report.md">30 分钟读懂 UID 理论（中文）</a> | <a href="./30minutes_report_en.md">Understand UID in 30 Minutes（English）</a>
</div>

<div align="center">
<a href="./theory.md">UID 理论全文（中文）</a> | <a href="./theory_en.md">UID Theory (English)</a>
</div>

<br>

<div align="center">

# 智能是一个非平衡场：统一智动力学（UID）的三层物理理论
## ——注意力并不够：智能架构的非平衡物理基础

[CI](https://github.com/gwailee/uid/actions/workflows/ci.yml) | [DOI](https://doi.org/10.5281/zenodo.20372493) | [License: PolyForm Noncommercial](LICENSE)


***作者***：李贵 <guilichina@163.com>、介党阳 <jiedy@jodell.cn>、康海涛 <kanght@jodell.cn>

***单位***：苏州钧舵机器人有限公司（Suzhou Jodell Robotics Co., Ltd.），苏州，中国

</div>

***通讯作者***：李贵（Gui LI），博士。学士毕业于西北大学物理学院，硕士、博士均毕业于中国科学院合肥物质科学研究院，现任职于苏州钧舵机器人有限公司，主要从事**统一智动力学（Unified Intelligo-Dynamics, UID）**的理论与工程研究。提出并发展面向智能架构的开放系统物理统一理论框架——CID/QID/FID 三层体系，并主导其在机器人认知大脑、运动控制小脑、灵巧手操作系统、大语言模型与专用智能芯片中的可证伪验证与工程落地。E-mail：guilichina@163.com

---

## ⚠️ 重要提示：v2.1 诚实版本说明

**本仓库当前为 v2.1（诚实验证版 + 理论 §8.5 / §14.2 修正版）**，是基于详细同行评审反馈对 v0.1 的完整重写，并在 v2.0 基础上**完成了三处与理论文档不符的实现缺陷的修正、以及一整套基础设施升级**：

| v2.1 关键修正 | 对应理论章节 |
|---|---|
| `HopfieldAttention` 实现 **ET 对称双项更新**（享 Lyapunov 单调下降保证）| §8.5 |
| `VortexField` 改为**从 FFN 第一层权重反对称投影**构造，零额外矩阵参数 | §14.2 |
| 色噪声默认改为 **Ornstein-Uhlenbeck 物理 SDE**（FFT 版本保留为 legacy）| §14.2 |
| `FIDLayer` 把 §6.1 各向异性 η 与 §6.2 Ricci 标量代理直接报告到 info | §6.1 / §6.2 |
| QID / FID 三级透传 v2.1 关键参数 + 顶层 API 透出 | 接口一致性 |
| `run_critical_exponents.py` verdict 表加入 η 行 + 三态判定 | §6.1 |
| `energy_meter.py` 升级到 v2.1：idle 基线 + above-idle 字段 + prefill/decode 模式 | §0.1 / §11.4 |

v0.1 版本的验证套件存在方法学缺陷，使其"已验证"声明在科学上站不住脚。详情见 [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)。**v0.1 与 v2.0 的任何实证主张都应在 v2.1 下重跑后才可引用**。

v2.1 版本：
- ✅ 提供了进行严格验证所需的**完整基础设施**（含 7 个新测试文件全栈覆盖）
- ✅ 完成了理论 §8.5 ET 修正、§14.2 零参数旋度、§14.2 OU 噪声、§6.1 η 直接可测等所有承诺
- ⏳ 大规模验证实验**尚未完成**
- 🎯 承诺**公开发布所有结果**（无论正面还是负面）

**证伪一个理论与证实它同等有价值**——这是科学进步的根本原则。

---

## 📋 项目概述

本项目实现并验证 **UID 三层理论**：

| 层级 | 全称 | 状态 |
|---|---|---|
| **CID** | Classical Intelligo-Dynamics（经典智动力学）| ✅ 可严格工程化（含 ET 对称项 + 零参数旋度 + OU 噪声），待大规模实验验证 |
| **QID** | Quantum Intelligo-Dynamics（量子智动力学）| ⚠ 经典模拟实现（零参数模式默认 + 量子 OU 噪声），真实量子优势待量子硬件 |
| **FID** | Field Intelligo-Dynamics（场智动力学）| 🔬 诊断性几何探针（直接报告 η / Ricci 标量），待经验校准 |

理论的核心工程论断：

> **基于 CID 主方程构建的模型架构，可以在参数量、能耗或两者方面显著优于标准 Transformer。**

这是本仓库要严格检验的**可证伪假设**。

---

## 🎯 核心可证伪预言

| # | 预言量 | 理论值 | 状态 |
|---|---|---|---|
| 1 | 雪崩规模指数 τ | 1.5 ± 0.2 | (A) 已在皮层数据独立实证 |
| 2 | Hurst 指数 H | 0.6 – 0.8 | (A) 已在人脑 EEG 独立实证 |
| 3 | 1/f 谱斜率 β | 0.7 – 1.3 | (A) 已在多项研究验证 |
| 4 | Fisher 度量各向异性 η | > 0.5（训练后）| (A) Karakida 等 2019 在 DNN 中实证 ≈ 0.7-0.9；UID 端可由 `measure_fisher_anisotropy_eta()` 直接测量 |
| 5 | 参数效率 vs Transformer | ≥ 3×（终期 ≥ 5×）| (C) 待 Phase 1 验证 |
| 6 | 推理能效改进 | ≥ 3×（above-idle）| (C) 待 Phase 1 验证（由 v2.1 `energy_meter.py` 实测）|
| 7 | 关闭噪声注入后的临界涌现 | β 与 H 仍在区间内 | (C) 待 Phase 1 验证 |
| 8 | ET 能量函数前向单调下降（§8.5）| dE/dt ≤ 0 | (C) 由 `tests/test_et_lyapunov.py` 单元测试覆盖 |

**等级说明**：
- (A) 已在外部独立体系（生物大脑 / 已发表 DNN 研究）实证
- (B) 理论严格但实证待补
- (C) 明确的可证伪工程目标

> 任何**显著偏离**这些区间的实测结果都构成对 UID 理论的反驳证据 —— 这正是科学的核心。

---

## 🆕 v2.1 相对 v2.0 的关键改进

| 模块 | v2.0 状态 | v2.1 修复 |
|---|---|---|
| **`HopfieldAttention`** | 标准缩放点积注意力，与论文 §8.5 自承不符 | 完整实现 ET 对称双项更新，享 Lyapunov 能量单调下降保证；新增 `compute_energy()` 工具方法 |
| **`VortexField`** | 引入两个独立 H×H 矩阵 W₁、W₂（破坏 §14.2 零参数承诺）| 改为从 FFN 第一层权重的反对称分量 J = (W − W^T)/2 构造，每层仅 +1 个标量参数 |
| **色噪声默认** | FFT 频域整形（存在循环测量风险）| 默认改为 OU 物理 SDE（FFT 仍可通过 `noise_type="fft"` 使用）|
| **QID 层参数预算** | 默认引入 5×H² 额外参数（违反零参数原则）| 默认 hamiltonian_mode='shared_with_ffn' + lindblad_mode='off'，仅 +几个标量；提供 `count_extras()` 诊断 |
| **FID 层 `info` 字典** | `curvature_loss` 是带梯度 Tensor，导致 JSON 序列化崩溃 | 引入 LOSS_PREFIX 分离机制 + `extract_loss_tensors()` 辅助函数；info 字典严格 JSON 安全 |
| **FID 层曲率代理** | 仅报告 `trace(g²)/trace(g)²` 与 §6.1 预言对接弱 | 新增 `compute_anisotropy_eta()`（§6.1 直接对接）+ `compute_ricci_scalar_surrogate()`（§6.2 直接对接），同时保留 legacy 字段 |
| **顶层 API** | 需通过 `model.backbone.xxx` 调用开关 | `UIDModel` / `QIDLayer` / `FIDLayer` 直接暴露 `set_noise_injection` / `set_energy_monitoring` / `set_temperature` / `fluctuation_dissipation_consistency` |
| **基线对照** | `transformer_plus_linear` 中的 VortexField 静默退化为 0，破坏关键证伪对照 | baseline 也接受 FFN 权重引用，对照真实有效 |
| **`UIDConfig`** | 缺 `noise_type` / `noise_tau` / `use_et_symmetric` 字段，HF 序列化丢配置 | 三字段已纳入 config，HF 序列化往返一致 |
| **消融变体数** | 9 组 | **11 组**（新增 `cid_full_no_et` 与 `cid_full_fft_noise`，分别隔离 §8.5 与 §14.2 修正的工程贡献）|
| **临界指数 verdict** | 仅基于 noise-OFF 单点判定 | 对比 noise-OFF vs noise-ON；新增"残留回响"警告；η 直接参与 verdict（三态：pass/fail/abstain_rank_deficient）|
| **能耗测量** | 仅报告平均功率 / 总能量 / 每 token 能耗 | 新增 idle 基线、above-idle 功率、above-idle 能量、above-idle 每 token 能耗；区分 prefill / decode 模式；pynvml 高频采样默认 25 Hz |
| **Checkpoint 流水线** | `run_scaling_law.py` 不写 checkpoint，导致下游脚本静默跳过 | 统一 v2.1 schema（`{family}_{scale}_seed{seed}.pt`）+ `run_all.py` checkpoint 路径搜索修复 |
| **数据加载脚本** | `test_uid_on_minimind.py`（名字带 `test_` 易被误收集）| 重命名为 `data_loaders.py`；新增 `SftJsonl`；截断保留 prompt 尾部 |
| **`prediction_test.py`** | v0.1 残留（循环测量 + 错误避雪崩协议）| 改写为 deprecated wrapper，自动路由到 v2.0+ 工具链 |
| **测试覆盖** | 5 个 ad-hoc 测试 | **7 个 v2.1 测试文件，约 200+ 测试用例**，覆盖三层架构全部修正点 |

完整对比见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 📁 项目结构

```
uid/
├── README.md                          本文件
├── README_en.md                       英文版 README
├── KNOWN_LIMITATIONS.md               v0.1 / v2.0 缺陷的诚实声明
├── ROADMAP.md                         验证路线图（含预注册证伪条件）
├── CHANGELOG.md                       v0.1 → v2.1 完整变更
├── LICENSE / LICENSE-NONCOMMERCIAL / LICENSE-COMMERCIAL
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── data_loaders.py                    数据加载工具（PretrainJsonl + SftJsonl）
│
├── uid_theory/                        UID 理论核心实现
│   ├── cid/                           经典智动力学
│   │   ├── cid_layer.py               v2.1: noise_type=ou 默认, ET 开关, FDT 诊断
│   │   ├── colored_noise.py           OU + FFT 双实现（OU 为 §14.2 默认）
│   │   ├── vortex_field.py            零额外参数旋度（FFN 反对称投影，§14.2）
│   │   ├── memory_kernel.py           亚欧姆记忆核 γ(t) ~ t^(-α)
│   │   └── hopfield_potential.py      ET 对称双项 Hopfield 注意力（§8.5）
│   │
│   ├── qid/                           量子智动力学（经典模拟）
│   │   ├── qid_layer.py               v2.1: shared_with_ffn 默认 + 顶层 API
│   │   ├── berry_phase.py             零参数 Berry 旋转 + tanh*π 有界
│   │   └── quantum_noise.py           QFDT + OU/FFT 双模式 + set_temperature
│   │
│   ├── fid/                           场智动力学（诊断探针）
│   │   ├── fid_layer.py               v2.1: 三级透传 + LOSS_PREFIX + 三种代理
│   │   ├── curvature.py               §6.1 η + §6.2 Ricci + legacy
│   │   └── fisher_metric.py           秩亏警告 + 真 Fisher 对角校准
│   │
│   └── verification/                  v2.1 严格验证套件
│       ├── powerlaw_estimator.py      Clauset-Shalizi-Newman MLE
│       ├── critical_exponents.py      DFA + 谱分析 + measure_fisher_anisotropy_eta
│       ├── avalanche_detector.py      正确的 Beggs-Plenz 协议
│       ├── energy_meter.py            v2.1 batch 4: pynvml + idle + decode
│       ├── ablation_suite.py          11 组完整消融（含 v2.1 隔离变体）
│       └── prediction_test.py         DEPRECATED: 自动路由到 v2.0+ 工具链
│
├── model/
│   ├── modern_transformer.py          RoPE + RMSNorm + SwiGLU 强基线
│   ├── known_tricks_baseline.py       Transformer + 所有已知技巧（v2.1 真实生效）
│   └── model_uid.py                   UID 因果语言模型（v2.1 暴露顶层 API）
│
├── experiments/                       完整实验脚本
│   ├── run_scaling_law.py             v2.1: 统一 checkpoint schema
│   ├── run_critical_exponents.py      v2.1: noise-OFF vs noise-ON + η verdict
│   ├── run_energy_benchmark.py        v2.1: idle 基线 + above-idle + decode
│   ├── run_ablation.py                v2.1: 11 组 + 3 个关键对照报告
│   └── run_all.py                     v2.1: 端到端流水线 + checkpoint 路径修复
│
├── results/                           真实实验结果（待 Phase 1 填充）
│   └── README.md                      结果目录索引
│
├── tests/                             单元测试（pytest）
│   ├── test_et_lyapunov.py            §8.5 ET 单调下降 + 零参数旋度
│   ├── test_run_scaling_law.py        v2.1 参数透传 + checkpoint schema
│   ├── test_qid_layer.py              QID v2.1 + Berry 有界 + QFDT
│   ├── test_fid_layer.py              FID 三级透传 + JSON 安全 + η/Ricci
│   ├── test_critical_exponents.py     新增 η 回归 + 集成测试
│   ├── test_energy_meter.py           能量积分 + 平台兼容 + GPU 烟测
│   ├── test_data_loaders.py           PretrainJsonl + SftJsonl + tail 截断
│   ├── test_cid_layer.py              CID 基础测试
│   ├── test_ablation_suite.py         11 组消融存在性
│   ├── test_avalanche_detector.py     Beggs-Plenz 协议
│   ├── test_modern_transformer.py     baseline 基础测试
│   └── conftest.py                    共享 fixture
│
└── .github/workflows/                 CI + 每晚训练
```

---

## 🚀 快速开始

### 1. 环境准备

```bash
git clone https://github.com/gwailee/uid.git
cd uid
pip install -r requirements.txt

# 推荐安装 pynvml 以获得 25 Hz 功率采样（vs nvidia-smi 10 Hz 上限）
pip install nvidia-ml-py
```

### 2. 运行单元测试

```bash
pip install -r requirements-dev.txt

# 全部 CPU 可跑测试（约 200+ 用例）
pytest tests/ -v -m "not gpu"

# 仅 v2.1 关键回归测试
pytest tests/test_et_lyapunov.py \
       tests/test_run_scaling_law.py \
       tests/test_qid_layer.py \
       tests/test_fid_layer.py \
       tests/test_critical_exponents.py \
       tests/test_energy_meter.py \
       tests/test_data_loaders.py -v

# 如果有 NVIDIA GPU，也跑 GPU 端到端
pytest tests/ -v
```

### 3. CPU 冒烟测试（约 10 分钟）

```bash
# 下载真实小型数据集（不使用合成数据）
python -c "
from datasets import load_dataset
import json, os
os.makedirs('data/wikitext-2', exist_ok=True)
ds = load_dataset('wikitext', 'wikitext-2-raw-v1', split='train[:1000]')
with open('data/wikitext-2/train.jsonl', 'w') as f:
    for ex in ds:
        if ex['text'].strip():
            f.write(json.dumps({'text': ex['text']}) + '\n')
"

# 验证数据加载脚本自检
python data_loaders.py \
    --data_path data/wikitext-2/train.jsonl \
    --tokenizer_path gpt2 \
    --max_length 128

# 运行 11 组完整消融（小规模）
python experiments/run_ablation.py \
    --data_path data/wikitext-2/train.jsonl \
    --tokenizer_path gpt2 \
    --scale 10M \
    --epochs 1 \
    --seeds 42 \
    --batch_size 4 \
    --max_seq_len 128 \
    --output_dir /tmp/smoke
```

### 4. 完整实验（需要 GPU）

```bash
# 端到端流水线：缩放律 + 消融 + 临界指数 + 能耗
python experiments/run_all.py \
    --data_path data/wikitext-103/train.jsonl \
    --tokenizer_path gpt2 \
    --seeds 42 43 44
```

⚠️ **完整实验需要数日 GPU 计算**。本仓库提供工具与方法，实际大规模运行属于 Phase 1 的下一步（见 [ROADMAP.md](./ROADMAP.md)）。

### 5. 测量临界涌现（必须关闭噪声注入）

```python
import torch
from model.model_uid import UIDConfig, UIDModel

config = UIDConfig(vocab_size=6400, hidden_size=512, num_hidden_layers=8)
model = UIDModel(config)

# ... 训练模型 ...

# CRITICAL: 测量临界涌现前必须关闭噪声注入，
# 否则测出的 1/f / Hurst / η 仅是注入噪声本身的回响。
model.eval()
model.set_noise_injection(False)

# 然后进行 1/f 谱测量、Hurst 估计、雪崩检测、η 测量
from uid_theory.verification.critical_exponents import (
    run_critical_exponent_battery,
)
res = run_critical_exponent_battery(
    model=model, model_name="my_cid",
    dataloader=eval_loader, device="cuda",
    n_sequences=10000,
    disable_noise=True,           # 关闭噪声注入
    include_eta=True,             # 测量 §6.1 η
    eta_threshold=0.5,            # README 预言 4 阈值
)
print(f"β = {res.spectrum.beta_mean:.3f}")
print(f"H = {res.hurst.hurst_mean:.3f}")
print(f"η = {res.eta.eta_mean:.3f} (in_range={res.eta.eta_in_range})")
```

### 6. 验证 §8.5 ET Lyapunov 单调性

```python
model.set_energy_monitoring(True)
out = model(input_ids, output_hidden_states=True)
# 现在每个 hidden state 旁边都附带能量值，
# 可在递归递推中验证 dE/dt ≤ 0。
```

### 7. 实测推理能耗（v2.1 idle + above-idle）

```python
from uid_theory.verification.energy_meter import measure_inference_energy

em = measure_inference_energy(
    model=model, model_name="cid_full",
    input_ids=torch.randint(0, 50000, (16, 1024), device="cuda"),
    n_warmup=50, n_measure=500,
    device="cuda",
    mode="decode",                # 或 "prefill"
    new_tokens_per_decode=64,
    sample_rate_hz=25.0,
    idle_window_seconds=2.0,
)
print(f"Idle floor:           {em.idle_power_watts:.2f} W")
print(f"Above-idle power:     {em.power_above_idle_watts:.2f} W")
print(f"Energy/token (raw):   {em.energy_per_token_joules*1e3:.4f} mJ")
print(f"Energy/token (above): {em.energy_per_token_above_idle_joules*1e3:.4f} mJ")
```

---

## 🔬 实验设计

### 十一组完整消融变体（v2.1 新增 2 组）

#### A 组：CID 组件消融

| 变体 | 旋度 v | 色噪声 ξ | 记忆核 γ | 用途 |
|---|---|---|---|---|
| `cid_full` | ✅ | ✅ | ✅ | 完整 CID 主方程 |
| `cid_no_vortex` | ❌ | ✅ | ✅ | 旋度项贡献消融 |
| `cid_no_memory` | ✅ | ❌ | ✅ | 记忆核贡献消融（v2.0 新增）|
| `cid_no_noise` | ✅ | ✅ | ❌ | 色噪声项贡献消融 |

#### A' 组：v2.1 修正隔离（**新增**）

| 变体 | 描述 |
|---|---|
| `cid_full_no_et` | 完整 CID 但 §8.5 ET 对称项 OFF（隔离 ET 工程贡献）|
| `cid_full_fft_noise` | 完整 CID 但用 FFT 噪声代替 OU（隔离 §14.2 OU 工程贡献）|

#### B 组：已知技巧基线

| 变体 | 描述 |
|---|---|
| `transformer_baseline` | 现代 Transformer（RoPE + RMSNorm + SwiGLU）|
| `transformer_plus_noise` | 仅添加色噪声正则 |
| `transformer_plus_conv` | 仅添加 depthwise 因果卷积 |
| `transformer_plus_linear` | 仅添加额外线性项（v2.1 真正生效，不再静默退化为零）|
| `transformer_plus_all_tricks` | **三项已知技巧的组合（关键对照）** |

### 三个关键对照（v2.1 由 `run_ablation.py` 终端自动报告）

1. **`cid_full` vs `transformer_plus_all_tricks`** —— UID 物理框架 vs 已知技巧组合的核心证伪测试
2. **`cid_full` vs `cid_full_no_et`** —— §8.5 ET 对称项的工程贡献
3. **`cid_full` vs `cid_full_fft_noise`** —— §14.2 OU 噪声相对 FFT 的工程贡献

**关键证伪测试**：如果 `cid_full` 不能显著优于 `transformer_plus_all_tricks`，则 UID 的"物理框架"贡献被证伪——增益（如果有）来自已知技巧本身，而非物理组织方式。

⚠️ **v2.1 重要修正**：v2.0 中 `transformer_plus_linear` 与 `transformer_plus_all_tricks` 的 `VortexField` 没有接收 FFN 权重引用，导致其内部反对称矩阵为空、整个"linear extra"项静默退化为零。这使得 v2.0 的对照测试**没有真正测试"已知技巧组合"的能力**。v2.1 修复后，该对照才真正生效。**v2.0 上跑过的任何对照实验结果都应当在 v2.1 下重跑后方可引用。**

### 验证流程

```mermaid
flowchart TD
    A["run_all.py 端到端流水线"] --> B["1. 缩放律实验<br/>iso-FLOP × 10M-1B 模型族<br/>(v2.1 统一 checkpoint schema)"]
    A --> C["2. 11 组完整消融<br/>3 个关键对照报告"]
    A --> D["3. 临界指数测量<br/>noise OFF vs ON + η verdict"]
    A --> E["4. 实测能耗<br/>idle baseline + above-idle + decode mode"]

    B --> F["scaling_curves.png<br/>等损失水平间距"]
    C --> G["summary.json<br/>3 个对照 verdict"]
    D --> H["verdict.md<br/>涌现确认/否定/残留回响警告"]
    E --> I["energy_per_token.json<br/>raw + above_idle 双轨"]
```

---

## 📐 CID 主方程在代码中的对应（v2.1 更新）

理论方程（CID 第 6 章）：

```
dφ/dt  =  -∇U(φ)               ← 联想记忆
         + v(φ)                 ← 多热浴旋度
         - ∫ γ(t-s) (dφ/ds) ds  ← 色阻尼
         + ξ(t)                 ← 色噪声
```

代码对应（见 `uid_theory/cid/cid_layer.py`）：

```python
# 1. 联想记忆 -∇U → HopfieldAttention (v2.1: §8.5 ET 对称双项)
#    out = softmax_C(K Q^T) @ q  +  softmax_B(K Q^T) @ k
#    享 Lyapunov 能量函数前向单调下降保证。
grad_term   = torch.exp(self.log_w_grad) * self.attn(h, causal_mask=mask)

# 2. 旋度 v(φ) → VortexField (v2.1: §14.2 零额外参数)
#    J = (W_FFN - W_FFN^T) / 2 ，从 FFN 第一层权重的反对称分量构造
#    v = temp_diff * J @ x ，每层仅 +1 个可学习标量 log_temp_diff
vortex_term = torch.exp(self.log_w_vortex) * self.vortex(h)[0]

# 3. 色阻尼 γ(t) ~ t^(-α) → MemoryKernel (depthwise 因果卷积)
mem_term    = -torch.exp(self.log_w_mem) * self.memory(h)

# 4. 色噪声 → OrnsteinUhlenbeckNoise (v2.1: §14.2 物理默认)
#    d ξ = -ξ/τ dt + sqrt(2/τ) dW ，稳态相关 <ξ(t)ξ(t+s)> = exp(-|s|/τ)
#    可通过 model.set_noise_injection(False) 在测量临界指数时关闭，
#    避免循环测量问题。FFT 版本仍可通过 noise_type="fft" 选用。
noise_term  = self.noise_scale * self.noise(B, S, h.device, h.dtype)

# Euler-Maruyama 离散：dt 已吸收进各项权重
x = x + grad_term + vortex_term + mem_term + noise_term
```

### CID 与 Transformer 的关系

在以下极限下，CID 严格退化为标准 Transformer：

| 极限条件 | 代码开关 |
|---|---|
| 关闭旋度 v = 0 | `use_vortex=False` |
| 关闭色噪声 ξ = 0 | `use_colored_noise=False` |
| 退化色阻尼为白噪声 γ → δ | `use_memory=False` |
| 关闭 ET 对称项（退化为标准 attention）| `use_et_symmetric=False` |
| 标准缩放 β = 1/√d_k | `HopfieldAttention.scale` 已实现 |

这印证理论第 8、10 章的论断：**"Transformer 是 CID 的最简极限"**。但 v2.0+ 的关键证伪测试是：单纯加回"已知技巧"组合是否就够了？还是 CID 的物理组织方式确实带来增量？

---

## 📊 预注册证伪条件

遵循开放科学的最佳实践，我们**预注册**以下证伪条件。如在 Phase 1 后任一未满足，我们将公开承认相应 UID 主张被**证伪**：

1. **参数效率**：在 100M 规模 iso-FLOP 缩放律研究中，CID 曲线在等损失处必须比现代 Transformer 基线向左偏移 **≥ 3×**，**且**比 "Transformer + 所有已知技巧" 基线向左偏移 **≥ 1.5×**。

2. **临界指数涌现**（噪声注入**关闭**后，即调用 `model.set_noise_injection(False)`）：
   - 训练后的 CID 必须在 ≥80% 的层呈现 β ∈ [0.7, 1.3]
   - 雪崩指数 τ（通过 Clauset MLE + KS 检验，p > 0.1）必须 ∈ [1.3, 1.7]
   - **Fisher 度量各向异性 η > 0.5** （§6.1 / README 预言 4；由 `measure_fisher_anisotropy_eta()` 测量，必须排除秩亏情况）

3. **能耗效率**：实测每 token 焦耳数（v2.1 `energy_meter.py` 实测 above-idle）必须 ≤ 现代 Transformer 基线在等困惑度下的 **1/3**。

4. **§8.5 ET Lyapunov 单调性**：开启 `model.set_energy_monitoring(True)` 后，在小步长递归应用注意力时，ET 能量必须严格单调不增（容差 < 10⁻³ × |E₀|）。该证伪条件已由 `tests/test_et_lyapunov.py` 单元测试覆盖。

5. **三个关键消融对照**（v2.1 由 `run_ablation.py` 自动报告）：
   - `cid_full` 必须显著优于 `transformer_plus_all_tricks`（UID 物理框架核心证伪）
   - 关闭 ET 对称项（`cid_full_no_et`）应当导致 PPL 显著恶化
   - 用 FFT 噪声代替 OU（`cid_full_fft_noise`）应当导致测量临界指数时的可信度恶化（noise-OFF 与 noise-ON 接近重合）

**我们承诺无论结果如何都公开发布。**

---

## ⚠️ 诚实声明

| # | 声明 |
|---|---|
| 1 | **CID 层可工程化但待大规模验证**：v2.1 提供了完整的验证基础设施并完成了 §8.5 / §14.2 三项理论修正的代码落地，但实际大规模实验（10M–1B 模型族）的运行属于 Phase 1，尚未完成。 |
| 2 | **QID 是经典代理**：本实现使用经典神经网络模拟量子相干（Berry 相位、含零点项的色噪声、现象学 Lindblad 通道），**不是**严格 Kraus 分解。真实量子优势需 NISQ 或容错量子硬件。**本代码无法验证 QID 的量子主张**。 |
| 3 | **FID 是探索性纲领**：Fisher 度量与曲率代理承担**诊断与软正则**角色，**不是**任何具体流形上严格定义的场方程数值解。本代码采用**隐状态空间**经验协方差作为 Fisher 矩阵代理（参数空间真 Fisher 由 `FisherMetric.compute_true_fisher_diagonal()` 提供，仅作小批次校准之用）。 |
| 4 | **CID 是本代码唯一可证伪/可证实的层级**。引用 UID 时应尊重这一范围。 |
| 5 | **v0.1 与 v2.0 的实证主张应在 v2.1 下重新跑过后才可引用**：v0.1 验证套件存在循环论证、样本不足等方法学缺陷；v2.0 的 baseline `VortexField` 静默退化为零导致关键对照失效。两者的修复在 v2.1 已完成。详情见 [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) 与 [CHANGELOG.md](./CHANGELOG.md)。 |
| 6 | **能耗对比应优先看 above-idle 字段**：小模型的 idle 基线（典型 30-80W）会主导 raw energy/token，造成大模型看起来不成比例地高效。v2.1 `energy_meter.py` 同时报告两栏，README 预言 5 / 6 均以 **above-idle** 为评估标准。 |

---

## 🗺️ 验证路线图

| 阶段 | 时间 | 目标 |
|---|---|---|
| **Phase 0** | 2026 Q2 | ✅ 完成 v2.1 验证基础设施（本仓库当前状态）|
| **Phase 1** | 2026 Q2–Q3 | 10M–100M 规模缩放律 + 11 组消融 + 临界涌现测试（含 η） |
| **Phase 2** | 2026 Q3–Q4 | 300M–1B 规模验证 + 收紧证伪阈值 |
| **Phase 3** | 2026 Q4 | 多硬件平台（H100/A100/边缘设备）能耗对比 |
| **Phase 4** | 2027 Q1 | 邀请独立团队复现 |
| **Phase 5** | 2027 Q2+ | 基于实证更新理论论文，投稿到正式期刊 |

完整路线图见 [ROADMAP.md](./ROADMAP.md)。

---

## 📚 引用文献

完整文献清单见 [`theory.md`](./theory.md) 附录 A。核心一手文献（含可点击 DOI）：

- **Langevin, P.** (1908). *Comptes Rendus* 146, 530. [gallica.bnf.fr](https://gallica.bnf.fr/ark:/12148/bpt6k3100t/f532)
- **Mori, H.** (1965). *Prog. Theor. Phys.* 33, 423. [doi.org/10.1143/PTP.33.423](https://doi.org/10.1143/PTP.33.423)
- **Zwanzig, R.** (1960). *J. Chem. Phys.* 33, 1338. [doi.org/10.1063/1.1731409](https://doi.org/10.1063/1.1731409)
- **Hopfield, J. J.** (1982). *PNAS* 79, 2554. [doi.org/10.1073/pnas.79.8.2554](https://doi.org/10.1073/pnas.79.8.2554)
- **Hoover, B., et al.** (2023). *Energy Transformer*. NeurIPS 2023. [arxiv.org/abs/2302.07253](https://arxiv.org/abs/2302.07253) — §8.5 ET 对称项的来源
- **Bialek, W., Nemenman, I., & Tishby, N.** (2001). *Neural Computation* 13, 2409. [doi.org/10.1162/089976601753195969](https://doi.org/10.1162/089976601753195969)
- **Clauset, A., Shalizi, C. R., & Newman, M. E.** (2009). *SIAM Review* 51(4), 661. [doi.org/10.1137/070710111](https://doi.org/10.1137/070710111)
- **Berry, M. V.** (1984). *Proc. R. Soc. A* 392, 45. [doi.org/10.1098/rspa.1984.0023](https://doi.org/10.1098/rspa.1984.0023)
- **Caldeira, A. O., & Leggett, A. J.** (1983). *Physica A* 121, 587. [doi.org/10.1016/0378-4371(83)90013-4](https://doi.org/10.1016/0378-4371(83)90013-4)
- **Amari, S.** (1985). *Differential-Geometrical Methods in Statistics*. [doi.org/10.1007/978-1-4612-5056-2](https://doi.org/10.1007/978-1-4612-5056-2)
- **Karakida, R., Akaho, S., & Amari, S.** (2019). *Universal Statistics of Fisher Information in Deep Neural Networks*. AISTATS. [arxiv.org/abs/1806.01316](https://arxiv.org/abs/1806.01316) — §6.1 η 的 DNN 实证基础
- **Beggs, J. M., & Plenz, D.** (2003). *J. Neurosci.* 23, 11167. [doi.org/10.1523/JNEUROSCI.23-35-11167.2003](https://doi.org/10.1523/JNEUROSCI.23-35-11167.2003)
- **Linkenkaer-Hansen, K., et al.** (2001). *J. Neurosci.* 21, 1370. [doi.org/10.1523/JNEUROSCI.21-04-01370.2001](https://doi.org/10.1523/JNEUROSCI.21-04-01370.2001)
- **Peng, C.-K., et al.** (1994). *Mosaic organization of DNA nucleotides*. *Phys. Rev. E* 49, 1685. — DFA 金标准
- **Ramsauer, H., et al.** (2020). *Hopfield Networks Is All You Need*. [arxiv.org/abs/2008.02217](https://arxiv.org/abs/2008.02217)
- **Vaswani, A., et al.** (2017). *Attention Is All You Need*. [arxiv.org/abs/1706.03762](https://arxiv.org/abs/1706.03762)

---

## 📝 引用本工作

如果您在论文、产品或服务中使用了本工作，请引用：

```bibtex
@article{li2026uid,
  title  = {Intelligence Is a Non-Equilibrium Field: A Three-Tier Physical 
            Theory of Unified Intelligo-Dynamics (UID)},
  author = {LI, Gui and JIE, Dangyang and KANG, Haitao},
  year   = {2026},
  publisher = {Zenodo},
  doi    = {10.5281/zenodo.20372493},
  url    = {https://github.com/gwailee/uid}
}
```

**纯文本引用**：

> LI, Gui, JIE, Dangyang, & KANG, Haitao. (2026). Intelligence Is a Non-Equilibrium Field: A Three-Tier Physical Theory of Unified Intelligo-Dynamics (UID). Zenodo. https://doi.org/10.5281/zenodo.20372493

---

## 📜 许可证

本项目采用 **双许可证** 发布。

| 使用场景 | 适用许可证 |
|---|---|
| 学术研究、教学、学生、个人、注册非营利机构、政府研究机构 | **PolyForm Noncommercial License 1.0.0**（免费）— 见 [`LICENSE-NONCOMMERCIAL`](./LICENSE-NONCOMMERCIAL) |
| 任何商业、营利或生产用途 | **Commercial License**（需付费授权）— 见 [`LICENSE-COMMERCIAL`](./LICENSE-COMMERCIAL) |

**双许可适用判断**（完整规则见 [`LICENSE`](./LICENSE)）：

- ✅ **免费可用**：高校教师/学生的科研与教学、个人学习、非营利机构的研究工作
- ❌ **需要商业授权**：将本代码或其衍生作品用于（a）任何为营利实体创造收入或价值的活动；（b）生产环境部署；（c）随商业产品/服务分发；（d）作为付费服务（含 SaaS）托管；（e）有偿咨询、技术服务或培训

### 商业授权咨询

任何企业（含外资、合资、有限责任公司、股份公司、个体工商户）若要将本仓库用于上述商业场景，**必须**先获得 Suzhou Jodell Robotics Co., Ltd. 的书面授权。

| 联系项 | 内容 |
|---|---|
| **公司** | Suzhou Jodell Robotics Co., Ltd.（苏州钧舵机器人有限公司）|
| **联系人** | Gui LI |
| **邮箱** | **lig@jodell.cn** |
| **邮件主题前缀** | `[UID Commercial License]` |

申请时请提供：被授权方法定名称与注册地、预期用途与部署规模、商业上线时间表、授权谈判联系人。

### 商标说明

"UID"、"Unified Intelligo-Dynamics"、"CID"、"QID"、"FID"、"Suzhou Jodell Robotics" 及相关标识均为 Suzhou Jodell Robotics Co., Ltd. 的专有标识。未经书面许可不得用于商业宣传或产品命名。

### 免责声明

> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY ARISING FROM USE OF THIS SOFTWARE.

---

## 🙏 致谢

- **同行评审者**：特别感谢匿名评审者对 v0.1 / v2.0 的详细批评，分别促成了 v2.0 的完整重写与 v2.1 的 §8.5 / §14.2 实现修正。诚实的批评让 UID 成为了更严谨的项目。详情见 [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)。
- **[MiniMind](https://github.com/jingyaogong/minimind) by jingyaogong**：提供高质量的小模型基础架构与数据集。
- **UID 理论的物理先驱们**（按时间顺序）：Langevin、Einstein、Fokker、Planck、Mori、Zwanzig、Lindblad、Caldeira-Leggett、Berry、Amari、Hopfield、Bak-Tang-Wiesenfeld、Bialek、Friston、Beggs-Plenz、Linkenkaer-Hansen、Karakida-Akaho-Amari 等。
- **现代深度学习架构的奠基者**：Vaswani et al.（Transformer）、Ramsauer et al.（Modern Hopfield Networks）、Hoover et al.（Energy Transformer，§8.5 关键参考）、Gu & Dao（Mamba）、He et al.（ResNet）。
- **统计方法学先驱**：Clauset、Shalizi & Newman（幂律拟合金标准）、Peng et al.（DFA 方法）。
- **开放科学工具生态**：PyTorch、Hugging Face、pynvml、pytest、ruff —— 让严格验证成为可能。

---

<div align="center">

> **统一智动力学的核心目标**：把"智能"从一种工程现象提升为一种物理理论。
> 
> CID 可编码，QID 可模拟，FID 可探索。**所有结果都是可证伪的——这是科学的核心。**

</div>
```
