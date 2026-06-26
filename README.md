<!--
Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
Author: Gui LI <guilichina@163.com>
Date:   2026-05-30
UPDATE: 2026-06-22 (v2.2 — Phase 1 四类实验完成 + 第三方独立复现回填)

This README is part of the UID Theory reference implementation (v2.2).

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

## ⚠️ 重要提示：v2.2 诚实版本说明

**本仓库当前为 v2.2（诚实验证版 · Phase 1 四类实验完成版）**，在 v2.1 基础上**完成了完整 Phase 1 实证（消融 + 缩放律家族 + 临界指数 + 解码能耗），修复了能耗与临界指数测量工具链中的多处缺陷，并收录了独立第三方复现**：

| v2.2 关键进展 | 对应理论章节 / 修复点 |
|---|---|
| 完成 10M 缩放律家族训练（3 家族 × 3 seeds，充分训练 tpp=200）| T1 / T2 |
| 能耗测量改用**全局稳健 idle 基线**（修复此前 CID 124W / Transformer 211W 不可比的伪差异）| §0.1 / §11.4 |
| 能耗对比改为 **iso-parameter（中性）+ iso-performance（C13 判决）三视图**，拒绝外推 | §13 |
| 临界指数工具链修复三处 bug：噪声 OFF/ON 退化→改用 shuffle 替代对照；η 逐序列病态→改全局协方差；Hurst 差分补偿错误→改标准 DFA-2（surrogate H=0.519 验证标定）| §6.1 |
| 收录第三方独立复现（赵星宇），关键数值逐位吻合 | §16.9 |

v2.2 版本：
- ✅ 提供进行严格验证所需的**完整基础设施**（全栈测试覆盖）
- ✅ 完成理论 §8.5 ET 修正、§14.2 零参数旋度、§14.2 OU 噪声、§6.1 η 可测等所有承诺
- ✅ **Phase 1 四类实验全部完成**（消融、缩放律家族、临界指数、能耗；见下方"首批实证结果"）
  - ✅ **T1（核心论断）强支持**：充分训练后 CID 困惑度 **7.90** vs Transformer **31.12**，即 **3.94×**，且 CID 参数更少（4.83M vs 5.12M）、跨 seed 近零方差（std≈0.01）
  - ✅ **"注意力并不够"三次独立复现**：堆叠已知技巧无效（消融 <1%；缩放律中 `transformer_plus_tricks` 31.23 ≈ `transformer` 31.12，却多耗 2.3× 算力）
  - ✅ **§14.2 OU 噪声支持**：OU 比 FFT 优 **6.9×**（z=37）
  - ✅ **F4 Hurst 支持**：H=0.803 落入预言区间 [0.6,0.8]，且远高于 shuffle 替代（0.519），证明真实长程相关
  - ❌ **F3 β 证伪**：β=0.572 略低于 [0.7,1.3]
  - ❌ **F5 雪崩证伪**：尾部非幂律（KS p=0，α≈3.0；附测量有效性 caveat）
  - ⚠️ **F6 η 无区分力**：η=0.997>0.5 但与 Transformer 基线（0.998）几乎相同，指标饱和
  - ❌ **F8 ET 项证伪**：ET 对称项无正面贡献甚至轻微有害（−3.2%）；**注：理论已声明 ET 非 UID 原创，借自 Hoover 2023**
  - ⏳ **多尺度缩放律（F1/F2）与 iso-PPL 能耗（F7）尚未完成**——这是 T2（5–10× 参数效率）与 C13（≥3× 能效）的**唯一判决点**，列入 Phase 1b
- ✅ **已收录第三方独立复现**（关键数值逐位吻合，连负面结论一并复现）
- 🎯 承诺**公开发布所有结果**（无论正面还是负面）

**证伪一个理论与证实它同等有价值**——这是科学进步的根本原则。

---

## 🧪 首批实证结果（Phase 1 完整 · 2026-06-22）

> **状态**：SUBSTANTIALLY COMPLETE（消融 + 缩放律家族 + 临界指数 + 解码能耗已完成；多尺度缩放律 F1/F2 与 iso-PPL 能耗 F7 列入 Phase 1b）
> **数据集**：MiniMind 中文预训练语料 10 万条子集（约 1000 万 tokens）
> **规模**：10M 参数 · **种子**：[42, 43, 44] · **硬件**：NVIDIA RTX 4090 (24GB)
> **可复现命令**见"快速开始"§步骤 5。完整报告见 [`results/phase1/REPORT.md`](./results/phase1/REPORT.md)。

