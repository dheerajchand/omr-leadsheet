"""Regression: row-OCR rejects non-chord tokens via shape + denylist (#48).

Spot-check on #13 LCWTO ending showed two non-chord strings rendered
as if they were chord-symbols:
- ``2-c;`` (mis-read second-ending number plus punctuation)
- ``tr`` (trill ornament glyph)

``recover_chord_row_chords`` now applies an explicit
``_is_plausible_chord_token`` filter before returning.
"""
from __future__ import annotations

import pytest

from omr_leadsheet.recognisers.row_ocr import _is_plausible_chord_token


@pytest.mark.parametrize("token", [
    # Plain triads
    "C", "F", "G", "Bb", "B",
    # With qualities
    "Cm", "Dm7", "Gmaj7", "Cdim", "Caug", "C+", "Csus", "Csus4",
    # With extensions
    "C7", "C9", "C13", "Cm7b5",
    # Sharps
    "F#", "C#m7", "G#dim",
    # Slash chords (root only, no bass detection needed for shape check)
    "C/G", "Dm7/F",
    # Stacked extensions (the 9/7 case)
    "F#9/7",
])
def test_plausible_chord_tokens_accepted(token: str) -> None:
    assert _is_plausible_chord_token(token), (
        f"{token!r} should pass the chord-token filter but didn't"
    )


@pytest.mark.parametrize("token", [
    # The two from the #13 screenshot
    "2-c;",
    "tr",
    # Ornaments and dynamics common in printed scores
    "Tr",
    "mf", "mp", "pp", "ff", "fp", "sf",
    # Structural / tempo markings
    "Fine", "D.C.", "D.S.", "Coda",
    "rit", "rit.", "cresc", "cresc.", "decresc",
    # Empty / punctuation-only
    "",
    # Starts with letter outside A-G
    "Hello", "tempo", "8va",
    # Numeric-leading garbage from ending boxes
    "2.", "1.",
])
def test_implausible_tokens_rejected(token: str) -> None:
    assert not _is_plausible_chord_token(token), (
        f"{token!r} should be rejected but passed the filter"
    )


def test_denylist_uses_exact_match_not_prefix() -> None:
    """``Fine`` is denylisted but ``F`` (the chord) must still be
    accepted. ``D.C.`` is denylisted but ``D``, ``D7``, ``Dm`` must
    pass. ``cresc`` denylisted but ``Cm`` passes."""
    assert _is_plausible_chord_token("F")
    assert _is_plausible_chord_token("Fm7")
    assert _is_plausible_chord_token("D")
    assert _is_plausible_chord_token("D7")
    assert _is_plausible_chord_token("Dm")
    assert _is_plausible_chord_token("C")
    assert _is_plausible_chord_token("Cm")
    # And the denylisted full strings stay rejected.
    assert not _is_plausible_chord_token("Fine")
    assert not _is_plausible_chord_token("D.C.")
    assert not _is_plausible_chord_token("cresc")
