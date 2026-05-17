"""Stacked-extension chord canonicalisation in chord_ops/diff.py (#13).

Audiveris (and the row-OCR fallback) sometimes emit `chord-name` values
like `F#9/7` for the stacked-9-over-7 dom-9 glyph. Before #13 the diff
inserter set `chordKindStr` to the literal `9/7`, which MuseScore parses
as a slash-bass (root /7), with different playback voicing than the
intended stacked dom-9.

Per ``docs/chord-notation.md`` and ``chord_ops.parser._SUFFIX``, the
canonical MuseScore-grammar token for dom-9-over-7 is the literal `97`
(no slash). The fix maps `9/7` -> `97`; other digit/digit stacks keep
their slash form until we encounter and verify a different shape.
"""
from __future__ import annotations

from omr_leadsheet.chord_ops.diff import _stacked_extension_display


def test_nine_over_seven_collapses_to_literal_97() -> None:
    assert _stacked_extension_display("9", "7") == "97"


def test_other_stacks_keep_slash_form() -> None:
    # Figured-bass-style 6/5 stacks are rare in jazz lead sheets and the
    # canonical MuseScore token for them hasn't been verified by the user;
    # keep the slash form until that decision is grounded.
    assert _stacked_extension_display("6", "5") == "6/5"
    assert _stacked_extension_display("4", "3") == "4/3"


def test_result_matches_format_chord_for_9_over_7() -> None:
    """The output must agree with what chord_ops.parser.format_chord
    emits for the same logical chord -- single source of truth."""
    from omr_leadsheet.chord_ops.parser import ChordFields, format_chord
    expected_suffix = format_chord(
        ChordFields(
            root="F#", quality="7", extension="9_over_7",
            alteration="none", raw="F#9/7",
        ),
        style="symbolic",
    )
    # format_chord returns root+suffix; strip the root to compare to our suffix.
    assert expected_suffix == "F#97"
    assert _stacked_extension_display("9", "7") == expected_suffix[len("F#"):]
