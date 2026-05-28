"""Regression: curly apostrophe (U+2019) handled in tokenizer + dict
lookup (#68).

Symptom on #13 LCWTO m45 v2: the lyric "I'll" (with curly U+2019,
emitted by tesseract on typeset jazz fonts) was tokenized as just
"I" because the WORD regex only matched straight apostrophe. NW
alignment then resolved the truncated "I" onto the score, leaving
the user-visible v2 first note showing "I" instead of "I'll".
"""
from __future__ import annotations

from omr_leadsheet.pipeline.spell_check import (
    _line_to_tokens, is_real_word,
)


CURLY = "’"  # ’


def test_word_regex_accepts_curly_apostrophe() -> None:
    """The WORD-extracted token from a curly-apostrophe line keeps
    the contraction intact (with curly normalised to straight)."""
    tokens = _line_to_tokens(f"I{CURLY}ll wear pa-ja-mas")
    # Should be one token "I'll" plus the rest, not "I" + dropped "ll"
    assert tokens[0] == "I'll", f"first token should be the full contraction; got {tokens[0]!r}"


def test_line_to_tokens_normalises_to_straight() -> None:
    """Curly is normalised to straight at tokenisation time so all
    downstream comparisons / dict lookups see one canonical form."""
    tokens = _line_to_tokens(f"don{CURLY}t know where I{CURLY}m at")
    assert "don't" in tokens
    assert "I'm" in tokens
    # Curly version should NOT appear (the normalisation happened first).
    assert f"don{CURLY}t" not in tokens
    assert f"I{CURLY}m" not in tokens


def test_is_real_word_recognises_curly_contractions() -> None:
    """``I'll`` with curly apostrophe should be treated as a real
    word (via the dict's straight-form entry) so NW pass-1 keeps it
    instead of trying to replace it with a truncated truth token."""
    assert is_real_word(f"I{CURLY}ll")
    assert is_real_word(f"don{CURLY}t")


def test_straight_apostrophe_still_works() -> None:
    """The fix preserves behaviour for the straight-apostrophe forms
    that already worked."""
    assert _line_to_tokens("I'll wear pa-ja-mas")[0] == "I'll"
    assert is_real_word("I'll")
    assert is_real_word("don't")


def test_plain_words_unaffected() -> None:
    """Words with no apostrophe behave exactly as before."""
    assert _line_to_tokens("wear pa-ja-mas") == ["wear", "pa", "ja", "mas"]
    assert is_real_word("wear")