### 结论一：充分训练后，CID 的框架优势进一步放大（T1 强支持）

| 家族 | 非嵌入参数 | 困惑度（3 seeds 均值）| 相对 CID |
|---|---|---|---|
| `transformer` | 5,115,136 | **31.12** | 3.94× 差 |
| `transformer_plus_tricks` | 5,213,470 | **31.23** | 3.95× 差 |
| **`cid_full`** | **4,831,268** | **7.90**（std≈0.01）| — |

CID 用**更少的参数**把困惑度降至 7.90，比 Transformer（31.12）低 **3.94×**；优势随训练放大（消融阶段为 3.22×），且三 seed 近零方差。堆叠已知技巧（conv/linear/noise）无效，且 `transformer_plus_tricks` 多耗 2.3× 算力却更差——"注意力并不够"在第三次独立实验中复现。

### 结论二：消融——UID 原创物理项得到支持，借来的 ET 项被证伪

> 消融为单轮训练（1 epoch），口径为单尺度等参数困惑度比，**与上方充分训练的 3.94× 是不同训练预算**。

| 对照 | 含义（理论章节）| `cid_full` | 对照组 | 困惑度比 | z(eval_loss) | 判定 |
|---|---|---|---|---|---|---|
| **A** | CID 物理框架 vs 已知技巧（T1）| 23.62 | `transformer_plus_all_tricks` = 73.33 | **3.10×** | 182.19 | ✅ supported |
| **C** | §14.2 OU vs FFT 噪声 | 23.62 | `cid_full_fft_noise` = 169.93 | **6.87×** | 37.14 | ✅ supported |
| **B** | §8.5 ET 对称项（F8）| 23.62 | `cid_full_no_et` = 22.87 | 0.97× | −6.39 | ❌ **not_supported** |

其中**色阻尼记忆核是单项贡献最大的物理项**（移除使困惑度上升 21%）；ET 项的证伪只针对借来的非首创组件，移除后 CID 反而更好，"提纯"了优势归属。（注：对照 A 若以损失比计为 3.22×，以困惑度比计为 3.10×；两者口径不同，本仓库主结论统一采用充分训练缩放律的 **3.94×**。）

### 结论三：临界指数——部分支持，且无法区分 CID 与基线（与理论自述一致）

> 修复测量工具后验证标定正确：shuffle 替代对照 Hurst=0.519≈0.5，谱拟合 R²=0.94。

| 指标（F#）| 预言区间 | `cid_full` | Transformer 基线 | 判定 |
|---|---|---|---|---|
| **Hurst (F4)** | [0.6, 0.8] | **0.803**（surrogate 0.519）| 0.813 | ✅ **PASS** |
| **β 1/f (F3)** | [0.7, 1.3] | **0.572**（R²=0.94）| 0.709 | ❌ FAIL |
| **雪崩 τ (F5)** | ~1.5 | 非幂律（α≈3.0, p=0）| 非幂律 | ❌ FAIL |
| **η 各向异性 (F6)** | > 0.5 | 0.997 | 0.998 | ⚠️ 无区分力 |

**关键诚实点**：四个指数均无法区分 CID 与普通 Transformer——这正是理论摘要预先申明的（"这些普适指数区分力有限，难以把 CID 与其他临界模型区分开"）。它们支持"CID 表现出与生物大脑一致的临界统计特征"这一描述性旁证，但**不**构成 CID 优于 Transformer 的独立证据。

### 结论四：能耗——idle 修复后干净可测，iso-PPL 判决待多尺度

> 稳健共享 idle 基线 = 61.9W（窗口间离散 0.06W），修复了此前 CID/Transformer idle 差 87W 的伪差异。

| 家族 | 困惑度 | above-idle 能耗（mJ/token）| 相对基线 |
|---|---|---|---|
| `transformer` | 31.12 | **0.141** | 1.00× |
| **`cid_full`** | **7.90** | 0.160 | 1.13×（开销）|
| `transformer_plus_tricks` | 31.23 | 0.164 | 1.17× |

等参数下 CID 每 token 能耗仅多约 **13%**（且**低于** tricks、参数最少、峰值功率最低），却换来 **3.9×** 的困惑度优势——即"以 13% 的能耗代价换 3.9× 质量"。**须强调：这是 iso-parameter 开销，而非 C13 的 ≥3× 能效判决（F7）**；后者须在 transformer 曲线覆盖到 CID 困惑度的多尺度 iso-PPL 曲线上测量，单尺度无法检验，列入 Phase 1b。

