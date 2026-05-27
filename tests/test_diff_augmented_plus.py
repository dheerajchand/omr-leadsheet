"""Regression: augmented chord-symbols inserted by chord_ops/diff carry
the `+` display override (#41).

Before the fix, ``harmony.ChordSymbol("Caug")`` parsed to
``chordKind="augmented"`` with no ``chordKindStr`` set, so the emitted
MusicXML wrote ``<kind>augmented</kind>`` without a ``text=`` attribute.
MuseScore then rendered the chord using its default style preset
("aug"). The fix forces ``chordKindStr = "+"`` after parsing.
"""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.chord_ops.diff import OMRChord, insert_missing


def _minimal_score_xml() -> str:
    """One-part one-measure MusicXML that ``insert_missing`` will treat
    as the target part. The part has no chord-symbols, so the function's
    "first part with any ChordSymbol" detection falls back to parts[0]."""
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
        <key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>16</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


def _omr_chord(value: str, measure: int) -> OMRChord:
    return OMRChord(
        sheet=1, staff=1, value=value,
        x=0.0, y=0.0,
        measure_local=measure, measure_global=measure, measure_frac=0.0,
    )


def test_augmented_chord_gets_plus_display_override(tmp_path: Path) -> None:
    """A ``Caug`` row-OCR'd chord ends up in the output MusicXML with
    ``<kind text="+">augmented</kind>`` so MuseScore renders ``C+``."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    inserted = insert_missing(str(src), [_omr_chord("Caug", 1)], str(out))
    assert inserted == 1

    xml = out.read_text(encoding="utf-8")
    assert 'text="+"' in xml, (
        "augmented chord-symbol should carry text=\"+\" override; "
        f"output was:\n{xml}"
    )
    assert "augmented" in xml, "structural kind must remain 'augmented'"


def test_plain_augmented_figure_also_gets_plus_override(tmp_path: Path) -> None:
    """`A+` (the canonical symbolic form) round-trips: music21 parses
    it to chordKind=augmented and the post-parse hook still applies
    the override idempotently (or leaves an existing override alone)."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    inserted = insert_missing(str(src), [_omr_chord("A+", 1)], str(out))
    assert inserted == 1

    xml = out.read_text(encoding="utf-8")
    assert 'text="+"' in xml
