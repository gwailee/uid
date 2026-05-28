# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Data-loading utilities for UID training/evaluation pipelines.

UID 训练 / 评估管道的数据加载工具。

This module name (``data_loaders.py``) is HISTORICAL: it predates
v2.1 and is referenced by ``experiments/run_*.py`` via
``from test_uid_on_minimind import PretrainJsonl``. Despite the
``test_`` prefix, it is NOT a pytest test module — it is a data-
loader module. Pytest will skip it automatically because it defines
no ``test_*`` functions or ``Test*`` classes.

Two ``torch.utils.data.Dataset`` subclasses are provided:

  * :class:`PretrainJsonl` — for next-token language-model pre-training
    over JSONL files of the form ``{"text": "..."}``.
  * :class:`SftJsonl` — for supervised fine-tuning over JSONL files of
    the form ``{"prompt": "...", "response": "..."}``.

Both datasets index records by byte offset (built once on construction)
so opening even multi-GB files takes microseconds per sample without
keeping the whole file in RAM.

设计原则：按字节偏移建立索引；容忍空行、编码错误、缺字段的不完整行；
labels 与 input_ids 严格错位并把 pad 位置置为 -100；通过 collate_fn
工厂函数让 DataLoader 直接可用；本模块名称以 ``test_`` 开头是历史原因，
不会被 pytest 收集（无 test_* 函数 / Test* 类）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import torch
from torch.utils.data import Dataset


# ======================================================================
# Constants
# ======================================================================


# Loss positions whose label equals IGNORE_INDEX are excluded from the
# cross-entropy reduction. Matches PyTorch and Hugging Face convention.
IGNORE_INDEX: int = -100


# ======================================================================
# Offset index builder (shared by both Dataset classes)
# ======================================================================


