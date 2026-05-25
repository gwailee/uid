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

"""End-to-end UID validation driver, leveraging the MiniMind repo.

UID 理论端到端验证驱动脚本；基于 MiniMind 仓库的 tokenizer 与数据。

Usage / 使用方法:
    python test_uid_on_minimind.py --quick        # CPU smoke test
    python test_uid_on_minimind.py --full         # full run on single GPU
    python test_uid_on_minimind.py --skip-train   # only re-run validation

What it does / 脚本流程:
    1. Clone https://github.com/jingyaogong/minimind into ``./minimind/``
       if not present. 自动克隆 MiniMind 仓库。
    2. Load MiniMind's tokenizer (falling back to ``gpt2`` if missing).
       加载 MiniMind tokenizer，若缺失则回退到 gpt2。
    3. Use ``dataset/pretrain_hq.jsonl`` if present, else build a small
       synthetic dataset (for smoke-test only). 使用 MiniMind 数据集，
       缺失时构造合成数据。
    4. Train four ablation variants: ``transformer``, ``cid_no_vortex``,
       ``cid_no_noise``, ``cid_full``. 训练四个消融变体。
    5. Run the falsification tests on every variant and save outputs.
       对每个变体运行可证伪测试并保存结果。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

# Make the local packages importable irrespective of cwd.
# 无论当前工作目录是什么，确保本仓库的包可被导入。
ROOT: Path = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Local imports (after sys.path manipulation).
# 在 sys.path 设置之后再导入本地包。
from model.model_baseline import TinyTransformerLM  # noqa: E402
from model.model_uid import UIDConfig, UIDModel  # noqa: E402
from verification.prediction_test import (  # noqa: E402
    UIDPredictionTester,
)

# ----------------------------------------------------------------------
# Constants / 常量
# ----------------------------------------------------------------------
MINIMIND_REPO: str = "https://github.com/jingyaogong/minimind.git"
MINIMIND_DIR: Path = ROOT / "minimind"
DATASET_FILE: Path = MINIMIND_DIR / "dataset" / "pretrain_hq.jsonl"
TOKENIZER_DIR: Path = MINIMIND_DIR / "model" / "minimind_tokenizer"


# ----------------------------------------------------------------------
# Environment setup / 环境准备
# ----------------------------------------------------------------------
def ensure_minimind() -> None:
    """Clone MiniMind if absent.

    若 MiniMind 仓库不存在则克隆下来。
    """
    if MINIMIND_DIR.exists():
        print(f"[ok] MiniMind already present at {MINIMIND_DIR}")
        return
    print(f"[..] cloning MiniMind into {MINIMIND_DIR}")
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            MINIMIND_REPO,
            str(MINIMIND_DIR),
        ],
        check=True,
    )


def ensure_dataset(tokenizer) -> Path:
    """Return a usable dataset path; build a synthetic one if needed.

    返回可用的数据集路径；若 MiniMind 数据集缺失则构造合成数据。

    Args:
        tokenizer: A HF tokenizer used for synthetic-data fallback.

    Returns:
        Path to a JSONL file with one ``{"text": ...}`` per line.
    """
    target_dir = MINIMIND_DIR / "dataset"
    target_dir.mkdir(parents=True, exist_ok=True)
    if DATASET_FILE.exists() and DATASET_FILE.stat().st_size > 1024:
        print(f"[ok] dataset found at {DATASET_FILE}")
        return DATASET_FILE

    print(
        f"[!!] {DATASET_FILE} not found; generating synthetic dataset "
        f"for smoke-test only."
    )
    rng = np.random.default_rng(42)
    vocab = max(int(tokenizer.vocab_size) - 5, 10)
    lines: List[str] = []
    for _ in range(5000):
        length = int(rng.integers(64, 256))
        ids = rng.integers(5, vocab, size=length).tolist()
        text = tokenizer.decode(ids)
        lines.append(json.dumps({"text": text}, ensure_ascii=False))
    DATASET_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] synthetic dataset written: {DATASET_FILE} "
          f"({len(lines)} lines)")
    return DATASET_FILE


# ----------------------------------------------------------------------
# Dataset / 数据集
# ----------------------------------------------------------------------
class PretrainJsonl(Dataset):
    """Read a MiniMind-style ``pretrain_hq.jsonl`` file.

    读取 MiniMind 风格的预训练 JSONL 数据集。
    """

    def __init__(
        self,
        path: Path,
        tokenizer,
        max_length: int = 256,
        max_samples: int = 0,
    ) -> None:
        """Initialise the dataset.

        Args:
            path:        Path to the JSONL file. JSONL 文件路径。
            tokenizer:   HF tokenizer. 分词器。
            max_length:  Truncate / pad to this length. 序列上限长度。
            max_samples: If > 0, keep only the first N lines.
                         若 > 0 则仅保留前 N 条。
        """
        lines = Path(path).read_text(encoding="utf-8").strip().split("\n")
        if max_samples > 0:
            lines = lines[:max_samples]
        self.lines: List[str] = lines
        self.tokenizer = tokenizer
        self.max_length: int = int(max_length)

    def __len__(self) -> int:
        return len(self.lines)

    def __getitem__(self, index: int) -> Dict[str, torch.Tensor]:
        text = json.loads(self.lines[index]).get("text", "")
        encoded = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        ids = encoded["input_ids"][0]
        labels = ids.clone()
        # Mask out padding so it does not contribute to the loss.
        # 屏蔽 padding 位置，使其不参与损失计算。
        labels[labels == self.tokenizer.pad_token_id] = -100
        return {"input_ids": ids, "labels": labels}


# ----------------------------------------------------------------------
# Model factory / 模型工厂
# ----------------------------------------------------------------------
def build_models(
    vocab_size: int,
    hidden_size: int,
    num_layers: int,
    num_heads: int,
    max_len: int,
) -> Dict[str, nn.Module]:
    """Build the four ablation models.

    构造四个消融模型。

    Returns:
        Mapping name -> model instance with the same I/O contract.
        模型名 -> 模型实例的映射，所有模型 I/O 一致。
    """
    common = dict(
        vocab_size=vocab_size,
        hidden_size=hidden_size,
        num_hidden_layers=num_layers,
        num_attention_heads=num_heads,
        max_position_embeddings=max_len,
    )
    return {
        "transformer": TinyTransformerLM(
            vocab_size=vocab_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            num_heads=num_heads,
            max_position_embeddings=max_len,
        ),
        "cid_no_vortex": UIDModel(
            UIDConfig(use_vortex=False, **common)
        ),
        "cid_no_noise": UIDModel(
            UIDConfig(use_colored_noise=False, **common)
        ),
        "cid_full": UIDModel(UIDConfig(**common)),
    }


# ----------------------------------------------------------------------
# Training / 训练
# ----------------------------------------------------------------------
def train_one_model(
    model: nn.Module,
    train_loader: DataLoader,
    eval_loader: DataLoader,
    device: str,
    name: str,
    lr: float,
    epochs: int,
    save_path: Path,
    log_every: int = 50,
) -> Dict[str, Any]:
    """Train a single model and return its statistics.

    训练单个模型并返回统计信息。
    """
    model.to(device)
    optim = torch.optim.AdamW(
        model.parameters(), lr=lr, weight_decay=0.01
    )
    n_params = int(sum(p.numel() for p in model.parameters()))
    print(f"[{name}] params = {n_params / 1.0e6:.2f}M, training...")
    start = time.time()
    history: Dict[str, List[float]] = {
        "train_loss": [],
        "eval_ppl": [],
    }

    for epoch in range(epochs):
        model.train()
        running_loss = 0.0
        running_tokens = 0
        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device)
            labels = batch["labels"].to(device)
            optim.zero_grad()
            out = model(input_ids=input_ids, labels=labels)
            if out.loss is None or torch.isnan(out.loss):
                print(f"  [{name}] skipping NaN loss at step {step}")
                continue
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            ntok = int((labels != -100).sum().item())
            running_loss += float(out.loss.item()) * ntok
            running_tokens += ntok
            if step % log_every == 0:
                print(
                    f"  [{name}] ep{epoch} step{step}/{len(train_loader)} "
                    f"loss={float(out.loss.item()):.3f}"
                )
        history["train_loss"].append(
            running_loss / max(running_tokens, 1)
        )

        # Evaluate / 评估
        model.eval()
        eval_loss = 0.0
        eval_tokens = 0
        with torch.no_grad():
            for batch in eval_loader:
                input_ids = batch["input_ids"].to(device)
                labels = batch["labels"].to(device)
                out = model(input_ids=input_ids, labels=labels)
                ntok = int((labels != -100).sum().item())
                eval_loss += float(out.loss.item()) * ntok
                eval_tokens += ntok
        ppl = float(np.exp(eval_loss / max(eval_tokens, 1)))
        history["eval_ppl"].append(ppl)
        print(
            f"  [{name}] ep{epoch}  train_loss="
            f"{history['train_loss'][-1]:.3f}  eval_ppl={ppl:.2f}"
        )

    elapsed = time.time() - start
    torch.save(
        {
            "model": model.state_dict(),
            "history": history,
            "n_params": n_params,
            "time": elapsed,
        },
        save_path,
    )
    return {
        "model": model,
        "history": history,
        "n_params": n_params,
        "time": elapsed,
        "final_ppl": history["eval_ppl"][-1],
    }


# ----------------------------------------------------------------------
# Reporting / 报告
# ----------------------------------------------------------------------
def write_plot(results: Dict[str, Any], save_to: Path) -> None:
    """Save a multi-panel summary plot.

    将所有指标汇总绘制为多面板对比图。
    """
    import matplotlib.pyplot as plt  # local import keeps headless safe

    val = results["validation"]
    train = results["training"]
    names = list(train.keys())

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    # 1. PPL.
    ax = axes[0, 0]
    ppls = [train[n]["final_ppl"] for n in names]
    ax.bar(names, ppls)
    ax.set_title("Eval perplexity (lower is better)")
    for i, value in enumerate(ppls):
        ax.text(i, value, f"{value:.2f}", ha="center", va="bottom")

    # 2. Param count.
    ax = axes[0, 1]
    params = [train[n]["n_params"] / 1.0e6 for n in names]
    ax.bar(names, params)
    ax.set_title("Parameters (M)")

    # 3. tau.
    ax = axes[0, 2]
    taus = [
        val.get(n, {}).get("avalanche", {}).get("tau", float("nan"))
        for n in names
    ]
    ax.bar(names, taus)
    ax.axhline(1.5, color="red", linestyle="--", label="theory τ=1.5")
    ax.set_title("Avalanche exponent τ")
    ax.legend()

    # 4. Hurst H.
    ax = axes[1, 0]
    hs = [
        val.get(n, {}).get("hurst", {}).get("hurst", float("nan"))
        for n in names
    ]
    ax.bar(names, hs)
    ax.axhspan(0.6, 0.8, alpha=0.2, color="green",
               label="theory H∈[0.6,0.8]")
    ax.set_title("Hurst exponent H")
    ax.legend()

    # 5. beta.
    ax = axes[1, 1]
    betas = [
        val.get(n, {})
        .get("power_spectrum", {})
        .get("beta", float("nan"))
        for n in names
    ]
    ax.bar(names, betas)
    ax.axhspan(0.7, 1.3, alpha=0.2, color="green",
               label="theory β∈[0.7,1.3]")
    ax.set_title("Power-spectrum slope β")
    ax.legend()

    # 6. Text summary.
    ax = axes[1, 2]
    ax.axis("off")
    lines = ["UID validation summary", "=" * 40]
    for n in names:
        lines.append(f"\n[{n}]")
        for key, payload in val.get(n, {}).items():
            if not isinstance(payload, dict):
                continue
            if "error" in payload:
                lines.append(f"  ! {key}: {payload['error']}")
                continue
            flag = "PASS" if payload.get("within") else "FAIL"
            primary_key = next(
                (
                    k
                    for k in ("tau", "hurst", "beta", "param_ratio")
                    if k in payload
                ),
                None,
            )
            primary_val = payload.get(primary_key, "n/a")
            lines.append(
                f"  [{flag}] {key}: {primary_key}={primary_val}"
            )
    ax.text(
        0.0,
        1.0,
        "\n".join(lines),
        va="top",
        family="monospace",
        fontsize=9,
    )

    fig.tight_layout()
    fig.savefig(save_to, dpi=120, bbox_inches="tight")
    print(f"[ok] summary plot saved to {save_to}")


def print_summary(results: Dict[str, Any]) -> None:
    """Pretty-print the final summary to stdout.

    向标准输出打印精简的最终摘要。
    """
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    train = results["training"]
    val = results["validation"]
    for name, payload in train.items():
        print(f"\n[{name}]")
        print(f"  params  : {payload['n_params']:,}")
        print(f"  eval PPL: {payload['final_ppl']:.2f}")
        print(f"  time    : {payload['time']:.1f}s")
        per_model = val.get(name, {})
        for key, theory_str in (
            ("avalanche", "tau -> 1.5"),
            ("hurst", "H in [0.6, 0.8]"),
            ("power_spectrum", "beta in [0.7, 1.3]"),
            ("efficiency", "param_ratio >= 5"),
        ):
            if key not in per_model:
                continue
            entry = per_model[key]
            if "error" in entry:
                print(f"  {key:16s}: ERROR {entry['error']}")
                continue
            primary_key = next(
                (
                    k
                    for k in ("tau", "hurst", "beta", "param_ratio")
                    if k in entry
                ),
                None,
            )
            flag = "PASS" if entry.get("within") else "FAIL"
            print(
                f"  {key:16s}: {primary_key}="
                f"{entry.get(primary_key, 'n/a')}  ({theory_str})  {flag}"
            )


# ----------------------------------------------------------------------
# Main entry point / 主入口
# ----------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    解析命令行参数。
    """
    parser = argparse.ArgumentParser(
        description="UID theory end-to-end validation on MiniMind."
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="CPU smoke test, ~5 minutes. CPU 极速冒烟测试。",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full GPU run, ~1-2 hours on RTX 3090. 完整 GPU 测试。",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip training; load checkpoints. 跳过训练，加载检查点。",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "uid_results"),
        help="Output directory. 输出目录。",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed. 随机种子。"
    )
    return parser.parse_args()


