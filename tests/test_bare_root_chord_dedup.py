"""Regression: row-OCR sometimes splits a single chord glyph like "A7"
into two separate reads, "A" and "A7", landing both in the same chord
row at nearby x-coordinates. The bare-root version is tesseract noise.

Symptom on #13 LCWTO m26: published chord row above "off!" measure has
"A7 D7"; our pipeline produced "A A7 D7" because tesseract row-OCR
read the chord row strip as two separate tokens (the leading "A" of
"A7" picked up before the full "A7" was captured).

Audiveris-detected <chord-name> elements are NOT touched -- only row-OCR
duplicates are removed -- so legitimate "A | A7" jazz changes that
Audiveris correctly identifies are preserved.
"""
from __future__ import annotations

from omr_leadsheet.chord_ops.diff import OMRChord


def _dedup(chords: list[OMRChord]) -> list[OMRChord]:
    """Run the same dedup logic used in extract_omr_chords without the
    OMR file parsing. Pulled out so we can hit it in unit tests."""
    import re as _re
    BARE_ROOT_RE = _re.compile(r"^[A-G][b#]?$")
    BARE_DEDUP_X_PIXELS = 200
    keep = [True] * len(chords)
    for i, ci in enumerate(chords):
        if ci.source != "row":
            continue
        if not BARE_ROOT_RE.match(ci.value or ""):
            continue
        for j, cj in enumerate(chords):
            if i == j or cj.source != "row":
                continue
            if cj.measure_global != ci.measure_global:
                continue
            if not cj.value or cj.value == ci.value:
                continue
            if not cj.value.startswith(ci.value):
                continue
            if abs(cj.x - ci.x) <= BARE_DEDUP_X_PIXELS:
                keep[i] = False
                break
    return [c for c, k in zip(chords, keep) if k]


def test_row_ocr_bare_root_dropped_when_extended_form_nearby() -> None:
    """The #80c case: row-OCR emits both 'A' at x=221 and 'A7' at x=370
    in the same measure. The bare 'A' is dropped."""
    chords = [
        OMRChord(sheet=1, staff=1, value="A", x=221, y=205,
                 measure_global=26, measure_frac=0.35, source="row"),
        OMRChord(sheet=1, staff=1, value="A7", x=370, y=205,
                 measure_global=26, measure_frac=0.59, source="row"),
        OMRChord(sheet=1, staff=1, value="D7", x=484, y=176,
                 measure_global=26, measure_frac=0.77, source="audi"),
    ]
    result = _dedup(chords)
    values = [c.value for c in result]
    assert "A" not in values
    assert "A7" in values
    assert "D7" in values


def test_audiveris_bare_root_kept_even_with_extended_form() -> None:
    """When Audiveris itself detects both 'A' and 'A7' as chord-names,
    trust both -- they're legitimate jazz changes (e.g. 'A | A7' over
    one measure). The dedup only fires on row-OCR-sourced chords."""
    chords = [
        OMRChord(sheet=1, staff=1, value="A", x=221, y=205,
                 measure_global=26, measure_frac=0.35, source="audi"),
        OMRChord(sheet=1, staff=1, value="A7", x=370, y=205,
                 measure_global=26, measure_frac=0.59, source="audi"),
    ]
    result = _dedup(chords)
    values = [c.value for c in result]
    assert "A" in values
    assert "A7" in values


def test_bare_root_kept_when_far_from_extended_form() -> None:
    """If a bare 'A' and 'A7' are more than 200px apart in the same
    measure, they're probably DIFFERENT chord changes. Keep both."""
    chords = [
        OMRChord(sheet=1, staff=1, value="A", x=100, y=205,
                 measure_global=26, measure_frac=0.10, source="row"),
        OMRChord(sheet=1, staff=1, value="A7", x=600, y=205,
                 measure_global=26, measure_frac=0.90, source="row"),
    ]
    result = _dedup(chords)
    values = [c.value for c in result]
    assert "A" in values
    assert "A7" in values


def test_bare_root_kept_when_extended_form_in_different_measure() -> None:
    """Cross-measure same-root chords stay -- they're independent."""
    chords = [
        OMRChord(sheet=1, staff=1, value="A", x=221, y=205,
                 measure_global=25, measure_frac=0.99, source="row"),
        OMRChord(sheet=1, staff=1, value="A7", x=370, y=205,
                 measure_global=26, measure_frac=0.10, source="row"),
    ]
    result = _dedup(chords)
    values = [c.value for c in result]
    assert "A" in values
    assert "A7" in values


def test_bare_root_kept_when_no_extended_form_match() -> None:
    """A bare 'A' with no same-root extended form anywhere -- keep it."""
    chords = [
        OMRChord(sheet=1, staff=1, value="A", x=221, y=205,
                 measure_global=26, measure_frac=0.35, source="row"),
        OMRChord(sheet=1, staff=1, value="D7", x=484, y=176,
                 measure_global=26, measure_frac=0.77, source="row"),
    ]
    result = _dedup(chords)
    values = [c.value for c in result]
    assert "A" in values
