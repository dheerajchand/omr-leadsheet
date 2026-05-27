"""Regression: stacked 9-over-7 chord-symbols emit kind="other" so
MuseScore honours the text="97" override (#42).

Before the fix, ``chord_ops/diff.insert_missing`` constructed the
stacked dom-9-over-7 ChordSymbol via ``harmony.ChordSymbol("F#9")``
and set ``chordKindStr = "97"``. music21 then emitted
``<kind text="97">dominant-ninth</kind>`` -- but MuseScore parses
``dominant-ninth`` from its internal chord grammar and renders the
canonical "9" glyph, ignoring the text. The "7" of the stacked
9-over-7 is lost.

The fix also sets ``cs.chordKind = "other"`` when the override is
"97", so music21 emits ``<kind text="97">other</kind>``. MuseScore
has no canonical glyph for ``other`` and falls back to the text.
"""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.chord_ops.diff import OMRChord, insert_missing


def _minimal_score_xml() -> str:
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
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>D</step><octave>5</octave></pitch>
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


def test_stacked_97_emits_other_kind_with_text_override(tmp_path: Path) -> None:
    """``F#9/7`` should round-trip to ``<kind text="97">other</kind>``
    so MuseScore renders the stacked 9-over-7 typography."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    inserted = insert_missing(str(src), [_omr_chord("F#9/7", 1)], str(out))
    assert inserted == 1

    xml = out.read_text(encoding="utf-8")
    assert 'text="97"' in xml, (
        "stacked 9/7 must preserve the text=\"97\" override; "
        f"output was:\n{xml}"
    )
    assert "<kind>other</kind>" in xml or 'text="97">other<' in xml, (
        "stacked 9/7 must emit kind='other' so MuseScore honours text; "
        f"output was:\n{xml}"
    )
    # Negative check: must NOT keep the dominant-ninth structural kind,
    # because that's exactly what MuseScore re-parses and clobbers the
    # text override.
    assert "dominant-ninth" not in xml, (
        "stacked 9/7 must NOT keep kind='dominant-ninth' -- MuseScore "
        "re-parses that and renders only the 9; got:\n" + xml
    )


def test_non_97_stack_keeps_original_kind(tmp_path: Path) -> None:
    """The kind=\"other\" switch is scoped to the 97 case. A 6/5
    stacked figured-bass style (rare in jazz but possible) keeps the
    slash form in the text override and the original parsed kind."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    inserted = insert_missing(str(src), [_omr_chord("D6/5", 1)], str(out))
    assert inserted == 1

    xml = out.read_text(encoding="utf-8")
    # The 6/5 case must NOT trip the kind="other" override.
    # (It may or may not have text="6/5" depending on how music21
    # serialises non-9/7 stacks; we only assert the negative.)
    assert "<kind>other</kind>" not in xml
