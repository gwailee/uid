<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-30
UPDATE: 2026-06-24 (v2.3 — 多尺度消融 + ET 非因果结构性结论 + 第三方复现)

This README is part of the UID Theory reference implementation (v2.3).

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

## ⚠️ 重要提示：v2.3 诚实版本说明

**本仓库当前为 v2.3（诚实验证版 · 多尺度消融完成版）**，在 v2.2 基础上完成 **10M/30M/100M 三尺度消融**、修复了 **ET 项与因果性的根本冲突**，并收录**第三方独立复现**：

| v2.3 关键进展 | 对应理论章节 / 修复点 |
|---|---|
| 完成 **10M/30M/100M 三尺度消融**（3 seeds），比值随规模放大 3.12→3.71→4.09× | T1 / T2（方向） |
| **ET 对称项被证明本质非因果**：其对称第二项要求 key 依赖未来 query（实测泄漏 ~0.11），与自回归因果性数学不可兼容；因果 LM 下**舍弃该项，ET 退化为标准注意力** | §8.5 |
| 临界指数工具链修三处 bug（噪声OFF/ON 退化→shuffle 替代；η 病态→全局协方差；Hurst 差分补偿错误→标准 DFA-2，surrogate H=0.519 验证）| §6.1 |
| 能耗改用全局稳健 idle 基线 + iso-parameter/iso-performance 三视图 | §0.1 / §13 |
| 收录第三方独立复现（赵星宇）| §16.9 |

v2.3 版本：
- ✅ **T1（核心论断）强支持，且优势随规模放大**：多尺度消融中 cid_full/transformer 困惑度比 **3.12×（10M）→3.71×（30M）→4.09×（100M）**；**cid_full 在 10M（~4.8M 参数）即优于 transformer 在 100M（~49M 参数）**——约 **1/10 参数**胜出，方向性地支持 5–10× 参数效率
- ✅ **"注意力并不够"跨三尺度复现**：堆叠已知技巧在每个尺度均无效（<1%）
- ✅ **§14.2 OU 噪声支持**（幅度随规模变化：10M 约 7×、100M 约 1.24×）
- ✅ **记忆核为主导物理项**（各尺度移除均 +15~22%）
- ✅ **F4 Hurst 支持**：H=0.803 ∈ [0.6,0.8]，surrogate 0.519 验证真实长程相关
- ❌ **F3 β 证伪**（0.572 略低）、**F5 雪崩证伪**（非幂律）
- ⚠️ **F6 η 无区分力**（0.997 ≈ 基线 0.998，指标饱和）
- 🔧 **F8 ET 项**：v2.3 证明 **ET 对称项在因果 LM 中不可实现**（非因果），据此舍弃；`cid_full ≡ cid_full_no_et`。这**取代** v2.2 的"F8 证伪"——正确结论是 **CID 的优势全部来自其三个因果安全的物理项，ET 在此不适用**
- ⏳ **等算力多尺度标度曲线（F1/F2）与 iso-PPL 能耗（F7）**列入 Phase 1b（H100）——这是 T2 与 C13 的**判决点**
- 🎯 承诺**公开发布所有结果**（无论正面还是负面）

**证伪一个理论与证实它同等有价值**——这是科学进步的根本原则。

---

## 🧪 首批实证结果（Phase 1 · v2.3 · 2026-06-24）

> **状态**：SUBSTANTIALLY COMPLETE（多尺度消融 + 临界指数 + 解码能耗完成；等算力标度曲线 F1/F2 与 iso-PPL 能耗 F7 列入 Phase 1b）
> **数据集**：MiniMind 中文预训练语料 10 万条子集（约 1000 万 tokens）· **种子**：[42,43,44] · **硬件**：RTX 4090（Phase 1b 用 H100）
> 完整报告见 [`results/phase1/REPORT.md`](./results/phase1/REPORT.md)。

### 头条结论：框架优势随规模放大，CID 用约 1/10 参数胜出（T1 强支持）

