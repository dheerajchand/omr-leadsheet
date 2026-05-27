"""Regression: parenthetical-wrapped alterations dedupe against their
unwrapped equivalents at the ``normalize_chord`` level (#49 partial).

``normalize_chord`` now strips parens so the dedup key collapses
parenthetical and non-parenthetical spellings of the same chord:

  E(b7) and Eb7 both normalise to "eb7"
  C7(b9) and C7b9 both normalise to "c7b9"
  Cm7(b5) and Cm7b5 both normalise to "cm7b5"

This affects the upstream ``diff(omr, mxl)`` comparison, where the
OMR-emitted text figure is compared directly against the exported
MXL chord text -- both can carry literal parens.

Out of scope (left for a separate ticket):
- The m52 case where Audiveris's parens reading becomes
  ``<harmony><degree>...</degree></harmony>`` at MusicXML export
  time. By the time music21 parses the lead, the figure attribute
  no longer carries parens (it becomes ``E add b7`` or similar
  structural string). normalize-paren-strip doesn't catch that
  collision. Needs a musical-fingerprint dedup based on root pitch
  class + kind + structural alterations.
"""
from __future__ import annotations

from omr_leadsheet.chord_ops.diff import (
    OMRChord, diff, normalize_chord,
)


def test_normalize_strips_parens() -> None:
    assert normalize_chord("E(b7)") == "eb7"
    assert normalize_chord("Eb7") == "eb7"
    assert normalize_chord("C7(b9)") == "c7b9"
    assert normalize_chord("C7b9") == "c7b9"
    assert normalize_chord("Cm7(b5)") == "cm7b5"
    assert normalize_chord("Cm7b5") == "cm7b5"


def test_normalize_still_strips_whitespace_and_lowercases() -> None:
    assert normalize_chord("G 7") == "g7"
    assert normalize_chord(" Bbm7 ") == "bbm7"


def test_normalize_non_paren_unchanged() -> None:
    assert normalize_chord("Cmaj7") == "cmaj7"
    assert normalize_chord("F#dim") == "f#dim"
    assert normalize_chord("Eb7") == "eb7"


def _omr(value: str, measure: int) -> OMRChord:
    return OMRChord(
        sheet=1, staff=1, value=value,
        x=0.0, y=0.0,
        measure_local=measure, measure_global=measure, measure_frac=0.0,
    )


def test_diff_treats_paren_form_as_already_covered() -> None:
    """If the OMR sees ``C7b9`` and the exported MusicXML carries
    the parens-form ``C7(b9)`` (or vice versa) for the same measure,
    ``diff`` should treat the OMR chord as already-covered and NOT
    report it as missing. Pre-fix the two strings normalised
    differently, so the OMR chord would have been re-inserted on top
    of the existing parens-form entry."""
    omr_chord = _omr("C7b9", 4)
    mxl_with_parens = [(4, "C7(b9)")]
    missing = diff([omr_chord], mxl_with_parens)
    assert missing == [], (
        "OMR's C7b9 should be covered by exported C7(b9) once parens "
        f"are stripped from the normalise key; got missing={missing!r}"
    )


def test_diff_treats_eb7_and_e_paren_b7_as_same() -> None:
    """The user-reported m52 collision in textual form. The
    structural-XML form needs a different fix; this assertion only
    covers the case where both sides are text strings."""
    omr_chord = _omr("Eb7", 1)
    mxl_with_parens = [(1, "E(b7)")]
    missing = diff([omr_chord], mxl_with_parens)
    assert missing == []
