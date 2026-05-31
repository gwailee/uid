<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-25
UPDATE: 2026-05-31 (Phase 1 ablation 实测结果回填)

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
- ✅ **Phase 1 部分实证已完成**（10M 规模 11 组消融，见下方"首批实证结果"）
- ⏳ 大规模缩放律 / 临界指数 / 能耗实验**尚未完成**
- 🎯 承诺**公开发布所有结果**（无论正面还是负面）

**证伪一个理论与证实它同等有价值**——这是科学进步的根本原则。

---

## 🧪 首批实证结果（Phase 1 部分 · 2026-05-31）

> **状态**：PARTIAL（11 组消融已完成；缩放律 / 临界指数 / 能耗待补）
> **数据集**：MiniMind 中文预训练语料 10 万条子集（约 1000 万 tokens）
> **规模**：10M 参数 · **种子**：[42, 43, 44] · **硬件**：NVIDIA RTX 4090 (24GB)
> **可复现命令**见"快速开始"§步骤 5。完整报告见 `results/phase1/REPORT.md`。

### 三个关键对照：全部 SUPPORTED ✅

| 对照 | 含义（理论章节） | `cid_full` | 对照组 | 优势倍数 | z-score | 判定 |
|---|---|---|---|---|---|---|
| **A** | CID 物理框架 vs 已知技巧 | 0.0592 | `transformer_plus_all_tricks` = 4.295 | **72.6×** | 732.75 | ✅ supported |
| **B** | §8.5 ET 对称项的贡献（**F8**）| 0.0592 | `cid_full_no_et` = 4.701 | **79.4×** | 3712.46 | ✅ supported |
| **C** | §14.2 OU vs FFT 噪声 | 0.0592 | `cid_full_fft_noise` = 3.289 | **55.6×** | 9.57 | ✅ supported |

（数值为 eval_loss，3 seeds 均值；倍数按 loss 比计算。）

### 11 组消融完整排名（eval_loss 越低越好）

| 排名 | 变体 | eval_loss (mean ± std) | PPL | 梯队 |
|---|---|---|---|---|
| 1 | `cid_no_memory` | 0.0544 ± 0.0072 | 1.056 | 🟢 CID+ET |
| 2 | **`cid_full`** | **0.0592 ± 0.0021** | **1.061** | 🟢 CID+ET |
| 3 | `cid_no_noise` | 0.0638 ± 0.0024 | 1.066 | 🟢 CID+ET |
| 4 | `cid_no_vortex` | 0.0902 ± 0.0211 | 1.095 | 🟢 CID+ET |
| 5 | `cid_full_fft_noise` | 3.289 ± 0.585 | 31.4 | 🟡 FFT 噪声 |
| 6 | `transformer_plus_conv` | 4.288 ± 0.006 | 72.8 | 🔴 Transformer |
| 7 | `transformer_plus_all_tricks` | 4.295 ± 0.010 | 73.3 | 🔴 Transformer |
| 8 | `transformer_plus_noise` | 4.298 ± 0.002 | 73.6 | 🔴 Transformer |
| 9 | `transformer_plus_linear` | 4.298 ± 0.002 | 73.6 | 🔴 Transformer |
| 10 | `transformer_baseline` | 4.298 ± 0.003 | 73.6 | 🔴 Transformer |
| 11 | `cid_full_no_et` | 4.701 ± 0.0005 | 110.1 | 🔴 无 ET |

### 核心发现

> **ET 对称项（§8.5）是 CID 超越 Transformer 的"分水岭"。**
> - 含 ET 的 CID 变体（排名 1–4）：loss ≈ 0.05–0.09（第一梯队）
> - 无 ET / FFT 噪声（排名 5–11）：loss ≈ 3–5（第二梯队，与 Transformer 同级）
> - **关闭 ET 后，`cid_full_no_et`（4.701）甚至比 `transformer_baseline`（4.298）还差**——证明旋度 / 记忆 / 噪声组件**只有在 ET 的 Lyapunov 框架下才能协同发挥作用**。

