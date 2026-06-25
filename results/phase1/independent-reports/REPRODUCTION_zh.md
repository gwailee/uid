# 独立复现报告：CID vs Transformer 参数效率（10M / 100k）

> 本文是对 UID（Unified Intelligo-Dynamics）仓库 CID/Transformer 对比实验的一次**独立第三方复现**，目的是在全新环境下重新测量核心指标，并与仓库公开数值做一致性核对。所有数字均为本次实测，未引用未经复算的结论。

| 项 | 值 |
|---|---|
| 复现人 | 赵星宇 |
| 单位 | 合肥综合性国家科学中心能源研究院中子技术应用研究中心 |
| 复现对象 | `gwailee/uid`，commit `53f2aa06` |
| 模型规模 / 数据 | 10M 参数族 / MiniMind 预训练前 100,000 条 |
| 硬件 | NVIDIA RTX 4090 (24GB) |
| 种子 | 42 / 43 / 44 |

---

## 0. 结果速览

| 实验 | 指标 | 本次实测 | 仓库公开值 | 一致性 |
|---|---|---|---|---|
| 消融（单 epoch）| cid_full vs transformer eval_ppl | **3.12×**（cid 23.62 / tf 73.58）| ~3.1× | ✅ |
| 消融关键对照 A | cid_full vs transformer+tricks，z(eval_loss) | **3.11×，z=182.2** | 3.1×，z=182 | ✅ 逐位吻合 |
| 缩放律（充分训练 tpp=200）| cid_full vs transformer eval_ppl，3 seeds | **3.94× ± 0.03**（cid 7.89 / tf 31.12）| 3.94× | ✅ 逐位吻合 |
| 推理吞吐 | cid_full vs transformer | Transformer 快约 **27%** | —（仓库未直接给出）| 新增观测 |
| 能耗（等参数）| cid_full / transformer，每 token | **1.20×**（CID 高 20%）| prefill ~1.13× | ✅ 同向 |
| 能耗（等性能 iso-PPL / C13）| ≥3× 阈值裁决 | **不可在此规模判定** | 列为待办 | ✅ 同结论 |
| 临界指数 | 涌现判定 | **emergence_not_confirmed** | 标注为"待验证" | ✅ 同结论 |

**一句话结论**：CID 相对同参数量 Transformer 的"困惑度优势"是**训练强度的函数**——单 epoch 消融下约 **3.1×**，充分训练（tokens_per_param=200）下放大到 **3.94×（≈4×）**，跨 3 个种子方差极小。该优势是**参数效率**层面的；在原始推理吞吐与等参数能耗上 CID 反而略有开销。UID 的相变/涌现类物理预言在 10M 单点上**尚不能与普通 Transformer 区分**。

---

## 1. 环境与数据

### 1.1 依赖与版本

按 `requirements.txt` 建立独立虚拟环境。逐项核对时发现 **3 处打包问题**（见 §5），处理后最终版本全部落入官方约束区间：

```
torch 2.11.0+cu128   transformers 4.57.6 (<5.0)   numpy 1.26.4   scipy 1.17.1
datasets 4.8.4       matplotlib 3.10.9            protobuf 7.35.1  tqdm 4.67.3
```

导入自检：`get_ablation_configs()` 返回 **11** 个消融变体；`bert-base-chinese` tokenizer 加载成功，**vocab_size = 21128**。

### 1.2 数据准备

按官方文档流程：从 ModelScope `gongjy/minimind_dataset` 下载预训练语料 → `convert_minimind_data.py` 转为 `pretrain.jsonl` → 截取前 10 万条：

```bash
head -n 100000 data/minimind/pretrain.jsonl > data/minimind/pretrain_100k.jsonl
```

数据校验：

```
pretrain_100k.jsonl : 100,000 行 / 71 MB
md5                 : f27f4c15095f44ecd3388b4c0ef6169a
```

预处理（`data_loaders.PretrainJsonl`）：`bert-base-chinese` 分词，`max_length=512`；构造 causal-LM `labels`（pad → -100）；**9:1 train/eval 切分，切分种子固定为 `manual_seed(42)`**，与运行 seed 解耦——这保证不同 seed 的进程使用完全相同的 eval 集，结果可比、可合并。

---

## 2. 消融实验（核心：参数效率）

命令（每 seed 一个进程，三进程并行；与单进程顺序运行等价，因每个 (变体, seed) 训练前独立设种子）：