多尺度消融（memory_length=64，1 epoch，3 seeds）：

| 尺度 | cid_full 非嵌入参数 | cid_full 困惑度 | transformer 困惑度 | **困惑度比** |
|---|---|---|---|---|
| 10M | ~4.8M | **23.62** | 73.58 | **3.12×** |
| 30M | ~22.7M | **12.49** | 46.36 | **3.71×** |
| 100M | ~49.3M | **10.21** | 41.76 | **4.09×** |

**两个关键点**：
1. **比值随规模单调放大**（3.12→3.71→4.09×）——架构优势"越大越强"，与"基线追平"的失效模式相反。
2. **cid_full 在 10M（~4.8M 参数，困惑度 23.62）远优于 transformer 在 100M（~49M 参数，困惑度 41.76）**——即 CID 用约 **1/10 参数**已胜出，方向性地支持 5–10× 参数效率（T2）。

> ⚠️ 诚实标注：上表为**消融预算（1 epoch）**下的趋势，是 T2 的**方向性下界**，**非**严格判决；严格 T2 须等算力多尺度标度曲线（Phase 1b）。作为对照，充分训练（tpp=200）的 10M 单点为 cid_full 7.90 vs transformer 31.12（3.94×）。

### "注意力并不够"：跨三尺度复现

已知 Transformer 技巧（conv/linear/noise）在 10M/30M/100M 每个尺度增益均 <1%；`transformer_plus_tricks` 甚至不优于纯 transformer，却多耗约 2.3× 算力。CID 的优势不能归因于"堆叠更多技巧"。

### 消融归因：记忆核主导，ET 不适用于因果 LM

| 物理项 | 移除后困惑度变化（各尺度）| 结论 |
|---|---|---|
| 色阻尼记忆核 ∫γ | +21.7%（10M）/ +14.7%（30M）/ +14.8%（100M）| **单项贡献最大** |
| 旋度 v(φ) | +0.2~0.4% | 消融效应小；必要性应由临界指数检验（命题 C3.3）|
| 色噪声（存在性）| ~0% | 关键在类型（OU vs FFT），非存在 |
| OU → FFT 噪声 | 10M 约 7× / 100M 约 1.24× 更差 | OU 支持 §14.2（幅度随规模变化）|
| ET 对称项（§8.5）| `cid_full ≡ cid_full_no_et` | **ET 非因果、因果 LM 下不可实现，已舍弃**（见下）|

**关于 ET（原 F8）的 v2.3 结论**：ET 的对称第二项要求 key 位置依赖未来 query 位置，实测在因果 LM 中造成约 0.11 的未来 token 泄漏——**ET 的双向对称性与自回归因果性数学上不可兼容**。因此 v2.3 舍弃该项，`use_et_symmetric=True` 退化为标准因果注意力，`cid_full ≡ cid_full_no_et`。这**取代** v2.2 的"F8 证伪"：正确结论不是"ET 无用"，而是**"ET 不适用于因果 LM；CID 的优势全部来自其三个因果安全的物理项（旋度/记忆核/色噪声）"**。

### 临界指数（10M）：部分支持，且无法区分基线

> 修复工具后验证标定正确：shuffle 替代对照 Hurst=0.519≈0.5，谱拟合 R²=0.94。

| 指标（F#）| 预言区间 | `cid_full` | Transformer 基线 | 判定 |
|---|---|---|---|---|
| Hurst (F4) | [0.6, 0.8] | **0.803**（surrogate 0.519）| 0.813 | ✅ PASS |
| β 1/f (F3) | [0.7, 1.3] | 0.572（R²=0.94）| 0.709 | ❌ FAIL |
| 雪崩 τ (F5) | ~1.5 | 非幂律（p=0）| 非幂律 | ❌ FAIL |
| η (F6) | > 0.5 | 0.997 | 0.998 | ⚠️ 无区分力 |

**关键诚实点**：四个指数均无法区分 CID 与普通 Transformer——正如理论摘要预先申明。它们仅作"CID 表现出与生物大脑一致的临界统计特征"的描述性旁证，**不**构成 CID 优于 Transformer 的独立证据。