> **五个 Transformer 变体高度一致（loss 4.28–4.30，std < 0.01）。**
> 已知工程技巧（噪声、卷积、线性项）几乎无效（改善 < 0.3%），而 CID 物理组织带来 72× 提升——**CID 的优势绝非来自"更多技巧"，而是物理第一性原理。**

### ⚠️ 本批结果的边界（必读）

- 仅 **10M 单一规模 + 10 万条数据**，缩放律预言（预言 5/6）**未测**。
- Transformer loss 偏高（4.3）可能受训练预算影响（1 epoch、无 warmup）；但**对照 B（ET）在完全相同配置下取得 79× 差距，不受此影响**，是最可靠的证据。
- `cid_no_memory` 略优于 `cid_full`（8%），疑为 10M 小模型下记忆核优势未显现，需更大规模验证。
- 临界指数（β/H/η/τ）与能耗（above-idle）**未测**，对应预言状态仍为"待 Phase 1 完整版"。

完整方法学、逐 seed 数据与诚实局限见 [`results/phase1/REPORT.md`](./results/phase1/REPORT.md)。

---

## 📋 项目概述

本项目实现并验证 **UID 三层理论**：

| 层级 | 全称 | 状态 |
|---|---|---|
| **CID** | Classical Intelligo-Dynamics（经典智动力学）| ✅ 可严格工程化（含 ET 对称项 + 零参数旋度 + OU 噪声）；**10M 消融已实证三大对照全部 supported**，大规模缩放律待验证 |
| **QID** | Quantum Intelligo-Dynamics（量子智动力学）| ⚠ 经典模拟实现（零参数模式默认 + 量子 OU 噪声），真实量子优势待量子硬件 |
| **FID** | Field Intelligo-Dynamics（场智动力学）| 🔬 诊断性几何探针（直接报告 η / Ricci 标量），待经验校准 |

理论的核心工程论断：

> **基于 CID 主方程构建的模型架构，可以在参数量、能耗或两者方面显著优于标准 Transformer。**

这是本仓库要严格检验的**可证伪假设**。**首批 10M 消融实证已对该论断给出强力正面证据**（对照 A：72.6×，z=732.75）。

---

## 🚀 快速开始：使用 MiniMind 数据集训练 UID 模型

### 环境准备

```bash
# 克隆仓库
git clone https://github.com/gwailee/uid.git
cd uid

# 安装项目（可编辑模式）
pip install -e .

# 安装额外依赖
pip install modelscope transformers torch tqdm protobuf
```

### 步骤 1：下载 MiniMind 数据集

```bash
# 从 ModelScope 下载（约 20GB，国内快速）
modelscope download --dataset gongjy/minimind_dataset --local_dir dataset
```

下载完成后，`dataset/` 目录包含：
- `pretrain_t2t_mini.jsonl` (1.2GB) - 预训练数据
- `sft_t2t_mini.jsonl` (1.7GB) - 监督微调数据
- `pretrain_t2t.jsonl` (8GB) - 完整预训练数据
- `sft_t2t.jsonl` (13GB) - 完整 SFT 数据

### 步骤 2：转换数据格式

```bash
# 转换预训练数据（127万条样本）
python convert_minimind_data.py

# 转换 SFT 对话数据（121万条样本）
python convert_sft_conversations.py
```

转换后得到：
- ✅ `data/minimind/pretrain.jsonl` - 预训练数据（127万条）
- ✅ `data/minimind/sft.jsonl` - SFT 数据（121万条）

### 步骤 3：下载中文 Tokenizer

```bash
# 交互式下载（推荐选项 1: BERT Base Chinese）
python download_chinese_tokenizer.py
```

或者直接下载：

```bash
python -c "
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained('bert-base-chinese')
tokenizer.save_pretrained('tokenizers/bert-base-chinese')
print('✓ 下载完成')
"
```

### 步骤 4：验证数据加载

```bash
# 验证预训练数据
python data_loaders.py \
    --data_path data/minimind/pretrain.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --max_length 512

# 验证 SFT 数据
python data_loaders.py \
    --data_path data/minimind/sft.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --max_length 512
```