```bash
python experiments/run_ablation.py \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --scale 10M --epochs 1 --seeds 42 43 44 --batch_size 64 --max_seq_len 512 \
  --output_dir output/ablation_100k
```

### 2.1 全部 11 变体 eval_ppl（3 seeds）

| 排名 | 变体 | 参数量 | eval_ppl (mean ± std) | 梯队 |
|---|---|---|---|---|
| 1 | cid_full_no_et | 10.37M | **22.87 ± 0.17** | CID |
| 2 | cid_full | 10.37M | **23.62 ± 0.11** | CID |
| 3 | cid_no_vortex | 10.37M | 23.71 ± 0.20 | CID |
| 4 | cid_no_noise | 10.37M | 23.79 ± 0.04 | CID |
| 5 | cid_no_memory | 10.27M | 28.65 ± 0.26 | CID（去记忆核）|
| 6 | transformer_plus_conv | 10.62M | 72.81 ± 0.44 | Transformer |
| 7 | transformer_plus_all_tricks | 10.62M | 73.33 ± 0.72 | Transformer |
| 8 | transformer_plus_noise | 10.52M | 73.55 ± 0.14 | Transformer |
| 9 | transformer_plus_linear | 10.52M | 73.57 ± 0.13 | Transformer |
| 10 | transformer_baseline | 10.52M | **73.58 ± 0.20** | Transformer |
| 11 | cid_full_fft_noise | 10.37M | 157.28 ± 2.87 | CID（FFT 噪声，劣化）|

CID 梯队（22–29）与 Transformer 梯队（73）之间呈数量级分离，跨 seed std 极小。

### 2.2 CID vs Transformer 比值

| 口径 | TF ppl | CID ppl | 比值 | z(eval_loss) |
|---|---|---|---|---|
| 对照 A：transformer_plus_all_tricks / cid_full | 73.33 | 23.62 | **3.11×** | **182.2** |
| transformer_baseline / cid_full | 73.58 | 23.62 | 3.12× | 374.8 |

→ 单 epoch 训练下，CID 比同参数量 Transformer 的困惑度低约 **3.1 倍**，统计极显著。

### 2.3 物理项消融解读

- **记忆核**（去掉后 23.6→28.7，+21%）：贡献最大。
- **噪声类型**（OU 23.6 vs FFT 157.3）：OU 噪声远优于 FFT。
- **ET 对称项**（去掉后 23.62→22.87，略**降**）：在该因果 LM 设置下未带来工程收益。

---

## 3. 缩放律：充分训练下的参数效率

消融用单 epoch；缩放律用 `run_scaling_law.py` 的充分训练预算。注意训练预算的两个口径：

- `run_scaling_law.py` 自身默认 `tokens_per_param=20`（Chinchilla 最优）；
- `run_all.py` 端到端流水线默认 `tokens_per_param=200`（小数据集充分收敛）。

两者训练量相差 10 倍，得到不同的收敛水平与比值。下面分别给出。

### 3.1 tokens_per_param=200（充分训练，10M，3 seeds）

```bash
python experiments/run_scaling_law.py \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --scales 10M --families transformer transformer_plus_tricks cid_full \
  --seeds 42 43 44 --batch_size 64 --max_seq_len 512 --target_tokens_per_param 200
```

| family | 非嵌入参数 | eval_ppl（3 seeds）| mean ± std |
|---|---|---|---|
| transformer | 5.12M | 31.35 / 30.98 / 31.03 | **31.12 ± 0.16** |
| transformer_plus_tricks | 5.21M | 30.90 / 31.32 / 31.48 | 31.23 ± 0.24 |
| **cid_full** | 4.83M | 7.88 / 7.90 / 7.90 | **7.89 ± 0.01** |

**比值**：

| 口径 | 比值（3 seeds）|
|---|---|
| transformer / cid_full | **3.94× ± 0.03**（逐 seed 3.98 / 3.92 / 3.93）|
| (transformer+tricks) / cid_full | 3.96× ± 0.03 |

→ 充分训练下比值放大到 **3.94×（≈4×）**，且 cid_full 用的参数还**更少**（4.83M vs 5.12M），跨 seed 极稳定。

### 3.2 tokens_per_param=20（10M + 30M，规模趋势参考）

| scale | transformer | transformer+tricks | cid_full | TF / CID |
|---|---|---|---|---|
| 10M | 40.89 | 40.57 | 11.27 | 3.63× |
| 30M | 27.17 | 27.39 | 7.37 | 3.69× |