### 能耗（10M）：idle 修复后干净可测，iso-PPL 判决待多尺度

> 稳健共享 idle 基线 = 61.9W（离散 0.06W）。

| 家族 | 困惑度 | above-idle 能耗（mJ/token）| 相对基线 |
|---|---|---|---|
| transformer | 31.12 | **0.141** | 1.00× |
| cid_full | 7.90 | 0.160 | 1.13×（开销）|
| transformer_plus_tricks | 31.23 | 0.164 | 1.17× |

等参数下 CID 每 token 能耗仅多约 13%（且低于 tricks、参数最少），却换来约 3.9× 困惑度优势。**这是 iso-parameter 开销，非 C13 的 ≥3× 能效判决（F7）**——后者须多尺度 iso-PPL 曲线，列入 Phase 1b。

### Phase 1 证伪记分牌

| 判定 | 条件 |
|---|---|
| ✅ PASS（1）| F4 (Hurst) |
| ❌ FAIL（2）| F3 (β)、F5 (雪崩) |
| ⚠️ INCONCLUSIVE（1）| F6 (η) |
| 🔧 RESOLVED_not_realizable（1）| F8（ET 非因果、不可实现）|
| ⏳ ABSTAIN（3）| F1/F2（等算力曲线）、F7（iso-PPL）|

> 所有负面结果与正面结果同等篇幅呈现、永久保留。引用须附 v2.3 提交哈希及 [`REPORT.md`](./results/phase1/REPORT.md) §6 逐项注意事项。

### ✅ 第三方独立复现

本仓库 Phase 1 核心结果已由**赵星宇（合肥综合性国家科学中心能源研究院中子技术应用研究中心）**在独立环境下复现（commit `53f2aa06`，RTX 4090，3 seeds）。关键数值逐位吻合：消融对照 A **3.11×/z=182.2**；充分训练缩放律 **cid 7.89 / tf 31.12（3.94×±0.03）**。复现同等地验证了负面/中性结论（临界指数无法区分 CID 与 Transformer、等参数能耗 CID 高约 20%、推理吞吐 transformer 快约 27%、iso-PPL 能效不可判定），并独立发现若干工程问题（已据此修订）。完整报告见 [`results/phase1/independent-reports/`](./results/phase1/independent-reports/)（不含约 880MB 权重，可另行索取）。

> **致谢**：感谢赵星宇对本仓库 Phase 1 实验的独立复现与工程反馈。
> **说明**：复现使用 commit `53f2aa06`（早于 v2.3 的 ET 修正），其临界指数工具为修复前版本，故复现的 Hurst（0.77）与本仓库修正后值（0.803）略有差异，方向一致。

---

## 📦 这是什么

**UID（统一智动力学）** 把智能架构当作**远离热平衡的随机场**，从开放系统物理三条公理出发经 Mori-Zwanzig 投影推导出**广义 Langevin 方程**，并指出 Transformer、Mamba、扩散模型等都是其特定极限下的特解。本仓库提供 **CID 层工程参考实现**与**可证伪验证套件**：在标准注意力骨架上加入三个**因果安全**的物理项——**旋度 v(φ)、色阻尼记忆核 ∫γ、OU 色噪声 ξ**。

- 📄 理论全文：[`theory.md`](./theory.md) / [`theory_en.md`](./theory_en.md)
- 🧪 完整实验报告：[`results/phase1/REPORT.md`](./results/phase1/REPORT.md)

---

## 🚀 快速开始