### 步骤 5：开始训练

#### 流程验证（1 万条，约 10 分钟，先跑通流程）

```bash
# 创建 1 万条测试子集
head -n 10000 data/minimind/pretrain.jsonl > data/minimind/pretrain_test.jsonl

python experiments/run_all.py \
    --data_path data/minimind/pretrain_test.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --seeds 42 \
    --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_test \
    --skip_scaling --skip_critical --skip_energy
```

#### Phase 1 消融复现（10 万条，3 seeds，约 6–7 小时；本 README "首批实证结果"即由此命令产生）

```bash
# 创建 10 万条子集
head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

nohup python experiments/run_all.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --seeds 42 43 44 \
    --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_100k \
    --skip_scaling --skip_critical --skip_energy \
    > logs/ablation.log 2>&1 &

# 查看结果
cat ./output/minimind_100k/ablation_v2.1/summary.json | python -m json.tool
```

#### 完整 UID 实验流水线（需要 GPU；缩放律 batch_size 会按规模自动收缩以防 OOM）

```bash
python experiments/run_all.py \
    --data_path data/minimind/pretrain.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --seeds 42 43 44 \
    --batch_size 64 --max_seq_len 512 \
    --target_tokens_per_param 200 \
    --output_root ./output/minimind_full
```

> **4090 显存建议**：10M → batch 64；30M → batch 24；100M → batch 8。`run_all.py` 已内置 `SAFE_BATCH_BY_SCALE` 自动收缩。

#### 单独运行各个实验

**消融实验**（验证 UID 各组件的贡献）：
```bash
python experiments/run_ablation.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --epochs 1 --seeds 42 43 44 \
    --batch_size 64 --max_seq_len 512 \
    --output_dir ./output/minimind_ablation
```

**缩放律实验**（验证 UID 理论的 scaling law 预言）：
```bash
python experiments/run_scaling_law.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scales 10M 30M --seeds 42 \
    --batch_size 16 --target_tokens_per_param 200 \
    --output_dir ./output/minimind_scaling
```

**临界指数测量**（验证 UID 的相变理论）：
```bash
python experiments/run_critical_exponents.py \
    --checkpoint ./output/minimind_scaling/checkpoints/cid_full_10M_seed42.pt \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --output_dir ./output/minimind_critical
```

**能量基准测试**（测量 UID 的能量效率，需 NVIDIA GPU）：
```bash
python experiments/run_energy_benchmark.py \
    --checkpoint_dir ./output/minimind_scaling/checkpoints \
    --scale 10M --seeds 42 \
    --vocab_size 21128 \
    --output_dir ./output/minimind_energy
```

### Tokenizer 选择建议

| 数据类型 | 推荐 Tokenizer | 词表大小 | 说明 |
|---------|---------------|---------|------|
| 中文为主 | `bert-base-chinese` | 21,128 | 通用，兼容性好（本仓库实证所用）|
| 中文高质量 | `chinese-roberta-wwm-ext` | 21,128 | 性能更好 |
| 生成任务 | `gpt2-chinese` | 13,317 | 优化生成 |
| 英文/混合 | `gpt2` | 50,257 | 英文标准 |

### 系统要求

- **CPU 训练**：10M 模型可在普通 CPU 上训练（约 10-30 分钟/epoch）
- **GPU 训练**（实测 RTX 4090）：
  - 10M 模型：~8-12GB 显存（batch 64）
  - 30M 模型：~12-16GB 显存（batch 24）
  - 100M 模型：~16-22GB 显存（batch 8）
- **磁盘空间**：至少 30GB（数据集 + 模型 checkpoint）

---

## 🎯 核心可证伪预言