→ 欠训预算下比值偏低（3.6–3.7×），但随规模 10M→30M **略增**，方向上与"参数效率随规模提升"一致。该口径仅作规模趋势参考；充分训练口径见 §3.1。

> **关于训练强度**：CID 的困惑度优势随训练量增长（单 epoch 3.1× → 充分训练 3.94×）。要检验论文终期 5–10× 的预言，需要更大规模、严格等算力的多尺度标度曲线。

---

## 4. 推理效率与能耗

### 4.1 推理吞吐（prefill，`measure_inference_energy`）

| 模型 | 参数量 | 吞吐 (tok/s) | 延迟 (ms/fwd) |
|---|---|---|---|
| cid_full | 10.37M | 594,686 | 13.78 |
| transformer_baseline | 10.52M | **756,026** | **10.84** |
| transformer_plus_all_tricks | 10.62M | 606,504 | 13.51 |

→ 在原始推理吞吐上，**纯 Transformer 反而快约 27%**。CID 因叠加旋度 / 记忆核 / 色噪声三个算子，单次前向计算量更大。**这与参数效率是两个不同维度**：CID 赢在"同参数量下更聪明"，不在"推理更快"。

### 4.2 能耗基准（`run_energy_benchmark.py`，decode 模式）

干净空闲基线 idle = 69.97 W（3 窗口中位，波动 0.56 W）。

| family | 非嵌入参数 | above-idle mJ/token |
|---|---|---|
| cid_full | 4.83M | 265.26 |
| transformer | 5.12M | 221.69 |
| transformer_plus_tricks | 5.21M | 259.70 |

**等参数（VIEW 1，中性开销）**：cid_full / transformer = **1.20×**（CID 每 token 能耗高 20%，但参数少 6%）。与仓库 prefill 口径的 ~13% 同向，差异来自 decode 模式。属预期开销。

**等性能 iso-PPL（VIEW 3，C13 ≥3× 能效裁决）**：**无法在本规模判定**。脚本要求两族 ppl 区间重叠才能比较，但 10M–30M 下 transformer 最低仅 ~27、CID 已 ~7–11，**区间不相交**，脚本拒绝外推，对 cid_full 返回 `out of range`。这与仓库自述一致——10M Transformer 无法达到 CID 的困惑度，等性能能效比当前仅为偏向 CID 的**下界**，严格的 ≥3× 裁决需要更大规模的多尺度曲线。

---

## 5. 复现中发现的仓库问题

| # | 问题 | 影响 | 处理 / 建议 |
|---|---|---|---|
| 1 | `requirements.txt` 钉死 `typeguard>=4.15.0`，但 PyPI 该包最高仅 4.5.2 | `pip install -r requirements.txt` 直接失败 | 代码实际未引用 typeguard；安装 4.5.2 规避。**建议上游修正版本号** |
| 2 | `transformers` 上限 `<5.0`，新环境常预装 5.x | `PreTrainedModel/Config` 在 5.x 有破坏性改动 | 独立 venv 内固定到 4.57.6 |
| 3 | `protobuf>=7.35.0` 略高于部分发行版默认 | 轻微 | venv 内升级至 7.35.1 |
| 4 | 实验脚本 stdout 在 `nohup` 下被缓冲 | 难以实时观测进度 | 加 `python -u`；或以增量 `results.json` 作为进度信号 |
| 5 | `run_critical_exponents.py` 默认 `n_sequences=10000` 的下游 CPU 统计分析极慢 | 实测 >3h 未完成 | 降至 `n_sequences=100`（仍 6400 条序列样本）。**建议为该统计步骤提供采样上限或向量化** |
| 6 | 文档未突出：消融默认 `epochs=1`、`run_scaling_law` 默认 `tpp=20`、`run_all` 默认 `tpp=200` | 不同入口得到不同比值（3.1× vs 3.94×），易混淆 | 见 §3。**建议在 README 明确各入口的训练预算默认值** |

---

## 6. 临界指数（UID 相变/涌现预言）

```bash
python experiments/run_critical_exponents.py \
  --checkpoint <cid_full_10M_seed42.pt> --baseline_checkpoint <transformer_10M_seed42.pt> \
  --data_path data/minimind/pretrain_100k.jsonl --tokenizer_path tokenizers/bert-base-chinese \
  --max_seq_len 512 --n_sequences 100
```

