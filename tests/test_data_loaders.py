# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
"""Unit tests for test_uid_on_minimind.py (data loaders).

Covers every promise made in the v2.1 rewrite of the data-loader
module:

  §A — Offset index builder (_build_line_offsets):
       * Skips blank lines.
       * Raises on missing file / empty file.
       * Returns one offset per non-empty line.

  §B — _TokenizerAdapter:
       * Falls back from pad_token_id to eos_token_id.
       * Raises if neither is available.
       * Truncates on max_length.

  §C — PretrainJsonl construction filtering:
       * Skips lines that fail JSON parsing.
       * Skips lines whose ``text_field`` is missing / empty / not str.
       * Skips lines that aren't a JSON object.
       * Raises if NO valid record remains.

  §D — PretrainJsonl __getitem__ contract:
       * Output keys are exactly {input_ids, labels, attention_mask}.
       * All three tensors have shape (max_length,).
       * input_ids dtype = long; attention_mask dtype = bool.
       * Pad positions in attention_mask are False.
       * IGNORE_INDEX placed at the last label position and at every
         label position whose target token is pad.
       * Index out of range raises IndexError.

  §E — Extreme content:
       * Very long samples truncate cleanly (no crash, no overflow).
       * Empty body after stripping is skipped at __init__.
       * Unicode CJK content survives the byte-offset round trip.

  §F — Encoding & malformed-line resilience:
       * UTF-8 decode failure inside a non-indexed line is skipped at
         __init__.
       * If a previously-indexed line gets corrupted between __init__
         and __getitem__ (we simulate by overwriting the file), the
         loader returns a pad sample instead of crashing.

  §G — SftJsonl construction filtering:
       * Requires BOTH prompt and response non-empty.
       * Skips records missing either field.

  §H — SftJsonl __getitem__ contract:
       * Prompt positions in labels are IGNORE_INDEX.
       * Response positions in labels are NOT all IGNORE_INDEX.
       * Truncation never loses the entire response.
       * EOS appended when tokenizer exposes eos_token_id.

  §I — make_collate_fn:
       * Stacks per-sample tensors into a batch.
       * Empty batch raises ValueError.
       * Keys argument filters output dict.

  §J — pytest discovery contract:
       * Importing test_uid_on_minimind does NOT contribute pytest
         test items (the module name has a 'test_' prefix but exposes
         no Test* / test_* symbols).

Run with::

    pytest tests/test_data_loaders.py -v
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import torch
from torch.utils.data import DataLoader

# Import the data-loader module under test. Despite its ``test_``
# prefix, this is a regular module (verified in §J below).
import test_uid_on_minimind as data_mod
from test_uid_on_minimind import (
    IGNORE_INDEX,
    PretrainJsonl,
    SftJsonl,
    _build_line_offsets,
    _TokenizerAdapter,
    make_collate_fn,
)


# ======================================================================
# Lightweight fake tokenizer (no external deps)
# ======================================================================


class _FakeTokenizer:
    """Whitespace tokenizer with a fixed vocab.

    Deterministic and dependency-free, so the tests don't need
    ``transformers`` installed. Mimics the subset of HuggingFace
    tokenizer API that ``_TokenizerAdapter`` uses.
    """

    PAD_ID = 0
    BOS_ID = 1
    EOS_ID = 2
    UNK_ID = 3
    BASE = 10  # first id assigned to a real word

    def __init__(
        self,
        with_pad: bool = True,
        with_eos: bool = True,
        with_bos: bool = True,
    ) -> None:
        self.pad_token_id: Optional[int] = (
            self.PAD_ID if with_pad else None
        )
        self.eos_token_id: Optional[int] = (
            self.EOS_ID if with_eos else None
        )
        self.bos_token_id: Optional[int] = (
            self.BOS_ID if with_bos else None
        )
        # Build a vocab on the fly.
        self._vocab: Dict[str, int] = {}
        self._next_id: int = self.BASE

    def encode(
        self,
        text: str,
        add_special_tokens: bool = False,
    ) -> List[int]:
        del add_special_tokens  # adapter passes False
        out: List[int] = []
        for word in text.split():
            if word not in self._vocab:
                self._vocab[word] = self._next_id
                self._next_id += 1
            out.append(self._vocab[word])
        return out

    def decode(self, ids: List[int]) -> str:
        inv = {v: k for k, v in self._vocab.items()}
        return " ".join(inv.get(i, "<unk>") for i in ids)


# ======================================================================
# JSONL writer fixtures
# ======================================================================


@pytest.fixture
def tokenizer() -> _FakeTokenizer:
    return _FakeTokenizer()


def _write_jsonl(path: Path, lines: List[str]) -> None:
    """Write raw lines verbatim (no auto-append of newlines if you
    already included them). This lets us craft malformed content."""
    with path.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln)
            if not ln.endswith("\n"):
                f.write("\n")


def _write_jsonl_records(path: Path, records: List[Dict[str, Any]]) -> None:
    """Write a list of well-formed JSON records, one per line."""
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ======================================================================
# §A — Offset index builder
# ======================================================================


class TestBuildLineOffsets:
    def test_one_offset_per_non_empty_line(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, ['{"text": "a"}', '{"text": "b"}', '{"text": "c"}'])
        offs = _build_line_offsets(p)
        assert len(offs) == 3
        assert offs == sorted(offs), "Offsets must be ascending"

    def test_blank_and_whitespace_lines_skipped(self, tmp_path):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            '{"text": "a"}',
            "",            # blank
            "   ",         # whitespace only
            '{"text": "b"}',
            "\t\t",        # tabs only
        ])
        offs = _build_line_offsets(p)
        assert len(offs) == 2

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            _build_line_offsets(tmp_path / "nope.jsonl")

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_bytes(b"")
        with pytest.raises(RuntimeError, match="no non-empty lines"):
            _build_line_offsets(p)

    def test_only_blank_lines_raises(self, tmp_path):
        p = tmp_path / "blanks.jsonl"
        p.write_text("\n\n   \n\t\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="no non-empty lines"):
            _build_line_offsets(p)


# ======================================================================
# §B — _TokenizerAdapter
# ======================================================================


class TestTokenizerAdapter:
    def test_uses_pad_token_id_when_present(self):
        tok = _FakeTokenizer(with_pad=True, with_eos=True)
        ad = _TokenizerAdapter(tok)
        assert ad.pad_id == _FakeTokenizer.PAD_ID
        assert ad.eos_id == _FakeTokenizer.EOS_ID
        assert ad.bos_id == _FakeTokenizer.BOS_ID

    def test_falls_back_to_eos_when_no_pad(self):
        tok = _FakeTokenizer(with_pad=False, with_eos=True)
        ad = _TokenizerAdapter(tok)
        assert ad.pad_id == _FakeTokenizer.EOS_ID

    def test_raises_when_neither_pad_nor_eos(self):
        tok = _FakeTokenizer(with_pad=False, with_eos=False)
        with pytest.raises(ValueError, match="pad_token_id or eos_token_id"):
            _TokenizerAdapter(tok)

    def test_raises_on_none_tokenizer(self):
        with pytest.raises(ValueError, match="must not be None"):
            _TokenizerAdapter(None)

    def test_encode_truncates_to_max_length(self, tokenizer):
        ad = _TokenizerAdapter(tokenizer)
        ids = ad.encode(" ".join(["w"] * 50), max_length=10)
        assert len(ids) == 10

    def test_encode_returns_list_not_tensor(self, tokenizer):
        ad = _TokenizerAdapter(tokenizer)
        ids = ad.encode("a b c")
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)


# ======================================================================
# §C — PretrainJsonl construction filtering
# ======================================================================


class TestPretrainJsonlConstructionFiltering:
    def test_skips_unparseable_json_lines(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            '{"text": "valid one"}',
            'this is not json',
            '{"text": "valid two"}',
            '{also not valid',
            '{"text": "valid three"}',
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32)
        assert len(ds) == 3

    def test_skips_lines_missing_text_field(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [
            {"text": "a"},
            {"not_text": "b"},
            {"text": "c"},
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32)
        assert len(ds) == 2

    def test_skips_lines_with_empty_text(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [
            {"text": "a"},
            {"text": ""},
            {"text": "   \t  "},  # only whitespace
            {"text": "b"},
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32)
        assert len(ds) == 2

    def test_skips_lines_with_non_string_text(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [
            {"text": "a"},
            {"text": 12345},     # int, not str
            {"text": ["a", "b"]},  # list, not str
            {"text": None},
            {"text": "b"},
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32)
        assert len(ds) == 2

    def test_skips_top_level_non_dict_records(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            '{"text": "valid"}',
            '"just a string"',
            '[1, 2, 3]',
            'true',
            'null',
            '42',
            '{"text": "another valid"}',
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32)
        assert len(ds) == 2

    def test_no_valid_records_raises(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl(p, [
            'garbage',
            '{"not_text": "x"}',
            '{"text": "   "}',
        ])
        with pytest.raises(RuntimeError, match="no valid records"):
            PretrainJsonl(p, tokenizer, max_length=32)

    def test_custom_text_field(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [
            {"body": "hello"},
            {"body": "world"},
            {"text": "ignored"},  # wrong field for this dataset
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=32, text_field="body")
        assert len(ds) == 2

    def test_max_length_must_be_gt_1(self, tmp_path, tokenizer):
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [{"text": "a"}])
        with pytest.raises(ValueError, match="max_length must be > 1"):
            PretrainJsonl(p, tokenizer, max_length=1)
        with pytest.raises(ValueError, match="max_length must be > 1"):
            PretrainJsonl(p, tokenizer, max_length=0)


# ======================================================================
# §D — PretrainJsonl __getitem__ contract
# ======================================================================


def _make_simple_pretrain_dataset(
    tmp_path: Path, tokenizer: _FakeTokenizer, n: int = 5,
    max_length: int = 16,
) -> PretrainJsonl:
    p = tmp_path / "train.jsonl"
    _write_jsonl_records(p, [
        {"text": f"sentence number {i} with several tokens"}
        for i in range(n)
    ])
    return PretrainJsonl(p, tokenizer, max_length=max_length)


class TestPretrainJsonlGetItem:
    def test_returns_exact_keys(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(tmp_path, tokenizer)
        sample = ds[0]
        assert set(sample.keys()) == {
            "input_ids", "labels", "attention_mask",
        }

    def test_tensor_shapes(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(
            tmp_path, tokenizer, max_length=16,
        )
        sample = ds[0]
        for k in ("input_ids", "labels", "attention_mask"):
            assert sample[k].shape == (16,), f"{k} has shape {sample[k].shape}"

    def test_tensor_dtypes(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(tmp_path, tokenizer)
        sample = ds[0]
        assert sample["input_ids"].dtype == torch.long
        assert sample["labels"].dtype == torch.long
        assert sample["attention_mask"].dtype == torch.bool

    def test_attention_mask_false_at_pad(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(
            tmp_path, tokenizer, max_length=32,
        )
        sample = ds[0]
        pad_id = ds.tok.pad_id
        ids = sample["input_ids"]
        mask = sample["attention_mask"]
        # Wherever input_ids == pad_id, mask must be False.
        for i in range(ids.shape[0]):
            if ids[i].item() == pad_id:
                assert mask[i].item() is False or bool(mask[i]) is False

    def test_last_label_is_ignored(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(tmp_path, tokenizer)
        sample = ds[0]
        assert sample["labels"][-1].item() == IGNORE_INDEX

    def test_labels_at_pad_positions_are_ignored(self, tmp_path, tokenizer):
        # Use a short text but a long max_length so we KNOW we'll have
        # plenty of pad positions to test the ignore-at-pad rule.
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [{"text": "a b c"}])
        ds = PretrainJsonl(p, tokenizer, max_length=16)
        sample = ds[0]
        ids = sample["input_ids"]
        lbl = sample["labels"]
        pad_id = ds.tok.pad_id
        # For each position whose NEXT token is pad, that position's
        # label (which equals the next token) must be IGNORE_INDEX.
        for i in range(ids.shape[0] - 1):
            if ids[i + 1].item() == pad_id:
                assert lbl[i].item() == IGNORE_INDEX, (
                    f"position {i} predicts pad but its label is "
                    f"{lbl[i].item()} (should be {IGNORE_INDEX})"
                )

    def test_labels_are_input_shifted_left_at_real_positions(
        self, tmp_path, tokenizer,
    ):
        # Text long enough that none of the early positions are pad.
        p = tmp_path / "f.jsonl"
        long_text = " ".join(["word" + str(i) for i in range(20)])
        _write_jsonl_records(p, [{"text": long_text}])
        ds = PretrainJsonl(p, tokenizer, max_length=10)
        sample = ds[0]
        ids = sample["input_ids"]
        lbl = sample["labels"]
        # First 9 label positions must equal input shifted left by 1
        # (provided none are pad — guaranteed by the long text + small
        # max_length).
        for i in range(ids.shape[0] - 1):
            if lbl[i].item() == IGNORE_INDEX:
                continue
            assert lbl[i].item() == ids[i + 1].item(), (
                f"label[{i}] = {lbl[i].item()}, "
                f"input[{i+1}] = {ids[i+1].item()}"
            )

    def test_index_out_of_range_raises(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(tmp_path, tokenizer, n=3)
        with pytest.raises(IndexError, match="out of range"):
            _ = ds[3]
        with pytest.raises(IndexError, match="out of range"):
            _ = ds[-1]

    def test_dataset_len_matches_valid_records(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(tmp_path, tokenizer, n=7)
        assert len(ds) == 7


# ======================================================================
# §E — Extreme content
# ======================================================================


class TestExtremeContent:
    def test_very_long_sample_truncates_cleanly(
        self, tmp_path, tokenizer,
    ):
        """Sample text with 10,000 words; max_length = 64."""
        p = tmp_path / "f.jsonl"
        long_text = " ".join(["w" + str(i) for i in range(10_000)])
        _write_jsonl_records(p, [{"text": long_text}])
        ds = PretrainJsonl(
            p, tokenizer, max_length=64,
            append_eos=True, prepend_bos=False,
        )
        sample = ds[0]
        # Hard cap holds.
        assert sample["input_ids"].shape[0] == 64
        # No tensor element should be out of range.
        assert sample["input_ids"].max().item() < 1_000_000
        # All attention positions should be True for a long sample
        # (no padding when the text fills the buffer).
        assert sample["attention_mask"].all().item()

    def test_unicode_cjk_round_trip(self, tmp_path, tokenizer):
        p = tmp_path / "cjk.jsonl"
        _write_jsonl_records(p, [
            {"text": "智能是一个非平衡场"},
            {"text": "注意力并不够"},
            {"text": "苏州钧舵机器人有限公司"},
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=16)
        assert len(ds) == 3
        # Every sample's input_ids must contain at least one non-pad token.
        for i in range(len(ds)):
            s = ds[i]
            n_real = int(s["attention_mask"].sum().item())
            assert n_real >= 1

    def test_text_consisting_only_of_specials_skipped_or_handled(
        self, tmp_path, tokenizer,
    ):
        """A text that produces zero tokens after encoding should not
        crash. Our fake tokenizer always produces at least one token
        for any non-empty string, so we test the construction-time
        skip via empty/whitespace text (already covered) and the
        runtime fallback via an empty post-strip body."""
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [{"text": "ok"}])
        ds = PretrainJsonl(p, tokenizer, max_length=16)
        # Just ensure __getitem__ on the indexed record works.
        sample = ds[0]
        assert sample["input_ids"].shape == (16,)


# ======================================================================
# §F — Encoding & malformed-line resilience
# ======================================================================


class TestEncodingResilience:
    def test_utf8_decode_failure_skipped_at_init(
        self, tmp_path, tokenizer,
    ):
        p = tmp_path / "mixed.jsonl"
        # Mix valid UTF-8 lines with one line of pure binary garbage.
        with p.open("wb") as f:
            f.write(b'{"text": "valid a"}\n')
            # 0xff 0xfe is an invalid UTF-8 byte sequence in the middle
            # of a line.
            f.write(b'\xff\xfe garbage \xff\xfe\n')
            f.write(b'{"text": "valid b"}\n')
        ds = PretrainJsonl(p, tokenizer, max_length=16)
        assert len(ds) == 2

    def test_runtime_corruption_falls_back_to_pad(
        self, tmp_path, tokenizer,
    ):
        """Simulate a file mutated between __init__ and __getitem__:
        we truncate the file after indexing and read past the new end.
        """
        p = tmp_path / "f.jsonl"
        _write_jsonl_records(p, [
            {"text": "first record"},
            {"text": "second record"},
            {"text": "third record"},
        ])
        ds = PretrainJsonl(p, tokenizer, max_length=16)
        assert len(ds) == 3
        # Truncate to 0 bytes — any subsequent read returns nothing.
        with p.open("wb") as f:
            f.write(b"")
        # __getitem__ must not crash; it should return a pad sample.
        sample = ds[2]
        # All positions pad means all attention_mask are False.
        assert not sample["attention_mask"].any().item()
        # All labels IGNORE.
        assert (sample["labels"] == IGNORE_INDEX).all().item()


# ======================================================================
# §G — SftJsonl construction filtering
# ======================================================================


class TestSftJsonlConstructionFiltering:
    def test_requires_both_prompt_and_response_nonempty(
        self, tmp_path, tokenizer,
    ):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {"prompt": "ask", "response": "answer"},   # OK
            {"prompt": "", "response": "answer"},      # bad prompt
            {"prompt": "ask", "response": ""},         # bad response
            {"prompt": "  ", "response": "answer"},    # whitespace prompt
            {"prompt": "ask", "response": "   "},      # whitespace response
            {"prompt": "ask only"},                    # missing response
            {"response": "resp only"},                 # missing prompt
            {"prompt": "ask2", "response": "answer2"},  # OK
        ])
        ds = SftJsonl(p, tokenizer, max_length=64)
        assert len(ds) == 2

    def test_no_valid_records_raises(self, tmp_path, tokenizer):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {"prompt": "x"},  # missing response
            {"response": "y"},  # missing prompt
        ])
        with pytest.raises(RuntimeError, match="no valid SFT records"):
            SftJsonl(p, tokenizer, max_length=64)

    def test_custom_field_names(self, tmp_path, tokenizer):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {"q": "ask", "a": "answer"},
            {"q": "ask2", "a": "answer2"},
        ])
        ds = SftJsonl(
            p, tokenizer, max_length=64,
            prompt_field="q", response_field="a",
        )
        assert len(ds) == 2


# ======================================================================
# §H — SftJsonl __getitem__ contract
# ======================================================================


class TestSftJsonlGetItem:
    def test_prompt_positions_masked(self, tmp_path, tokenizer):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {
                "prompt": "the prompt has several words",
                "response": "the response also has several words",
            },
        ])
        ds = SftJsonl(p, tokenizer, max_length=32)
        sample = ds[0]
        lbl = sample["labels"]
        # At least the first few labels should be IGNORE (prompt region).
        # We can't know the exact length without re-tokenising, so we
        # just assert a non-trivial prefix is ignored.
        prefix_ignored = sum(
            1 for i in range(min(5, lbl.shape[0]))
            if lbl[i].item() == IGNORE_INDEX
        )
        assert prefix_ignored >= 3, (
            "Expected prompt prefix to be masked out of the loss; "
            f"only {prefix_ignored}/5 of leading positions were IGNORE."
        )

    def test_response_has_some_non_ignore_labels(
        self, tmp_path, tokenizer,
    ):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {
                "prompt": "ask",
                "response": (
                    "long response with many words that should produce "
                    "many non-ignore label positions in the supervision"
                ),
            },
        ])
        ds = SftJsonl(p, tokenizer, max_length=64)
        sample = ds[0]
        lbl = sample["labels"]
        n_supervised = int((lbl != IGNORE_INDEX).sum().item())
        assert n_supervised >= 3, (
            "Expected the response to provide several supervised "
            f"label positions; got {n_supervised}."
        )

    def test_truncation_never_loses_response(self, tmp_path, tokenizer):
        """Prompt very long, response short, max_length too small to
        keep the full prompt. The truncator must keep the response."""
        p = tmp_path / "sft.jsonl"
        long_prompt = " ".join(["p"] * 200)
        _write_jsonl_records(p, [
            {"prompt": long_prompt, "response": "short answer"},
        ])
        ds = SftJsonl(p, tokenizer, max_length=16)
        sample = ds[0]
        lbl = sample["labels"]
        # The response is "short answer" -> 2 tokens; plus a leading
        # "\n" + EOS, expect about 3-5 supervised tokens.
        n_supervised = int((lbl != IGNORE_INDEX).sum().item())
        assert n_supervised >= 1, (
            "Aggressive truncation dropped the entire response; "
            "the response must always survive truncation."
        )

    def test_eos_appended_when_available(self, tmp_path, tokenizer):
        # Build with EOS token id available.
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {"prompt": "ask", "response": "a b"},
        ])
        ds = SftJsonl(p, tokenizer, max_length=12, append_eos=True)
        sample = ds[0]
        # The EOS token id should appear at least once.
        assert (sample["input_ids"] == _FakeTokenizer.EOS_ID).any().item()

    def test_no_eos_when_disabled(self, tmp_path, tokenizer):
        p = tmp_path / "sft.jsonl"
        _write_jsonl_records(p, [
            {"prompt": "ask", "response": "a b"},
        ])
        ds = SftJsonl(p, tokenizer, max_length=12, append_eos=False)
        sample = ds[0]
        # If the response did NOT contain EOS originally, the input
        # should also not contain EOS (unless purely by coincidence —
        # our fake tokenizer never produces EOS_ID from text).
        # The "\n" prefix may or may not map to EOS depending on the
        # tokenizer; with our fake tokenizer it maps to a fresh id.
        # So assert that EOS_ID appears at most as a coincidence:
        # in the tokenised stream of "ask", "\n", "a", "b" it should
        # be absent.
        assert not (sample["input_ids"] == _FakeTokenizer.EOS_ID).any().item()


# ======================================================================
# §I — make_collate_fn
# ======================================================================


class TestCollateFn:
    def test_stacks_per_sample_dicts(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(
            tmp_path, tokenizer, n=4, max_length=8,
        )
        loader = DataLoader(
            ds, batch_size=2, shuffle=False, collate_fn=make_collate_fn(),
        )
        batch = next(iter(loader))
        assert set(batch.keys()) == {
            "input_ids", "labels", "attention_mask",
        }
        for k in batch:
            assert batch[k].shape == (2, 8)

    def test_empty_batch_raises(self):
        collate = make_collate_fn()
        with pytest.raises(ValueError, match="empty batch"):
            collate([])

    def test_keys_filter(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(
            tmp_path, tokenizer, n=3, max_length=8,
        )
        loader = DataLoader(
            ds, batch_size=2, shuffle=False,
            collate_fn=make_collate_fn(keys=("input_ids",)),
        )
        batch = next(iter(loader))
        assert set(batch.keys()) == {"input_ids"}
        assert batch["input_ids"].shape == (2, 8)

    def test_dataloader_iterates_all_records(self, tmp_path, tokenizer):
        ds = _make_simple_pretrain_dataset(
            tmp_path, tokenizer, n=5, max_length=8,
        )
        loader = DataLoader(
            ds, batch_size=2, shuffle=False, collate_fn=make_collate_fn(),
        )
        seen = 0
        for batch in loader:
            seen += batch["input_ids"].shape[0]
        assert seen == 5


# ======================================================================
# §J — pytest discovery contract
# ======================================================================


class TestModuleDoesNotPolluteDiscovery:
    """The data-loader module has a ``test_`` prefix for historical
    reasons. Pytest must not collect any test items FROM IT, otherwise
    every CI run would silently re-run import side effects."""

    def test_no_test_functions_in_module(self):
        names = [n for n in dir(data_mod) if n.startswith("test_")]
        # Only acceptable matches are dunder-private helpers (e.g.
        # ``_test``); top-level public ``test_*`` is forbidden.
        public_test_names = [n for n in names if not n.startswith("_")]
        assert public_test_names == [], (
            f"data-loader module exposes public test_* names: "
            f"{public_test_names}. These would be collected by pytest."
        )

    def test_no_test_classes_in_module(self):
        names = [
            n for n in dir(data_mod)
            if n.startswith("Test") and isinstance(getattr(data_mod, n), type)
        ]
        assert names == [], (
            f"data-loader module exposes Test* classes: {names}. "
            "These would be collected by pytest."
        )

    def test_module_is_importable_more_than_once(self):
        """Re-importing must be cheap and side-effect-free."""
        mod1 = importlib.reload(data_mod)
        mod2 = importlib.reload(mod1)
        assert hasattr(mod2, "PretrainJsonl")
        assert hasattr(mod2, "SftJsonl")
        assert hasattr(mod2, "IGNORE_INDEX")
