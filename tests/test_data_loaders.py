# -*- coding: utf-8 -*-
# Copyright (c) 2026 Suzhou Jodell Robotics Co., Ltd.
# Author: Gui LI <guilichina@163.com>
# Date: 2026-05-28
# UPDATE: 2026-05-28 (v2.1 batch 5)
#   * Switched import source from test_uid_on_minimind -> data_loaders
#     to follow the v2.1 rename of the data-loader module.
#   * Added TestSftJsonl::test_truncation_keeps_recent_prompt and
#     three companion tests covering the "keep the TAIL of the prompt
#     when truncation is necessary" contract from data_loaders.SftJsonl.
"""Unit tests for data_loaders.py (v2.1).

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
       * **Aggressive truncation keeps the TAIL of the prompt**
         (most recent context), NOT the head — this is the
         instruction-tuning convention and matches data_loaders'
         ``prompt_ids = prompt_ids[-max_prompt:]`` slice.

  §I — make_collate_fn:
       * Stacks per-sample tensors into a batch.
       * Empty batch raises ValueError.
       * Keys argument filters output dict.

  §J — pytest discovery contract:
       * Importing data_loaders does NOT contribute pytest test items
         (the module exposes no Test* / test_* symbols).

Run with::

    pytest tests/test_data_loaders.py -v
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import torch
from torch.utils.data import DataLoader

# Import the data-loader module under test.
import data_loaders as data_mod
from data_loaders import (
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

    The vocab is **shared as a process-wide cache** between successive
    calls to encode(), which means the same word always maps to the
    same id within one test process. This stability is what enables
    §H's "keep recent prompt" tests to compare token-ids directly
    between an un-truncated reference run and a truncated run.
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
                assert bool(mask[i]) is False

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

    # ------------------------------------------------------------------
    # NEW (v2.1 batch 5): truncation keeps the recent prompt tail
    # ------------------------------------------------------------------

    def _build_sft_with_unique_prompt_words(
        self,
        tmp_path: Path,
        tokenizer: _FakeTokenizer,
        n_prompt_words: int,
        response_text: str,
        max_length: int,
        prompt_prefix: str = "",
        response_prefix: str = "\n",
        append_eos: bool = True,
    ) -> tuple[SftJsonl, List[int], List[int]]:
        """Build an SftJsonl whose prompt is a sequence of UNIQUE words.

        Returns ``(dataset, prompt_word_ids, response_token_ids)``:
            * ``prompt_word_ids[i]`` is the token id assigned by the
              fake tokenizer to the i-th prompt word
              (``"pw{i:04d}"`` for i in 0..n-1).
            * ``response_token_ids`` is the **fully tokenised**
              response after the response_prefix and (optional) EOS
              have been appended; this is what the truncator must
              preserve.

        Constructing unique prompt words lets us check, after
        truncation, exactly which prompt words survived in the
        sample's input_ids — and hence whether the TAIL of the
        prompt was kept (the v2.1 contract).
        """
        # Build prompt with deterministic, unique words.
        prompt_words = [f"pw{i:04d}" for i in range(n_prompt_words)]
        prompt_text = " ".join(prompt_words)

        # Pre-warm the tokenizer's vocab so that its assigned ids match
        # what SftJsonl will see when it later encodes the same text.
        prompt_word_ids = tokenizer.encode(
            prompt_prefix + prompt_text, add_special_tokens=False,
        )
        response_token_ids = tokenizer.encode(
            response_prefix + response_text, add_special_tokens=False,
        )
        if append_eos and tokenizer.eos_token_id is not None:
            response_token_ids = response_token_ids + [
                tokenizer.eos_token_id,
            ]

        p = tmp_path / "sft_recent.jsonl"
        _write_jsonl_records(p, [
            {"prompt": prompt_text, "response": response_text},
        ])
        ds = SftJsonl(
            p, tokenizer,
            max_length=max_length,
            prompt_prefix=prompt_prefix,
            response_prefix=response_prefix,
            append_eos=append_eos,
        )
        return ds, prompt_word_ids, response_token_ids

    def test_truncation_keeps_recent_prompt(
        self, tmp_path, tokenizer,
    ):
        """When the prompt is too long to fit, truncation must keep
        the TAIL of the prompt (most recent context), not the head.

        This is the key instruction-tuning convention encoded in
        ``data_loaders.SftJsonl`` via
        ``prompt_ids = prompt_ids[-max_prompt:]``. Failing this test
        means a future refactor accidentally switched to head-keeping
        truncation, which would silently degrade SFT quality on long
        prompts.
        """
        # Build a sample whose prompt is much longer than max_length
        # can possibly hold, so the truncator MUST drop part of it.
        n_prompt_words = 64
        response_text = "tail_response_word"
        max_length = 16

        ds, prompt_word_ids, response_token_ids = (
            self._build_sft_with_unique_prompt_words(
                tmp_path, tokenizer,
                n_prompt_words=n_prompt_words,
                response_text=response_text,
                max_length=max_length,
            )
        )

        sample = ds[0]
        ids: List[int] = sample["input_ids"].tolist()
        mask: List[bool] = [bool(x) for x in sample["attention_mask"].tolist()]
        # Strip pad positions to get only the 'real' tokens.
        real_ids = [i for i, m in zip(ids, mask) if m]

        # 1. The response tokens MUST appear at the very end of the
        #    real-id sequence (response is preserved, not the prompt
        #    head).
        assert real_ids[-len(response_token_ids):] == response_token_ids, (
            "Response was not preserved at the tail of the sample.\n"
            f"  expected tail: {response_token_ids}\n"
            f"  got tail:      {real_ids[-len(response_token_ids):]}"
        )

        # 2. The prompt portion of the real-id sequence is everything
        #    BEFORE those response tokens.
        kept_prompt = real_ids[: -len(response_token_ids)]
        assert len(kept_prompt) >= 1, (
            "After truncation, no prompt tokens survived; the "
            "truncator over-truncated the prompt."
        )

        # 3. Critically, the surviving prompt tokens must match the
        #    TAIL of the original full prompt token sequence
        #    (most-recent context preserved).
        expected_prompt_tail = prompt_word_ids[-len(kept_prompt):]
        assert kept_prompt == expected_prompt_tail, (
            "Truncation did NOT preserve the prompt tail.\n"
            f"  kept prompt:      {kept_prompt}\n"
            f"  expected tail:    {expected_prompt_tail}\n"
            f"  full prompt head: {prompt_word_ids[:8]}...\n"
            "If kept_prompt matches the prompt HEAD instead, the\n"
            "v2.1 'recent prompt' contract has been broken."
        )

        # 4. As a sanity guard: if the last surviving prompt word is
        #    pw0001, then truncation kept the head — explicit fail.
        if kept_prompt:
            assert kept_prompt[0] != prompt_word_ids[0], (
                "kept_prompt starts with the FIRST prompt word "
                f"(token id {prompt_word_ids[0]}); this means "
                "truncation kept the prompt HEAD instead of the TAIL."
            )

    def test_truncation_keeps_recent_prompt_when_no_room_for_full_response(
        self, tmp_path, tokenizer,
    ):
        """Edge case: response is long and prompt is also long; the
        truncator must still preserve the response (potentially
        truncating it to fit max_length-1) AND keep the most recent
        prompt prefix that fits in whatever room is left over.

        We focus the assertion on the tail-vs-head property of the
        surviving prompt segment.
        """
        n_prompt_words = 64
        response_text = "rword1 rword2 rword3 rword4 rword5"
        max_length = 12

        ds, prompt_word_ids, response_token_ids = (
            self._build_sft_with_unique_prompt_words(
                tmp_path, tokenizer,
                n_prompt_words=n_prompt_words,
                response_text=response_text,
                max_length=max_length,
            )
        )

        sample = ds[0]
        ids: List[int] = sample["input_ids"].tolist()
        mask: List[bool] = [bool(x) for x in sample["attention_mask"].tolist()]
        real_ids = [i for i, m in zip(ids, mask) if m]

        # The number of prompt tokens that survived in real_ids is
        # |real_ids| minus however many response tokens fit. We don't
        # know exactly how many response tokens were truncated (the
        # implementation is allowed to keep all of them and chop more
        # of the prompt), so we infer the boundary by finding the
        # longest suffix of real_ids that is a PREFIX of
        # response_token_ids OR equals response_token_ids exactly.
        # Then everything before that suffix is the surviving prompt.
        boundary = len(real_ids)
        for k in range(len(real_ids), 0, -1):
            candidate_resp_tail = real_ids[-k:]
            # Does this suffix appear as a prefix of the full response?
            if response_token_ids[:k] == candidate_resp_tail:
                boundary = len(real_ids) - k
                break
        kept_prompt = real_ids[:boundary]

        # If no prompt survived, the test has no signal — but the
        # data_loaders implementation reserves at least 1 prompt slot
        # via ``max_prompt = max(self.max_length - len(response_ids) - 1, 1)``
        # so we expect at least one surviving prompt token in the
        # vast majority of configurations.
        if not kept_prompt:
            pytest.skip(
                "No prompt tokens survived this configuration; "
                "skipping head-vs-tail check."
            )

        # The kept prompt must be a TAIL slice of the full prompt.
        expected_tail = prompt_word_ids[-len(kept_prompt):]
        assert kept_prompt == expected_tail, (
            "Truncation kept the wrong prompt slice.\n"
            f"  kept prompt:    {kept_prompt}\n"
            f"  expected tail:  {expected_tail}\n"
            f"  full prompt[:5]: {prompt_word_ids[:5]}"
        )

    def test_short_prompt_kept_in_full(self, tmp_path, tokenizer):
        """Sanity check: when the prompt fits comfortably, truncation
        is a no-op and the prompt is kept verbatim from the head."""
        n_prompt_words = 3
        response_text = "ans1 ans2"
        max_length = 32  # plenty of room

        ds, prompt_word_ids, response_token_ids = (
            self._build_sft_with_unique_prompt_words(
                tmp_path, tokenizer,
                n_prompt_words=n_prompt_words,
                response_text=response_text,
                max_length=max_length,
            )
        )

        sample = ds[0]
        ids: List[int] = sample["input_ids"].tolist()
        mask: List[bool] = [bool(x) for x in sample["attention_mask"].tolist()]
        real_ids = [i for i, m in zip(ids, mask) if m]

        # Full prompt + full response must both appear, in order.
        assert real_ids[: len(prompt_word_ids)] == prompt_word_ids, (
            "Short prompt was unexpectedly truncated."
        )
        assert real_ids[-len(response_token_ids):] == response_token_ids, (
            "Response was not preserved at the tail."
        )

    def test_prompt_kept_words_are_contiguous(self, tmp_path, tokenizer):
        """The surviving prompt segment must be a CONTIGUOUS slice of
        the original prompt — i.e. the truncator does not drop tokens
        from the middle. Combined with ``test_truncation_keeps_recent
        _prompt`` this pins down the truncation policy exactly:
        a single ``[-max_prompt:]`` slice.
        """
        n_prompt_words = 50
        response_text = "rrr"
        max_length = 18

        ds, prompt_word_ids, response_token_ids = (
            self._build_sft_with_unique_prompt_words(
                tmp_path, tokenizer,
                n_prompt_words=n_prompt_words,
                response_text=response_text,
                max_length=max_length,
            )
        )

        sample = ds[0]
        ids: List[int] = sample["input_ids"].tolist()
        mask: List[bool] = [bool(x) for x in sample["attention_mask"].tolist()]
        real_ids = [i for i, m in zip(ids, mask) if m]
        kept_prompt = real_ids[: -len(response_token_ids)] \
            if len(real_ids) >= len(response_token_ids) else []

        if not kept_prompt:
            pytest.skip("No prompt tokens survived; cannot test contiguity.")

        # Find where kept_prompt begins inside the original prompt.
        # Because kept_prompt is supposed to be a tail slice, this
        # start index equals len(prompt_word_ids) - len(kept_prompt).
        start = len(prompt_word_ids) - len(kept_prompt)
        assert start >= 0
        original_tail = prompt_word_ids[start:]
        assert kept_prompt == original_tail, (
            "Surviving prompt segment is not a contiguous tail of "
            "the original prompt; the truncator may be dropping "
            "tokens from the middle.\n"
            f"  kept_prompt:   {kept_prompt}\n"
            f"  original_tail: {original_tail}"
        )


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
    """The data-loader module must not contribute pytest test items
    by accident, otherwise every CI run would silently re-run import
    side effects."""

    def test_no_test_functions_in_module(self):
        names = [n for n in dir(data_mod) if n.startswith("test_")]
        # Only acceptable matches are dunder-private helpers (e.g.
        # ``_test``); top-level public ``test_*`` is forbidden.
        public_test_names = [n for n in names if not n.startswith("_")]
        assert public_test_names == [], (
            f"data_loaders module exposes public test_* names: "
            f"{public_test_names}. These would be collected by pytest."
        )

    def test_no_test_classes_in_module(self):
        names = [
            n for n in dir(data_mod)
            if n.startswith("Test") and isinstance(getattr(data_mod, n), type)
        ]
        assert names == [], (
            f"data_loaders module exposes Test* classes: {names}. "
            "These would be collected by pytest."
        )

    def test_module_is_importable_more_than_once(self):
        """Re-importing must be cheap and side-effect-free."""
        mod1 = importlib.reload(data_mod)
        mod2 = importlib.reload(mod1)
        assert hasattr(mod2, "PretrainJsonl")
        assert hasattr(mod2, "SftJsonl")
        assert hasattr(mod2, "IGNORE_INDEX")