def _build_line_offsets(path: Path) -> List[int]:
    """Return the byte offset of every non-empty line in a UTF-8 file.

    扫描一次文件，记录每行的字节偏移；空行 / 仅空白行被忽略。

    Args:
        path: Absolute or relative path to a text file.

    Returns:
        List of byte offsets where each non-empty line starts.

    Raises:
        FileNotFoundError: If the path does not exist.
        PermissionError:   If the file cannot be opened for reading.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"data file not found: {path.resolve()}"
        )
    offsets: List[int] = []
    # Open in binary mode so byte offsets are unambiguous regardless of
    # platform-specific newline translation.
    with path.open("rb") as f:
        while True:
            off = f.tell()
            line = f.readline()
            if not line:
                break
            # Skip blank lines (after stripping CR/LF and whitespace).
            stripped = line.strip()
            if stripped:
                offsets.append(off)
    if not offsets:
        raise RuntimeError(
            f"data file {path} contains no non-empty lines"
        )
    return offsets


def _read_line_at_offset(
    path: Path, offset: int,
) -> Optional[str]:
    """Return the decoded text of the line that starts at ``offset``.

    返回起始字节为 ``offset`` 的一行解码后的文本；
    UTF-8 解码失败时返回 None，由调用方决定如何处理。
    """
    with path.open("rb") as f:
        f.seek(offset)
        raw = f.readline()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ======================================================================
# Tokenizer adapter
# ======================================================================


class _TokenizerAdapter:
    """Light-weight wrapper around a HuggingFace tokenizer.

    HuggingFace tokenizer 的轻量包装，统一 pad / eos / bos 行为，
    便于在不同 tokenizer 之间切换而不需要修改 Dataset 代码。
    """

    def __init__(self, tokenizer: Any) -> None:
        if tokenizer is None:
            raise ValueError("tokenizer must not be None")
        self.tok = tokenizer
        # Resolve pad token: prefer pad_token_id, then eos_token_id.
        pad_id = getattr(tokenizer, "pad_token_id", None)
        if pad_id is None:
            pad_id = getattr(tokenizer, "eos_token_id", None)
        if pad_id is None:
            raise ValueError(
                "tokenizer must expose at least one of "
                "pad_token_id or eos_token_id"
            )
        self.pad_id: int = int(pad_id)
        # Resolve eos / bos for use in SFT formatting; either may be None.
        self.eos_id: Optional[int] = (
            int(tokenizer.eos_token_id)
            if getattr(tokenizer, "eos_token_id", None) is not None
            else None
        )
        self.bos_id: Optional[int] = (
            int(tokenizer.bos_token_id)
            if getattr(tokenizer, "bos_token_id", None) is not None
            else None
        )

    def encode(
        self,
        text: str,
        add_special_tokens: bool = False,
        max_length: Optional[int] = None,
        truncation: bool = True,
    ) -> List[int]:
        """Encode plain text to token ids.

        Returns a Python list (rather than a tensor) so the caller can
        cheaply concatenate / slice without tensor overhead.
        """
        ids = self.tok.encode(
            text, add_special_tokens=add_special_tokens,
        )
        if max_length is not None and truncation and len(ids) > max_length:
            ids = ids[:max_length]
        return list(ids)


# ======================================================================
# Pretrain dataset (next-token LM over plain text)
# ======================================================================


@dataclass
class _PretrainRecord:
    """One record returned by :class:`PretrainJsonl`."""

    input_ids: torch.Tensor  # (L,) long
    labels: torch.Tensor     # (L,) long; pad positions == IGNORE_INDEX
    attention_mask: torch.Tensor  # (L,) bool; True at non-pad positions


class PretrainJsonl(Dataset):
    """JSONL dataset for next-token language-model pre-training.

    用于下一 token 语言模型预训练的 JSONL 数据集。

    Expected line format::

        {"text": "...arbitrary unicode text..."}

    Lines that fail to parse as JSON, contain no ``text`` field, or
    whose ``text`` field is empty after stripping are silently skipped
    at construction time. The index built once on ``__init__`` then
    seeks directly to each valid line on demand.

    Args:
        path:              Path to the JSONL file.
        tokenizer:         A HuggingFace-compatible tokenizer object
                           (must expose ``encode``, ``pad_token_id``
                           and/or ``eos_token_id``).
        max_length:        Hard cap on the per-sample sequence length
                           (including any BOS/EOS specials).
        text_field:        JSON field to read as the text body
                           (default ``"text"``).
        append_eos:        If True (default), append ``eos_token_id``
                           to every sample when present.
        prepend_bos:       If True, prepend ``bos_token_id`` to every
                           sample when present.

    Each call to ``__getitem__`` returns a dict with three keys:

        * ``"input_ids"``:      (max_length,) torch.long
        * ``"labels"``:         (max_length,) torch.long; positions
                                that should not contribute to the loss
                                are set to :data:`IGNORE_INDEX` (-100).
        * ``"attention_mask"``: (max_length,) torch.bool; True where
                                ``input_ids[i] != pad_id``.

    The standard next-token language-model setup is implemented:
    ``labels`` equals ``input_ids`` rolled left by one position, with
    the final label set to IGNORE_INDEX. The model code is then free
    to perform its own ``shift_logits = logits[..., :-1, :]`` slice.
    """

    def __init__(
        self,
        path: Union[str, os.PathLike],
        tokenizer: Any,
        max_length: int = 1024,
        *,
        text_field: str = "text",
        append_eos: bool = True,
        prepend_bos: bool = False,
    ) -> None:
        if max_length <= 1:
            raise ValueError(
                f"max_length must be > 1, got {max_length}"
            )
        self.path: Path = Path(path)
        self.tok: _TokenizerAdapter = _TokenizerAdapter(tokenizer)
        self.max_length: int = int(max_length)
        self.text_field: str = str(text_field)
        self.append_eos: bool = bool(append_eos)
        self.prepend_bos: bool = bool(prepend_bos)

        # Build offsets and validate at least one record exists.
        all_offsets = _build_line_offsets(self.path)
        # Filter out lines whose text field is empty/missing/malformed.
        # We do this lazily by walking the file once at __init__; the
        # cost is one O(N) pass amortised over the dataset's lifetime.
        valid_offsets: List[int] = []
        with self.path.open("rb") as f:
            for off in all_offsets:
                f.seek(off)
                raw = f.readline()
                try:
                    text = raw.decode("utf-8")
                    record = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                body = record.get(self.text_field)
                if isinstance(body, str) and body.strip():
                    valid_offsets.append(off)
        if not valid_offsets:
            raise RuntimeError(
                f"no valid records in {self.path} "
                f"(field {self.text_field!r} empty or missing in every line)"
            )
        self._offsets: List[int] = valid_offsets

    # ----- Dataset API -------------------------------------------------

    def __len__(self) -> int:
        return len(self._offsets)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        if not 0 <= idx < len(self._offsets):
            raise IndexError(
                f"index {idx} out of range for {len(self._offsets)} records"
            )
        offset = self._offsets[idx]
        line = _read_line_at_offset(self.path, offset)
        if line is None:
            # Should be unreachable because __init__ filters bad lines,
            # but in case the file is mutated mid-flight we return a
            # single-pad sample instead of crashing.
            return self._pad_sample()
        try:
            record = json.loads(line)
            text = record[self.text_field]
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._pad_sample()

        # Encode and apply BOS/EOS.
        ids: List[int] = self.tok.encode(
            text, add_special_tokens=False,
            max_length=self.max_length, truncation=True,
        )
        if self.prepend_bos and self.tok.bos_id is not None:
            ids = [self.tok.bos_id] + ids
        if self.append_eos and self.tok.eos_id is not None:
            ids = ids + [self.tok.eos_id]
        # Truncate (again) AFTER specials in case appending overflowed.
        if len(ids) > self.max_length:
            ids = ids[: self.max_length]

        return self._to_tensors(ids)

    # ----- Helpers -----------------------------------------------------

    def _pad_sample(self) -> Dict[str, torch.Tensor]:
        """Return an all-pad sample (used as a graceful fallback)."""
        return self._to_tensors([])

    def _to_tensors(
        self, ids: Sequence[int],
    ) -> Dict[str, torch.Tensor]:
        """Pad to max_length and build the (input_ids, labels, mask)."""
        ids = list(ids)
        n = len(ids)
        if n < self.max_length:
            ids = ids + [self.tok.pad_id] * (self.max_length - n)
        # Build attention mask.
        mask = torch.tensor(
            [i < n for i in range(self.max_length)],
            dtype=torch.bool,
        )
        input_ids = torch.tensor(ids, dtype=torch.long)
        # Labels: shift LEFT by 1, set the LAST position to IGNORE.
        # Mask positions that are pad in input_ids to IGNORE too.
        labels = input_ids.clone()
        labels[:-1] = input_ids[1:]
        labels[-1] = IGNORE_INDEX
        # Set ignore at pad positions (they would otherwise predict pad).
        pad_mask = input_ids == self.tok.pad_id
        # The position immediately BEFORE a pad token is also typically
        # excluded because its prediction target is pad. We shift the
        # pad mask LEFT by 1 to map to label positions, then OR it in.
        shifted_pad = torch.zeros_like(pad_mask)
        shifted_pad[:-1] = pad_mask[1:]
        labels[shifted_pad] = IGNORE_INDEX
        # Last position is always IGNORE (already set above).
        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": mask,
        }


# ======================================================================
# Supervised fine-tuning dataset
# ======================================================================


class SftJsonl(Dataset):
    """JSONL dataset for supervised fine-tuning (instruction tuning).

    Expected line format::

        {"prompt": "...", "response": "..."}

    Tokens belonging to the prompt are masked out of the loss
    (set to :data:`IGNORE_INDEX`); only response tokens contribute
    to gradient updates.

    用于指令微调的 JSONL 数据集；prompt 部分的 token 不计入损失，
    仅 response 部分计入。

    Args:
        path:           JSONL file path.
        tokenizer:      HF-style tokenizer.
        max_length:     Hard cap on per-sample length.
        prompt_field:   JSON field for the prompt body
                        (default ``"prompt"``).
        response_field: JSON field for the response body
                        (default ``"response"``).
        prompt_prefix:  String prepended to the prompt before tokenising
                        (default ``""``).
        response_prefix:String prepended to the response before
                        tokenising (default ``"\\n"`` so the response
                        starts on a new line by default).
        append_eos:     If True (default), append eos_token_id to the
                        response when available.
    """

    def __init__(
        self,
        path: Union[str, os.PathLike],
        tokenizer: Any,
        max_length: int = 1024,
        *,
        prompt_field: str = "prompt",
        response_field: str = "response",
        prompt_prefix: str = "",
        response_prefix: str = "\n",
        append_eos: bool = True,
    ) -> None:
        if max_length <= 1:
            raise ValueError(
                f"max_length must be > 1, got {max_length}"
            )
        self.path: Path = Path(path)
        self.tok: _TokenizerAdapter = _TokenizerAdapter(tokenizer)
        self.max_length: int = int(max_length)
        self.prompt_field: str = str(prompt_field)
        self.response_field: str = str(response_field)
        self.prompt_prefix: str = str(prompt_prefix)
        self.response_prefix: str = str(response_prefix)
        self.append_eos: bool = bool(append_eos)

        all_offsets = _build_line_offsets(self.path)
        valid_offsets: List[int] = []
        with self.path.open("rb") as f:
            for off in all_offsets:
                f.seek(off)
                raw = f.readline()
                try:
                    text = raw.decode("utf-8")
                    record = json.loads(text)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(record, dict):
                    continue
                p = record.get(self.prompt_field)
                r = record.get(self.response_field)
                if (
                    isinstance(p, str) and p.strip()
                    and isinstance(r, str) and r.strip()
                ):
                    valid_offsets.append(off)
        if not valid_offsets:
            raise RuntimeError(
                f"no valid SFT records in {self.path} "
                f"(need both {self.prompt_field!r} and "
                f"{self.response_field!r} non-empty)"
            )
        self._offsets = valid_offsets

    def __len__(self) -> int:
        return len(self._offsets)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        if not 0 <= idx < len(self._offsets):
            raise IndexError(
                f"index {idx} out of range for {len(self._offsets)} records"
            )
        offset = self._offsets[idx]
        line = _read_line_at_offset(self.path, offset)
        if line is None:
            return self._pad_sample()
        try:
            record = json.loads(line)
            prompt = record[self.prompt_field]
            response = record[self.response_field]
        except (json.JSONDecodeError, KeyError, TypeError):
            return self._pad_sample()

        prompt_ids = self.tok.encode(
            self.prompt_prefix + prompt, add_special_tokens=False,
        )
        response_ids = self.tok.encode(
            self.response_prefix + response, add_special_tokens=False,
        )
        if self.append_eos and self.tok.eos_id is not None:
            response_ids = response_ids + [self.tok.eos_id]

        # Truncate prompt FIRST (we never want to lose the response
        # entirely).
        max_prompt = max(self.max_length - len(response_ids) - 1, 1)
        if len(prompt_ids) > max_prompt:
            prompt_ids = prompt_ids[-max_prompt:]
        full = prompt_ids + response_ids
        if len(full) > self.max_length:
            full = full[: self.max_length]

        n_prompt = len(prompt_ids)
        return self._to_tensors(full, n_prompt=n_prompt)

    def _pad_sample(self) -> Dict[str, torch.Tensor]:
        return self._to_tensors([], n_prompt=0)

    def _to_tensors(
        self, ids: Sequence[int], n_prompt: int,
    ) -> Dict[str, torch.Tensor]:
        ids = list(ids)
        n = len(ids)
        if n < self.max_length:
            ids = ids + [self.tok.pad_id] * (self.max_length - n)
        mask = torch.tensor(
            [i < n for i in range(self.max_length)],
            dtype=torch.bool,
        )
        input_ids = torch.tensor(ids, dtype=torch.long)
        labels = input_ids.clone()
        labels[:-1] = input_ids[1:]
        labels[-1] = IGNORE_INDEX
        # Mask prompt positions: in the SHIFTED labels view, label[i]
        # predicts token[i+1]. We mask out positions 0 .. n_prompt-1
        # because those targets belong to the prompt continuation.
        if n_prompt > 0:
            cutoff = min(n_prompt, self.max_length)
            labels[:cutoff] = IGNORE_INDEX
        # Mask pad positions.
        pad_mask = input_ids == self.tok.pad_id
        shifted_pad = torch.zeros_like(pad_mask)
        shifted_pad[:-1] = pad_mask[1:]
        labels[shifted_pad] = IGNORE_INDEX
        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": mask,
        }


# ======================================================================
# Collate-fn factory
# ======================================================================


def make_collate_fn(
    pad_id: Optional[int] = None,
    keys: Tuple[str, ...] = ("input_ids", "labels", "attention_mask"),
) -> Callable[[List[Dict[str, torch.Tensor]]], Dict[str, torch.Tensor]]:
    """Build a collate_fn that stacks per-sample dicts into a batch dict.

    构造 DataLoader 用的 collate_fn：把若干个 (input_ids, labels,
    attention_mask) 字典堆叠成 batch 字典。

    All samples must already have the same length (the two Dataset
    classes in this module guarantee that via padding to max_length).

    Args:
        pad_id: Unused in the same-length case; kept for forward
                compatibility with future variable-length batching.
        keys:   Tuple of dict keys to stack.

    Returns:
        A callable suitable for ``DataLoader(..., collate_fn=...)``.
    """
    del pad_id  # reserved

    def _collate(
        batch: List[Dict[str, torch.Tensor]],
    ) -> Dict[str, torch.Tensor]:
        if not batch:
            raise ValueError("collate_fn received an empty batch")
        out: Dict[str, torch.Tensor] = {}
        for k in keys:
            if k not in batch[0]:
                continue
            out[k] = torch.stack([item[k] for item in batch], dim=0)
        return out

    return _collate


# ======================================================================
# Standalone sanity check
# ======================================================================


def _self_test(path: str, tokenizer_path: str, max_length: int) -> None:
    """Quick CLI sanity check; run via ``python test_uid_on_minimind.py``."""
    from transformers import AutoTokenizer

    print(f"Loading tokenizer {tokenizer_path!r} ...")
    tok = AutoTokenizer.from_pretrained(tokenizer_path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    print(f"Building PretrainJsonl({path}, max_length={max_length}) ...")
    ds = PretrainJsonl(path, tok, max_length=max_length)
    print(f"  {len(ds):,} records indexed")

    print("Pulling 3 samples ...")
    for i in (0, len(ds) // 2, len(ds) - 1):
        sample = ds[i]
        ids = sample["input_ids"]
        lbl = sample["labels"]
        msk = sample["attention_mask"]
        n_real = int(msk.sum().item())
        n_ignored = int((lbl == IGNORE_INDEX).sum().item())
        decoded = tok.decode(ids[:n_real].tolist())
        snippet = decoded[:80].replace("\n", " ")
        print(
            f"  [{i:>6d}] real_tokens={n_real:>4d} "
            f"ignored_labels={n_ignored:>4d}  "
            f"text~ {snippet!r}"
        )

    # DataLoader smoke test.
    from torch.utils.data import DataLoader
    print("DataLoader smoke test (batch_size=2) ...")
    loader = DataLoader(
        ds, batch_size=2, shuffle=False, collate_fn=make_collate_fn(),
    )
    batch = next(iter(loader))
    print(
        f"  batch shape input_ids={tuple(batch['input_ids'].shape)} "
        f"labels={tuple(batch['labels'].shape)} "
        f"mask={tuple(batch['attention_mask'].shape)}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data_path", type=str, required=True,
        help="Path to a JSONL file of {'text': ...} records.",
    )
    parser.add_argument(
        "--tokenizer_path", type=str, default="gpt2",
        help="HuggingFace tokenizer id or local path.",
    )
    parser.add_argument(
        "--max_length", type=int, default=128,
        help="Per-sample token length cap for the sanity check.",
    )
    args = parser.parse_args()
    _self_test(args.data_path, args.tokenizer_path, args.max_length)