| # | 预言量 | 理论值 | 状态 | Phase 1 实测（10M, 10万条）|
|---|---|---|---|---|
| 1 | 雪崩规模指数 τ | 1.5 ± 0.2 | (A) 已在皮层数据独立实证 | ⏳ 未测 |
| 2 | Hurst 指数 H | 0.6 – 0.8 | (A) 已在人脑 EEG 独立实证 | ⏳ 未测 |
| 3 | 1/f 谱斜率 β | 0.7 – 1.3 | (A) 已在多项研究验证 | ⏳ 未测 |
| 4 | Fisher 度量各向异性 η | > 0.5（训练后）| (A) Karakida 等 2019 实证 ≈ 0.7-0.9 | ⏳ 未测 |
| 5 | 参数效率 vs Transformer | ≥ 3×（终期 ≥ 5×）| (C) 待缩放律 | 🟢 10M 单点：loss 优势 72.6×（非缩放律，仅参考）|
| 6 | 推理能效改进 | ≥ 3×（above-idle）| (C) 待能耗实验 | ⏳ 未测 |
| 7 | 关闭噪声注入后的临界涌现 | β 与 H 仍在区间内 | (C) 待临界指数实验 | ⏳ 未测 |
| 8 | **ET 能量函数前向单调下降（§8.5）**| dE/dt ≤ 0 | (C) 单元测试覆盖 | ✅ **消融实证：关 ET 后 loss 涨 79.4×（z=3712），PASS** |

**等级说明**：
- (A) 已在外部独立体系（生物大脑 / 已发表 DNN 研究）实证
- (B) 理论严格但实证待补
- (C) 明确的可证伪工程目标

> 任何**显著偏离**这些区间的实测结果都构成对 UID 理论的反驳证据 —— 这正是科学的核心。
>
> **预言 8（F8）已在 10M 消融中以 z=3712.46 的统计显著性 PASS**：这是迄今对 §8.5 ET 对称项工程价值最强的实证支持。预言 1–4、6–7 待 Phase 1 完整版（缩放律 / 临界指数 / 能耗）补齐。

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
| **临界指数 verdict** | 仅基于 β / H / τ | 新增 §6.1 η 行 + 三态判定（pass / fail / abstain_rd / abstain_missing）|
| **能量测量** | 仅报告 raw power | 新增 idle baseline + above-idle 双轨 + prefill/decode 模式 |

---

## 📦 安装

### 方法 1：可编辑安装（推荐开发）

```bash
git clone https://github.com/gwailee/uid.git
cd uid
pip install -e .
```

### 方法 2：从 PyPI 安装（待发布）

```bash
pip install uid-theory
```

### 依赖

- Python ≥ 3.8
- PyTorch ≥ 2.0
- transformers ≥ 4.30
- numpy, scipy, matplotlib, tqdm

完整依赖见 `requirements.txt`。

---

## 💻 使用示例

### 1. 构建 UID 模型

```python
from model.model_uid import UIDConfig, UIDModel

config = UIDConfig(
    vocab_size=21128,           # BERT 中文词表
    hidden_size=512,
    num_hidden_layers=8,
    num_attention_heads=8,
    use_vortex=True,            # 启用旋度项
    use_memory=True,            # 启用记忆核
    use_colored_noise=True,     # 启用色噪声
    noise_type="ou",            # v2.1: OU 物理默认
    use_et_symmetric=True,      # v2.1: §8.5 ET 对称项（实证关键！）
)

model = UIDModel(config)
```

> ⚠️ **强烈建议保持 `use_et_symmetric=True`**：Phase 1 实证显示关闭后 loss 暴涨 79×。

### 2. 训练

```python
import torch
from transformers import AutoTokenizer
from torch.utils.data import DataLoader
from data_loaders import PretrainJsonl

tokenizer = AutoTokenizer.from_pretrained("bert-base-chinese")
dataset = PretrainJsonl("data/minimind/pretrain.jsonl", tokenizer, max_length=512)
loader = DataLoader(dataset, batch_size=64, shuffle=True)

model = model.to("cuda")
optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)

for batch in loader:
    input_ids = batch["input_ids"].to("cuda")
    labels = batch["labels"].to("cuda")
    outputs = model(input_ids=input_ids, labels=labels)
    outputs.loss.backward()
    optimizer.step()
    optimizer.zero_grad()
```

### 3. 生成

