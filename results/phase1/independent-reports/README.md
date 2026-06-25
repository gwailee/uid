# UID 复现结果包

- **复现人**：赵星宇
- **单位**：合肥综合性国家科学中心能源研究院中子技术应用研究中心
- **复现对象**：`gwailee/uid`（commit `53f2aa06`），CID vs Transformer（10M / 10万条）

## 目录说明

| 路径 | 内容 |
|---|---|
| `REPRODUCTION_zh.md` / `REPRODUCTION_en.md` | 复现报告（中 / 英），先看这两个 |
| `outputs/combined_summary.json` | 消融 3-seed 聚合（CID vs Transformer = **3.11×, z=182**）|
| `outputs/sl200_3seed_summary.json` | 缩放律充分训练 3-seed（**3.94× ± 0.03 ≈ 4:1**，核心结论）|
| `outputs/scaling_summary.json` | 缩放律 tpp=20（10M+30M 规模趋势）|
| `outputs/energy_summary.json` · `outputs/energy/` | 能耗基准（等参数 +20%；iso-PPL 此规模不可判定）|
| `outputs/critical_exponents/results.json` | 临界指数（verdict = `emergence_not_confirmed`）|
| `outputs/infer_efficiency/` | 推理吞吐 / 延迟 |
| `outputs/ablation_100k_seed{42,43,44}/` | 消融逐 seed 原始结果 |
| `outputs/sl200_*/` · `outputs/sl_*/` | 缩放律逐 family/seed 原始结果 |
| `outputs/minimind_100k/` | 仓库自带官方对照基线（用于一致性核对）|
| `outputs/provenance/` | 溯源：代码版本 / 依赖版本 / 数据 md5 / GPU |
| `outputs/logs/` | 全部运行日志 |

> 说明：本包不含模型权重 `.pt`（合计约 880MB，属中间产物），如需可另行索取。所有指标数值均可由上述 JSON 与报告中的命令复算。