### Phase 1 证伪记分牌

| 判定 | 条件 |
|---|---|
| ✅ PASS（1）| F4 (Hurst) |
| ❌ FAIL（3）| F3 (β)、F5 (雪崩)、F8 (借来的 ET) |
| ⚠️ INCONCLUSIVE（1）| F6 (η，无区分力) |
| ⏳ ABSTAIN（3）| F1/F2 (多尺度未跑)、F7 (单尺度 iso-PPL 无法测) |

> 所有负面结果与正面结果**同等篇幅呈现**，永久保留。引用本批结果须附 v2.2 提交哈希及 [`results/phase1/REPORT.md`](./results/phase1/REPORT.md) §6 列出的逐项注意事项。

### ✅ 第三方独立复现

本仓库 Phase 1 核心结果已由**赵星宇（合肥综合性国家科学中心能源研究院中子技术应用研究中心）**在独立环境下复现（基于 commit `53f2aa06`，10M 规模、3 个种子、RTX 4090，依官方 `requirements.txt` 与文档流程从头搭建）。

| 实验 | 复现实测 | 本仓库公开值 | 一致性 |
|---|---|---|---|
| 消融关键对照 A（z）| **3.11×，z=182.2** | 3.10×，z=182 | ✅ 逐位吻合 |
| 缩放律 tpp=200（3 seeds）| **3.94× ± 0.03**（cid 7.89 / tf 31.12）| 3.94× | ✅ 逐位吻合 |
| 等参数能耗（decode）| **1.20×**（CID 高 20%）| 1.13×（prefill 同向）| ✅ 同向 |
| iso-PPL 能效（C13）| **本规模不可判定** | 列为待办 | ✅ 同结论 |
| 临界指数涌现判定 | **emergence_not_confirmed** | 同（无法区分基线）| ✅ 同结论 |

复现不仅逐位吻合正面结论，也**同等复现了本仓库的负面与中性结论**（临界指数无法区分 CID 与 Transformer、等参数能耗 CID 反高约 20%、原始推理吞吐 Transformer 反快约 27%、iso-PPL 能效不可判定），并独立指出若干工程缺陷（依赖版本约束、临界指数统计采样上限、不同入口的训练预算默认值），本仓库已据此修订。

完整复现报告（中英）、聚合 JSON 与溯源信息见 [`results/phase1/independent-reports/`](./results/phase1/independent-reports/)（不含模型权重 `.pt`，约 880MB 中间产物，可另行索取；所有数值均可由该目录 JSON 与报告命令复算）。

> **致谢**：感谢赵星宇对本仓库 Phase 1 实验的独立复现与工程反馈。复现报告原文及全部聚合数据原样收录，包括与本仓库一致的负面结论。
> **说明**：复现使用 commit `53f2aa06`，其临界指数工具为 DFA 修复前版本，故复现的 Hurst（0.766）与本仓库修复后值（0.803）略有差异，但方向一致（均落入 [0.6,0.8] 且无法区分基线）。

---

## 📦 这是什么

**UID（统一智动力学）** 把智能架构当作**远离热平衡的随机场**来处理，从开放系统物理学三条公理出发，经 Mori-Zwanzig 投影推导出**广义 Langevin 方程**作为智能系统的一般演化结构，并据此指出主流架构（Transformer、Mamba、扩散模型等）都是其在特定极限下的特解。

本仓库提供 **CID（经典智动力学）层的工程参考实现**与一套**可证伪验证套件**：在标准注意力骨架上加入 UID 的三个物理项——**旋度 v(φ)、色阻尼记忆核 ∫γ、OU 色噪声 ξ**——并提供消融、缩放律、临界指数、能耗四类实验脚本。

- 📄 理论全文：[`theory.md`](./theory.md)（中）/ [`theory_en.md`](./theory_en.md)（英）
- ⏱️ 30 分钟速读：[`30minutes_report.md`](./30minutes_report.md)（中）/ [`30minutes_report_en.md`](./30minutes_report_en.md)（英）
- 🧪 完整实验报告：[`results/phase1/REPORT.md`](./results/phase1/REPORT.md)

---

## 🚀 快速开始

### 步骤 1：克隆与安装