```bash
git clone https://github.com/gwailee/uid.git && cd uid
pip install -e .
pip install modelscope transformers torch tqdm protobuf
# 依赖说明：经复现反馈，requirements.txt 的 typeguard 版本约束已修正；transformers 固定 <5.0

modelscope download --dataset gongjy/minimind_dataset --local_dir dataset
python convert_minimind_data.py
python -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('bert-base-chinese').save_pretrained('tokenizers/bert-base-chinese')"

head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# (a) 多尺度消融（10M/30M/100M）
for S in 10M 30M 100M; do
  python experiments/run_all.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale $S --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_100k \
    --skip_scaling --skip_critical --skip_energy
done

# (b) 缩放律家族训练（3 家族 × 3 seeds，tpp=200）
python experiments/run_scaling_law.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scales 10M --families transformer transformer_plus_tricks cid_full \
    --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --target_tokens_per_param 200 \
    --output_dir ./output/minimind_100k/scaling_law_v2.1

# (c) 临界指数（已修复工具链）
python experiments/run_critical_exponents.py \
    --checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/cid_full_10M_seed42.pt \
    --baseline_checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/transformer_10M_seed42.pt \
    --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
    --max_seq_len 512 --batch_size 4 --n_sequences 2000 --eta_max_samples 50000 \
    --output_dir output/minimind_100k/critical_exponents_v2.2.1

# (d) 解码能耗（seq_len + new_tokens <= max_seq_len）
python experiments/run_energy_benchmark.py \
    --families transformer cid_full transformer_plus_tricks \
    --checkpoint_dir output/minimind_100k/scaling_law_v2.1/checkpoints \
    --scale 10M --seeds 42 43 44 --batch_size 8 --seq_len 256 \
    --vocab_size 21128 --mode decode --new_tokens_per_decode 64 \
    --scaling_law_json output/minimind_100k/scaling_law_v2.1/results.json \
    --output_dir output/minimind_100k/energy_v2.2

# Phase 1b（H100，判决性 F1/F2/F7）：等算力多尺度缩放律 + iso-PPL 能耗
#   --scaling_scales 10M 30M 100M --target_tokens_per_param 200 --force_stage scaling energy
```

> **训练预算说明**：消融默认 `epochs=1`；`run_scaling_law.py` 默认 `tokens_per_param=20`；`run_all.py` 默认 `tokens_per_param=200`。不同入口预算不同、比值不同（消融 3.12× vs 充分训练 3.94×），引用时须注明口径。

---

## 🔬 可证伪预言与判决点

| # | 预言 | 等级 | Phase 1 状态 |
|---|---|---|---|
| **T1** | CID 物理项 > Transformer | C | ✅ 支持，随规模放大（3.12→4.09×，~1/10 参数胜出）|
| **T2** | 5–10× 参数效率（等算力多尺度）| C | ⏳ 方向性强支持，判决待 Phase 1b（F1/F2）|
| **C3.3** | 旋度必要性（预测蕴含非平衡）| B | 部分（临界指数无法区分基线）|
| **§14.2** | OU > FFT | C | ✅ 各尺度支持（幅度随规模变化）|
| **临界普适类** | τ≈1.5 / H≈0.7 / β≈1 | B | Hurst PASS；β/雪崩 FAIL；无基线区分 |
| **C13** | iso-PPL 下 ≥3× 能效 | C | ⏳ 待 Phase 1b（单尺度不可判定）|
| **ET §8.5** | ET 对称项 | 借自 Hoover 2023 | 🔧 非因果、因果 LM 不可实现，已舍弃 |

---

## 📚 引用

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

> 引用 Phase 1 结果请附 v2.3 提交哈希及 [`REPORT.md`](./results/phase1/REPORT.md) §6 逐项注意事项。

---

## 🙏 致谢

感谢赵星宇（合肥综合性国家科学中心能源研究院中子技术应用研究中心）对本仓库 Phase 1 实验的独立复现与工程反馈。

---

## 📄 许可证

本仓库采用**双许可证**：**PolyForm Noncommercial License 1.0.0**（学术/个人非商业，见 [`LICENSE-NONCOMMERCIAL`](./LICENSE-NONCOMMERCIAL)）＋**商业许可证**（商业用途须苏州钧舵机器人有限公司书面授权，见 [`LICENSE-COMMERCIAL`](./LICENSE-COMMERCIAL)）。商业咨询：lig@jodell.cn