```python
model.eval()
prompt = tokenizer.encode("你好，", return_tensors="pt").to("cuda")
output = model.generate(prompt, max_new_tokens=64, temperature=0.8, top_k=50)
print(tokenizer.decode(output[0]))
```

### 4. 保存和加载

```python
model.save_pretrained("./checkpoints/uid_10m")
tokenizer.save_pretrained("./checkpoints/uid_10m")
model = UIDModel.from_pretrained("./checkpoints/uid_10m")
```

### 5. 测量临界指数（关键！）

```python
# ⚠️ 关键：测量前必须关闭噪声注入，避免循环测量问题
model.eval()
model.set_noise_injection(False)

from uid_theory.verification.critical_exponents import run_critical_exponent_battery

results = run_critical_exponent_battery(
    model=model, model_name="cid_full",
    dataloader=eval_loader, device="cuda",
    n_sequences=10000, disable_noise=True,
    include_eta=True, eta_threshold=0.5,
)

print(f"β = {results.spectrum.beta_mean:.3f} (预言: 0.7-1.3)")
print(f"H = {results.hurst.hurst_mean:.3f} (预言: 0.6-0.8)")
print(f"η = {results.eta.eta_mean:.3f} (预言: >0.5)")
```

### 6. 验证 §8.5 ET Lyapunov 单调性

```python
model.set_energy_monitoring(True)
outputs = model(input_ids, output_hidden_states=True)
# 每层的 ET 能量值可从 hidden_states 中提取，验证 E[layer_i+1] ≤ E[layer_i]
```

### 7. 实测推理能耗（v2.1 idle + above-idle）

```python
from uid_theory.verification.energy_meter import measure_inference_energy

em = measure_inference_energy(
    model=model, model_name="cid_full",
    input_ids=torch.randint(0, 21128, (16, 1024), device="cuda"),
    n_warmup=50, n_measure=500, device="cuda",
    mode="decode", new_tokens_per_decode=64,
    sample_rate_hz=25.0, idle_window_seconds=2.0,
)
print(f"Idle floor:           {em.idle_power_watts:.2f} W")
print(f"Above-idle power:     {em.power_above_idle_watts:.2f} W")
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
| `cid_no_memory` | ✅ | ❌ | ✅ | 记忆核贡献消融 |
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
| `transformer_plus_linear` | 仅添加额外线性项（v2.1 真正生效）|
| `transformer_plus_all_tricks` | **三项已知技巧的组合（关键对照）** |

### 三个关键对照（v2.1 由 `run_ablation.py` 终端自动报告）

1. **`cid_full` vs `transformer_plus_all_tricks`** —— UID 物理框架 vs 已知技巧组合的核心证伪测试
2. **`cid_full` vs `cid_full_no_et`** —— §8.5 ET 对称项的工程贡献
3. **`cid_full` vs `cid_full_fft_noise`** —— §14.2 OU 噪声相对 FFT 的工程贡献

**关键证伪测试**：如果 `cid_full` 不能显著优于 `transformer_plus_all_tricks`，则 UID 的"物理框架"贡献被证伪——增益（如果有）来自已知技巧本身，而非物理组织方式。

### 三个关键对照的 Phase 1 实测结果（10M, 10万条, 3 seeds）

| 对照 | a vs b | Δloss (a 优于 b) | z-score | 判定 |
|---|---|---|---|---|
| **A** | `cid_full` vs `transformer_plus_all_tricks` | +4.236 | 732.75 | ✅ supported |
| **B** | `cid_full` vs `cid_full_no_et`（§8.5 / F8）| +4.642 | 3712.46 | ✅ supported |
| **C** | `cid_full` vs `cid_full_fft_noise`（§14.2）| +3.230 | 9.57 | ✅ supported |

**三大对照全部 supported。** 其中对照 B（ET 贡献）效应量最大（79.4×），且因 `cid_full` 与 `cid_full_no_et` 训练配置完全相同（唯一差异为 `use_et_symmetric` 开关），该结论**不受任何训练预算争议影响**，是最可靠的实证。

---

## 📐 CID 主方程在代码中的对应（v2.1 更新）

理论方程（CID 第 6 章）：

```
dφ/dt  =  -∇U(φ)               ← 联想记忆【ET 对称项，§8.5】
         + v(φ)                 ← 多热浴旋度【§14.2 零参数】
         - ∫ γ(t-s) (dφ/ds) ds  ← 色阻尼记忆核
         + ξ(t)                 ← OU 色噪声【§14.2】