```bash
git clone https://github.com/gwailee/uid.git
cd uid
pip install -e .
pip install modelscope transformers torch tqdm protobuf
```

> 依赖版本说明：经第三方复现反馈，`requirements.txt` 中 `typeguard` 的版本约束已修正；`transformers` 请固定在 `<5.0`（4.5x 验证可用）。

### 步骤 2：下载 MiniMind 数据集

```bash
modelscope download --dataset gongjy/minimind_dataset --local_dir dataset
```

### 步骤 3：转换数据格式

```bash
python convert_minimind_data.py
```

### 步骤 4：下载 BERT 中文分词器

```bash
python -c "from transformers import AutoTokenizer; \
AutoTokenizer.from_pretrained('bert-base-chinese').save_pretrained('tokenizers/bert-base-chinese')"
```

### 步骤 5：复现 Phase 1 实验

```bash
# 创建 10 万条子集
head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# (a) 消融（11 变体 × 3 seeds，单 epoch）
python experiments/run_all.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scale 10M --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --output_root ./output/minimind_100k \
    --skip_scaling --skip_critical --skip_energy

# (b) 缩放律家族训练（3 家族 × 3 seeds，充分训练 tpp=200）
python experiments/run_scaling_law.py \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
    --scales 10M --families transformer transformer_plus_tricks cid_full \
    --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
    --target_tokens_per_param 200 \
    --output_dir ./output/minimind_100k/scaling_law_v2.1

# (c) 临界指数（已修复工具链；n_sequences 取 2000 避免 OOM）
python experiments/run_critical_exponents.py \
    --checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/cid_full_10M_seed42.pt \
    --baseline_checkpoint output/minimind_100k/scaling_law_v2.1/checkpoints/transformer_10M_seed42.pt \
    --data_path data/minimind/pretrain_100k.jsonl \
    --tokenizer_path tokenizers/bert-base-chinese \
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
```

> **关于训练预算（重要）**：消融默认 `epochs=1`；`run_scaling_law.py` 自身默认 `tokens_per_param=20`（Chinchilla 最优）；`run_all.py` 端到端流水线默认 `tokens_per_param=200`（小数据集充分收敛）。不同入口的训练预算不同，会得到不同的优势比值（消融 3.1–3.22× vs 充分训练 3.94×），引用时请注明口径。

---

## 🔬 可证伪预言与判决点

| # | 预言 | 实证等级 | Phase 1 状态 |
|---|---|---|---|
| **T1** | CID 物理项使模型优于纯 Transformer | C（可证伪工程目标）| ✅ 支持（消融 3.22× / 缩放律 3.94×）|
| **T2** | 5–10× 参数效率（多尺度等算力）| C | ⏳ 待 Phase 1b（**唯一判决点之一**）|
| **C3.3** | 旋度必要性（预测蕴含非平衡）| B（理论严格待实证）| 部分（临界指数无法区分基线）|
| **§14.2** | OU 色噪声 > FFT 谱整形 | C | ✅ 支持（6.9×，z=37）|
| **临界普适类** | τ≈1.5 / H≈0.7 / β≈1 | B | Hurst 支持、β/雪崩未达、且无法区分基线 |
| **C13** | iso-PPL 下 ≥3× 能效 | C | ⏳ 待 Phase 1b（单尺度不可判定）|

> 真正具有区分力的判决点是 **T2（参数效率）** 与 **C13（能效）**；临界普适指数区分力有限（实测已证实无法区分 CID 与 Transformer），仅作描述性旁证。

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

> 引用 Phase 1 实验结果时，请附 v2.2 提交哈希及 [`results/phase1/REPORT.md`](./results/phase1/REPORT.md) §6 列出的逐项注意事项。

---

## 🙏 致谢

感谢赵星宇（合肥综合性国家科学中心能源研究院中子技术应用研究中心）对本仓库 Phase 1 实验的独立复现与工程反馈。

---

## 📄 许可证

本仓库采用**双许可证**：

- **PolyForm Noncommercial License 1.0.0**：免费用于学术 / 个人非商业用途，见 [`LICENSE-NONCOMMERCIAL`](./LICENSE-NONCOMMERCIAL)。
- **商业许可证**：任何商业 / 营利 / 生产用途须先获得苏州钧舵机器人有限公司书面授权，见 [`LICENSE-COMMERCIAL`](./LICENSE-COMMERCIAL)。

商业许可咨询：lig@jodell.cn