def resolve_config(args: argparse.Namespace) -> Dict[str, int]:
    """Map CLI flags to training hyperparameters.

    将命令行选项映射为训练超参数。
    """
    if args.quick:
        return dict(
            hidden_size=128,
            n_layer=4,
            n_head=4,
            max_len=128,
            batch=8,
            epochs=1,
            lr=3e-4,
            max_samples=400,
        )
    if args.full:
        return dict(
            hidden_size=512,
            n_layer=8,
            n_head=8,
            max_len=256,
            batch=16,
            epochs=3,
            lr=3e-4,
            max_samples=10000,
        )
    # default / 默认中等规模
    return dict(
        hidden_size=256,
        n_layer=6,
        n_head=8,
        max_len=256,
        batch=16,
        epochs=1,
        lr=3e-4,
        max_samples=2000,
    )


def main() -> None:
    """Drive the end-to-end experiment.

    端到端实验主流程。
    """
    args = parse_args()
    cfg = resolve_config(args)
    torch.manual_seed(int(args.seed))
    np.random.seed(int(args.seed))
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[info] device = {device}")
    print(f"[info] config = {cfg}")

    # 1. Prepare MiniMind and tokenizer.
    ensure_minimind()
    from transformers import AutoTokenizer

    if TOKENIZER_DIR.exists():
        tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR))
    else:
        print(
            f"[!!] tokenizer dir {TOKENIZER_DIR} missing; falling back "
            f"to 'gpt2'"
        )
        tokenizer = AutoTokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    vocab_size = int(tokenizer.vocab_size)

    # 2. Dataset.
    data_path = ensure_dataset(tokenizer)
    dataset = PretrainJsonl(
        data_path,
        tokenizer,
        max_length=int(cfg["max_len"]),
        max_samples=int(cfg["max_samples"]),
    )
    train_size = int(0.9 * len(dataset))
    eval_size = len(dataset) - train_size
    train_ds, eval_ds = torch.utils.data.random_split(
        dataset,
        [train_size, eval_size],
        generator=torch.Generator().manual_seed(int(args.seed)),
    )
    train_loader = DataLoader(
        train_ds,
        batch_size=int(cfg["batch"]),
        shuffle=True,
        num_workers=0,
    )
    eval_loader = DataLoader(
        eval_ds,
        batch_size=int(cfg["batch"]),
        shuffle=False,
        num_workers=0,
    )

    # 3. Models.
    print("\n========== Building models ==========")
    models = build_models(
        vocab_size=vocab_size,
        hidden_size=int(cfg["hidden_size"]),
        num_layers=int(cfg["n_layer"]),
        num_heads=int(cfg["n_head"]),
        max_len=int(cfg["max_len"]),
    )

    # 4. Output directory.
    out_dir = Path(args.out) / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 5. Train (or load).
    train_results: Dict[str, Any] = {}
    if not args.skip_train:
        for name, model in models.items():
            ckpt = out_dir / f"{name}.pt"
            train_results[name] = train_one_model(
                model,
                train_loader,
                eval_loader,
                device,
                name,
                lr=float(cfg["lr"]),
                epochs=int(cfg["epochs"]),
                save_path=ckpt,
            )
    else:
        for name, model in models.items():
            ckpt = out_dir / f"{name}.pt"
            if not ckpt.exists():
                print(
                    f"[warn] checkpoint {ckpt} missing; cannot skip "
                    f"training for {name}"
                )
                continue
            state = torch.load(ckpt, map_location=device)
            model.load_state_dict(state["model"])
            model.to(device)
            train_results[name] = {
                "model": model,
                "history": state["history"],
                "n_params": state["n_params"],
                "time": state["time"],
                "final_ppl": state["history"]["eval_ppl"][-1],
            }

    if not train_results:
        print("[error] no models available for validation; aborting")
        sys.exit(1)

    # 6. Validation.
    print("\n========== Running validations ==========")
    sample_batch = next(iter(eval_loader))
    sample_inputs = sample_batch["input_ids"][:2]
    baseline_model = train_results.get("transformer", {}).get("model")

    validation: Dict[str, Dict[str, Any]] = {}
    for name, info in train_results.items():
        print(f"  [validate] {name}")
        tester = UIDPredictionTester(info["model"], device=device)
        validation[name] = tester.run_all(
            sample_inputs,
            baseline_model=(
                baseline_model if name != "transformer" else None
            ),
            eval_loader=eval_loader if name != "transformer" else None,
        )

    # 7. Save & report.
    saveable = {
        "config": cfg,
        "training": {
            name: {
                "final_ppl": info["final_ppl"],
                "n_params": info["n_params"],
                "time": info["time"],
                "history": info["history"],
            }
            for name, info in train_results.items()
        },
        "validation": validation,
    }
    json_path = out_dir / "results.json"
    json_path.write_text(
        json.dumps(saveable, indent=2, default=str), encoding="utf-8"
    )
    print(f"[ok] results saved to {json_path}")

    try:
        write_plot(saveable, out_dir / "report.png")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[warn] plot generation failed: {exc}")

    print_summary(saveable)


if __name__ == "__main__":
    main()