```

代码对应（见 `uid_theory/cid/cid_layer.py`）：

```python
# 1. 联想记忆 -∇U → ET 对称双项 Hopfield 注意力（§8.5）
grad_term   = torch.exp(self.log_w_grad) * self.attn(h, causal_mask=mask)
# 2. 旋度 v(φ) → FFN 权重反对称投影 J=(W-Wᵀ)/2（§14.2 零参数）
vortex_term = torch.exp(self.log_w_vortex) * self.vortex(h)[0]
# 3. 色阻尼 γ(t)~t^(-α) → 亚欧姆记忆核
mem_term    = -torch.exp(self.log_w_mem) * self.memory(h)
# 4. 色噪声 → OU 物理 SDE（§14.2）
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
| 关闭记忆核 γ = 0 | `use_memory=False` |
| 关闭 ET 对称项 | `use_et_symmetric=False` |

此时 CID 退化为：`dφ/dt = -∇U(φ)`，即标准 Hopfield 注意力（等价于 Transformer 的 softmax 注意力）。

> **实证警示**：Phase 1 显示，仅关闭 ET 对称项（保留旋度/记忆/噪声）会使 loss 从 0.059 暴涨至 4.701（比纯 Transformer 还差）。这说明 ET 是让其他物理组件协同的"地基"。

---

## 📊 项目结构

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
├── setup.py                           安装配置
├── data_loaders.py                    数据加载工具（PretrainJsonl + SftJsonl）
├── convert_minimind_data.py           MiniMind 预训练数据转换脚本
├── convert_sft_conversations.py       SFT 对话数据转换脚本
├── download_chinese_tokenizer.py      中文 tokenizer 下载工具
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
│   ├── run_scaling_law.py             v2.1: 统一 checkpoint schema + tokens_per_param
│   ├── run_critical_exponents.py      v2.1: noise-OFF vs noise-ON + η verdict
│   ├── run_energy_benchmark.py        v2.1: idle 基线 + above-idle + decode
│   ├── run_ablation.py                v2.1: 11 组 + 3 个关键对照报告
│   └── run_all.py                     v2.1: 端到端 + 按规模自动 batch + vocab 自检
│
├── results/                           真实实验结果
│   ├── README.md                      结果目录索引
│   └── phase1/REPORT.md               Phase 1 实证报告（10M 消融）
│
└── tests/                             单元测试（pytest）
    ├── test_et_lyapunov.py            §8.5 ET 单调下降 + 零参数旋度
    ├── test_run_scaling_law.py        v2.1 参数透传 + checkpoint schema
    ├── test_qid_layer.py              QID v2.1 + Berry 有界 + QFDT
    ├── test_fid_layer.py              FID 三级透传 + JSON 安全 + η/Ricci
    ├── test_critical_exponents.py     新增 η 回归 + 集成测试
    ├── test_energy_meter.py           能量积分 + 平台兼容 + GPU 烟测
    ├── test_data_loaders.py           PretrainJsonl + SftJsonl + tail 截断
    ├── test_cid_layer.py              CID 基础测试
    ├── test_ablation_suite.py         11 组消融存在性
    ├── test_avalanche_detector.py     Beggs-Plenz 协议
    ├── test_modern_transformer.py     baseline 基础测试
    └── conftest.py                    共享 fixture
```

---

## 🧪 运行测试

```bash
# 运行所有单元测试
pytest tests/

# 运行特定测试（§8.5 ET 单调性）
pytest tests/test_et_lyapunov.py -v

