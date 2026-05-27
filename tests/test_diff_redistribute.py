"""Regression: same-offset chord-symbol stacks get redistributed using
the row-OCR's x-coordinate-derived ``measure_frac`` (#43).

Symptom on #13 LCWTO: Audiveris collapsed two sequential chord changes
(e.g. ``B-`` then ``D6`` on beats 1 and 3 of a cut-time bar) to offset 0
within the measure, which MuseScore renders as a vertical stack. The
fix walks every measure that has shared-offset harmonies, looks each
one up in the OMRChord list by figure, and rewrites its offset to the
``measure_frac`` the row-OCR detected.

This test fabricates the stack condition directly so the redistribute
pass can be exercised without a full pipeline run.
"""
from __future__ import annotations

from pathlib import Path

from music21 import converter, harmony

from omr_leadsheet.chord_ops.diff import OMRChord, insert_missing


def _two_bar_score_xml() -> str:
    """Two cut-time measures, P1 already carrying TWO chord-symbols at
    offset 0 in measure 1 (the stack we want redistributed). The
    ``<offset>0</offset>`` makes both harmonies anchor to the first
    note in the measure."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC
    "-//Recordare//DTD MusicXML 4.0 Partwise//EN"
    "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Voice</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>4</divisions>
        <key><fifths>2</fifths></key>
        <time><beats>2</beats><beat-type>2</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <harmony><root><root-step>B</root-step></root>
        <kind text="-">minor</kind></harmony>
      <harmony><root><root-step>D</root-step></root>
        <kind text="6">major-sixth</kind></harmony>
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>8</duration><type>half</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>8</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>
"""


def _omr_chord(value: str, measure: int, frac: float) -> OMRChord:
    return OMRChord(
        sheet=1, staff=1, value=value,
        x=0.0, y=0.0,
        measure_local=measure, measure_global=measure, measure_frac=frac,
    )


def test_stacked_harmonies_get_redistributed_by_measure_frac(tmp_path: Path) -> None:
    """B- at frac=0.0 and D6 at frac=0.5 should land on distinct offsets
    after the redistribute pass."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_two_bar_score_xml(), encoding="utf-8")

    # No insertions needed -- both chord-symbols already exist in the
    # source. We pass them as all_omr so the redistribute pass has the
    # frac data.
    all_omr = [
        _omr_chord("Bm", 1, frac=0.0),
        _omr_chord("D6", 1, frac=0.5),
    ]
    insert_missing(str(src), missing=[], out_path=str(out), all_omr=all_omr)

    score = converter.parse(str(out))
    m1 = next(
        m for p in score.parts
        for m in p.getElementsByClass("Measure")
        if m.number == 1
    )
    harmonies = list(m1.recurse().getElementsByClass(harmony.ChordSymbol))
    offsets = sorted(float(h.offset) for h in harmonies)
    assert len(offsets) == 2
    assert offsets[0] != offsets[1], (
        f"after redistribute the two harmonies should be at distinct "
        f"offsets, got {offsets!r}"
    )


def test_no_redistribute_without_all_omr(tmp_path: Path) -> None:
    """When ``all_omr`` is not passed, behaviour is unchanged from
    the pre-fix state -- harmonies remain stacked. Guards against
    accidentally regressing the no-data path."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_two_bar_score_xml(), encoding="utf-8")

    insert_missing(str(src), missing=[], out_path=str(out))

    score = converter.parse(str(out))
    m1 = next(
        m for p in score.parts
        for m in p.getElementsByClass("Measure")
        if m.number == 1
    )
    harmonies = list(m1.recurse().getElementsByClass(harmony.ChordSymbol))
    offsets = sorted(float(h.offset) for h in harmonies)
    assert len(offsets) == 2
    assert offsets[0] == offsets[1], (
        "without all_omr the redistribute pass should be a no-op"
    )


def test_redistribute_skips_when_no_omr_match(tmp_path: Path) -> None:
    """A stacked harmony whose figure has no matching OMRChord is left
    alone (Policy A only -- Policy B fallback is out of scope here)."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_two_bar_score_xml(), encoding="utf-8")

    # OMR list only has one of the two stacked figures.
    all_omr = [_omr_chord("Bm", 1, frac=0.0)]
    insert_missing(str(src), missing=[], out_path=str(out), all_omr=all_omr)

    score = converter.parse(str(out))
    m1 = next(
        m for p in score.parts
        for m in p.getElementsByClass("Measure")
        if m.number == 1
    )
    harmonies = list(m1.recurse().getElementsByClass(harmony.ChordSymbol))
    # Bm has frac=0.0 which already matches its current offset, so no
    # move. D6 has no OMR match, so no move. Stack stays.
    assert len(harmonies) == 2