| 测试 | Hurst H | β（谱斜率）| 雪崩 α | 幂律? | η |
|---|---|---|---|---|---|
| CID（noise-OFF）| 0.766 ± 0.14 | 0.513 | 2.819 | ✗ | 0.998 |
| CID（noise-ON）| 0.766 ± 0.14 | 0.513 | 2.819 | ✗ | 0.998 |
| Transformer（负对照）| 0.806 ± 0.11 | 0.639 | 2.524 | ✗ | 0.997 |
| shuffle surrogate | 0.519 | −0.001 | — | — | — |

**判定：`emergence_not_confirmed`**。逐项对照预言：

| 预言 | 理论区间 | 实测 | 结论 |
|---|---|---|---|
| Hurst H | 0.6–0.8 | 0.77（CID）/ 0.81（TF）| ✅ 落入 |
| 1/f 谱斜率 β | 0.7–1.3 | 0.51 / 0.64 | ❌ 偏低 |
| 雪崩指数 τ | 1.5 ± 0.2 | α≈2.5–2.8 且 KS 拒绝幂律 | ❌ 未确认 |
| Fisher 各向异性 η | 高 | 0.998 | ✅ |

要点：

1. surrogate 对照有效——打乱时间轴后 H 0.77→0.52、β 0.51→0，说明隐藏态长程相关结构是真实的、非偶然。
2. noise OFF vs ON 三项指标差异均为 0，即推理期色噪声注入未改变隐藏态统计——"噪声驱动涌现"在此规模无证据支持。
3. **CID 与 Transformer 的临界指数高度相近**，这些长程相关/各向异性特征并非 CID 独有。临界指数预言在 10M 单点上尚不能区分二者。
4. 该结论不影响 §2/§3 的参数效率结论——后者是稳健的（3.1–3.94×）。

---

## 7. 结论

1. **核心可复现**：在全新独立环境下，消融（11 变体 × 3 seeds）与充分训练缩放律（3 seeds）的关键数值与仓库公开值逐位吻合（对照 A 3.11× / z=182.2；缩放律 cid 7.89 / tf 31.12）。
2. **参数效率比值是训练强度的函数**：单 epoch 3.1×，充分训练（tpp=200）**3.94× ± 0.03**（≈4×），CID 参数更少、跨 seed 方差极小。
3. **维度区分**：CID 的优势是参数效率（同参数量更低困惑度），而非推理速度或等参数能耗——在后两者上 CID 反而有约 20–27% 的开销。
4. **物理项归因**：记忆核贡献最大；OU 噪声远优于 FFT；借用的 ET 对称项无工程收益。
5. **未决项（与仓库自述一致）**：等性能（iso-PPL）能效的 ≥3× 裁决、以及临界指数的涌现预言，在 10M 单点 / 10M–30M 区间均**不能成立或不可判定**，需更大规模、严格等算力的多尺度实验。

---

## 附录：可追溯数据

所有原始结果保存在复现工作目录的 `output/` 下（路径相对于工作目录）：

| 内容 | 路径 |
|---|---|
| 代码/环境/数据溯源 | `output/provenance/{git_head,pip_versions,data_checksum,gpu}.txt` |
| 消融原始（每 seed）/ 聚合 | `output/ablation_100k_seed{42,43,44}/results.json` · `output/combined_summary.json` |
| 缩放律 tpp=200（3 seeds）| `output/sl200_<family>_10M[_seed{43,44}]/results.json` · `output/sl200_3seed_summary.json` |
| 缩放律 tpp=20（10M+30M）| `output/sl_<family>_<scale>/results.json` · `output/scaling_summary.json` |
| 推理效率 / 能耗 | `output/infer_efficiency/infer_efficiency.json` · `output/energy/results.json` · `output/energy_summary.json` |
| 临界指数 | `output/critical_exponents/results.json` |

**逐 seed 原始 eval_ppl（消融，关键变体）**：

```
cid_full_no_et       [42,43,44] = [22.81, 23.10, 22.70]
cid_full             [42,43,44] = [23.76, 23.50, 23.59]
cid_no_memory        [42,43,44] = [28.74, 28.30, 28.91]
transformer_baseline [42,43,44] = [73.30, 73.66, 73.77]
cid_full_fft_noise   [42,43,44] = [160.83, 157.22, 153.80]
```

**逐 seed 原始 eval_ppl（缩放律 tpp=200）**：

```
transformer  [42,43,44] = [31.35, 30.98, 31.03]
cid_full     [42,43,44] = [ 7.88,  7.90,  7.90]
```

---

*本报告所有数值均为本次独立实测，可按上述路径与命令复算。*