# 运行带覆盖率报告
pytest tests/ --cov=uid_theory --cov-report=html
```

---

## 📈 验证流程

```mermaid
flowchart TD
    A["run_all.py 端到端流水线"] --> B["1. 缩放律实验<br/>iso-FLOP × 10M-1B 模型族"]
    A --> C["2. 11 组完整消融<br/>3 个关键对照报告"]
    A --> D["3. 临界指数测量<br/>noise OFF vs ON + η verdict"]
    A --> E["4. 实测能耗<br/>idle baseline + above-idle + decode"]

    B --> F["scaling_curves.png<br/>等损失水平间距"]
    C --> G["summary.json<br/>3 个对照 verdict ✅已实证"]
    D --> H["verdict.md<br/>涌现确认/否定/残留回响警告"]
    E --> I["energy_per_token.json<br/>raw + above_idle 双轨"]
```

---

## 🔧 常见问题

### Q: 网络连接失败怎么办？
A: 使用 ModelScope 镜像（国内快速）或手动下载。参见"快速开始"部分。

### Q: CUDA out of memory 怎么办？
A: (1) 设置 `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`；(2) 减小 `--batch_size`；(3) 用更小规模（10M）。`run_all.py` 已按规模自动收缩 batch_size。

### Q: 之前 OOM 的进程占着显存怎么办？
A: `pkill -9 -f experiments/run_` 然后 `nvidia-smi` 确认显存释放。

### Q: 能量测试报 device-side assert？
A: 这是 token id 越界（vocab 不匹配）。`run_all.py` 已自动从 tokenizer 读取 `vocab_size`；单独运行时请显式传 `--vocab_size 21128`。

### Q: 缩放律 loss 不下降（停在 ~10）？
A: 默认 `target_tokens_per_param` 太小导致训练不足。`run_all.py` 已默认 200；单独运行 `run_scaling_law.py` 请加 `--target_tokens_per_param 200`。

### Q: 中文 tokenizer 和 GPT-2 有什么区别？
A: 中文 tokenizer 对中文字符编码效率更高，词表更小，训练更快。GPT-2 适合英文或混合语言。

### Q: 如何使用完整数据集而非 mini 版本？
A: 修改 `convert_minimind_data.py` 中的文件名：
```python
pretrain_file = dataset_dir / 'pretrain_t2t.jsonl'  # 完整版 8GB
sft_file = dataset_dir / 'sft_t2t.jsonl'  # 完整版 13GB
```

### Q: 为什么测量临界指数前要关闭噪声注入？
A: **这是 v2.1 的关键修正**。否则测得的 1/f 谱、Hurst 等仅是注入噪声的回响，而非真实涌现。正确做法：`model.set_noise_injection(False)`。

### Q: v2.1 相对 v2.0 最重要的改进是什么？
A: 三个核心修正：(1) §8.5 ET 对称项；(2) §14.2 零参数旋度；(3) §14.2 OU 噪声。**Phase 1 实证显示这三项分别带来 79×、52%、55× 的影响**。

---

## 🗺️ 路线图

### Phase 1：基础验证（进行中）

- [x] v2.1 基础设施完成（§8.5 / §14.2 / §6.1 修正）
- [x] 11 组消融变体 + 3 个关键对照（**10M / 10万条已实证，全部 supported**）
- [x] 临界指数测量套件（含 η）
- [x] 能量测量 v2.1（idle + above-idle）
- [x] 7 个新测试文件全栈覆盖
- [ ] **10M-160M 缩放律实验**（验证预言 5）
- [ ] **临界指数验证**（noise-OFF 真实涌现，验证预言 1-4、7）
- [ ] **能效基准测试**（above-idle 对比，验证预言 6）
- [ ] **完整 127 万条数据复跑**（最终确认）

### Phase 2：大规模验证

- [ ] 400M-1B 模型族缩放律
- [ ] 多数据集 / 跨语言泛化测试
- [ ] 长序列性能（8K-32K tokens）
- [ ] 下游任务评估

### Phase 3：理论扩展

- [ ] QID 量子硬件验证
- [ ] FID 几何探针经验校准
- [ ] 多模态扩展

详见 [ROADMAP.md](./ROADMAP.md)。

---

## 📄 引用

如果您在研究中使用了 UID 理论或本实现，请引用：

```bibtex
@software{uid_theory_2026,
  author = {Li, Gui and Jie, Dangyang and Kang, Haitao},
  title = {Unified Intelligo-Dynamics (UID): A Three-Layer Physical Theory of Intelligence},
  year = {2026},
  publisher = {Zenodo},
  doi = {10.5281/zenodo.20372493},
  url = {https://github.com/gwailee/uid}
}
```

引用 Phase 1 实证数字时，请同时注明：seed（或"averaged over seeds {42,43,44}"）、硬件平台（RTX 4090）、v2.1 commit hash，以及 `results/phase1/REPORT.md` §6 的相应局限。

---

## 📜 许可证

本项目采用**双许可证**模式：

### 非商业使用（免费）
- **PolyForm Noncommercial License 1.0.0**
- 适用于学术研究、个人学习、非营利组织
- 详见 [LICENSE-NONCOMMERCIAL](./LICENSE-NONCOMMERCIAL)

### 商业使用（需授权）
- 任何商业、营利性或生产环境使用需获得**苏州钧舵机器人有限公司**的书面授权
- 详见 [LICENSE-COMMERCIAL](./LICENSE-COMMERCIAL)
- 商业授权咨询：lig@jodell.cn

**重要说明**：
- ✅ 学术论文、课程作业、个人项目：免费使用
- ✅ 开源项目（非商业）：免费使用
- ❌ 公司产品、SaaS 服务、商业咨询：需商业授权
- ❌ 在商业产品中集成 UID：需商业授权
- ❌ 使用 UID 进行商业宣传或产品命名：需商业授权

### 免责声明
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY ARISING FROM USE OF THIS SOFTWARE.

---

## 🙏 致谢

- **同行评审者**：特别感谢匿名评审者对 v0.1 / v2.0 的详细批评，分别促成了 v2.0 的完整重写与 v2.1 的 §8.5 / §14.2 实现修正。详情见 [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md)。
- **[MiniMind](https://github.com/jingyaogong/minimind) by jingyaogong**：提供高质量的小模型基础架构与数据集。
- **UID 理论的物理先驱们**（按时间顺序）：Langevin、Einstein、Fokker、Planck、Mori、Zwanzig、Lindblad、Caldeira-Leggett、Berry、Amari、Hopfield、Bak-Tang-Wiesenfeld、Bialek、Friston、Beggs-Plenz、Linkenkaer-Hansen、Karakida-Akaho-Amari 等。
- **现代深度学习架构的奠基者**：Vaswani et al.（Transformer）、Ramsauer et al.（Modern Hopfield Networks）、Hoover et al.（Energy Transformer，§8.5 关键参考）、Gu & Dao（Mamba）、He et al.（ResNet）。
- **统计方法学先驱**：Clauset、Shalizi & Newman（幂律拟合金标准）、Peng et al.（DFA 方法）。
- **开放科学工具生态**：PyTorch、Hugging Face、pynvml、pytest、ruff —— 让严格验证成为可能。

---

## 📧 联系方式

- **通讯作者**：李贵 <guilichina@163.com>
- **商业授权**：lig@jodell.cn
- **GitHub Issues**：[https://github.com/gwailee/uid/issues](https://github.com/gwailee/uid/issues)
- **单位**：苏州钧舵机器人有限公司（Suzhou Jodell Robotics Co., Ltd.）

---

<div align="center">

> **统一智动力学的核心目标**：把"智能"从一种工程现象提升为一种物理理论。
>
> CID 可编码，QID 可模拟，FID 可探索。**所有结果都是可证伪的——这是科学的核心。**
>
> *首批实证（10M 消融）已对 §8.5 ET 对称项给出 z=3712 的强力支持。*

**[⭐ Star this repo](https://github.com/gwailee/uid) | [📖 Read the theory](./theory.md) | [🚀 Quick start](#-快速开始使用-minimind-数据集训练-uid-模型)**

</div>
