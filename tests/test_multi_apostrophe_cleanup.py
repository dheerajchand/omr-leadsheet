"""Regression: tesseract OCR sometimes doubles apostrophe marks within
a jazz syllable (e.g. "sas'" -> "sa's'") and the WORD tokenizer would
preserve every apostrophe, leaving a token that doesn't match any dict
entry. Collapse multi-apostrophe tokens to a single trailing one (#85).

Symptom on #13 LCWTO m30 v2: published lyric "You sas'-pa-ril-la and"
came through tesseract as "You, sa's'- pa- ril-la and", tokenizing as
["sa's'", "pa", "ril", "la", ...] -- "sa's'" is not in any dict so
NW alignment lost the syllable."""
from __future__ import annotations

from omr_leadsheet.pipeline.spell_check import _line_to_tokens, is_real_word


def test_double_apostrophe_collapses() -> None:
    """OCR garble 'sa's'' becomes 'sas'' with one trailing apostrophe."""
    toks = _line_to_tokens("You, sa's'- pa- ril-la")
    assert "sas'" in toks
    assert "sa's'" not in toks


def test_single_apostrophe_preserved() -> None:
    """Real contractions like 'don't' and 'I'll' must stay intact."""
    toks = _line_to_tokens("don't know I'll go")
    assert "don't" in toks
    assert "I'll" in toks


def test_triple_apostrophe_also_collapses() -> None:
    """A pathological 'a'b'c'' style OCR collapse still produces one
    trailing apostrophe."""
    toks = _line_to_tokens("a'b'c'd")
    assert toks == ["abcd'"]


def test_collapsed_jazz_syllable_recognised_as_real_word() -> None:
    """After collapse, 'sas'' is recognised as a real-word via the
    GERSHWIN_SYLLABLES dict so NW alignment treats it as a real
    truth token."""
    toks = _line_to_tokens("sa's'- pa-ril-la")
    assert "sas'" in toks
    assert is_real_word("sas'")
