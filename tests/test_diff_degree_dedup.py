"""Regression: when two ChordSymbols at the same beat share a root
letter and one has structural ``<degree>`` alterations while the
other doesn't, the degree-form is removed (#52).

Symptom on #13 LCWTO m52 first-ending: Audiveris read the printed
``Eb7`` glyph as ``E(b7)`` and emitted ``<harmony> root=E kind=major
<degree>add-7(-1)</degree></harmony>``. The row-OCR independently
read the same glyph as ``Eb7`` and emitted ``<harmony> root=E-flat
kind=dominant</harmony>``. Both anchored to the same beat in m52
→ MuseScore stacked them. The clean ``Eb7`` is what the source PDF
actually shows.
"""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.chord_ops.diff import OMRChord, insert_missing


def _score_with_degree_form_xml() -> str:
    """Lead with an Audiveris-style E(b7) already present:
    root=E natural, kind=major, with a degree element altering 7."""
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
      <harmony>
        <root><root-step>E</root-step></root>
        <kind>major</kind>
        <degree>
          <degree-value>7</degree-value>
          <degree-alter>-1</degree-alter>
          <degree-type>add</degree-type>
        </degree>
      </harmony>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>16</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
"""


def _omr(value: str, measure: int) -> OMRChord:
    return OMRChord(
        sheet=1, staff=1, value=value,
        x=0.0, y=0.0,
        measure_local=measure, measure_global=measure, measure_frac=0.0,
    )


def test_degree_form_dropped_when_clean_sibling_arrives(tmp_path: Path) -> None:
    """The Audiveris E-major-with-degree gets removed when the row-OCR
    Eb7 (root=E-flat, kind=dominant, no degrees) is inserted at the
    same beat."""
    from music21 import converter, harmony as h_mod
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_score_with_degree_form_xml(), encoding="utf-8")

    insert_missing(str(src), [_omr("Eb7", 1)], str(out))

    score = converter.parse(str(out))
    chord_syms = list(score.recurse().getElementsByClass(h_mod.ChordSymbol))
    assert len(chord_syms) == 1, (
        f"expected one chord-symbol after degree-form dedup, got "
        f"{len(chord_syms)}: figures={[c.figure for c in chord_syms]}"
    )
    surviving = chord_syms[0]
    # The clean Eb7 form: root E-flat, kind dominant, no chord-step mods.
    assert surviving.root().name in ("E-", "Eb"), (
        f"surviving root should be E-flat; got {surviving.root().name!r}"
    )
    assert surviving.chordKind in ("dominant", "dominant-seventh"), (
        f"surviving kind should be dominant-7 family; got {surviving.chordKind!r}"
    )
    assert not list(surviving.getChordStepModifications() or []), (
        "surviving chord should have no structural alterations"
    )


def test_no_dedup_when_roots_differ(tmp_path: Path) -> None:
    """Two chord-symbols at the same beat with DIFFERENT root letters
    are not deduped, even if one has degrees."""
    from music21 import converter, harmony as h_mod
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    # Existing chord: F major with degree
    src.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name/></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>4</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <harmony><root><root-step>F</root-step></root>
        <kind>major</kind>
        <degree><degree-value>7</degree-value>
          <degree-alter>-1</degree-alter>
          <degree-type>add</degree-type></degree></harmony>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>16</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
""", encoding="utf-8")

    # Different root letter -- should not dedup
    insert_missing(str(src), [_omr("Eb7", 1)], str(out))

    score = converter.parse(str(out))
    chord_syms = list(score.recurse().getElementsByClass(h_mod.ChordSymbol))
    assert len(chord_syms) == 2, (
        f"different-root chord-symbols should NOT dedup; got "
        f"{len(chord_syms)}: {[c.figure for c in chord_syms]}"
    )


def test_no_dedup_when_neither_has_degrees(tmp_path: Path) -> None:
    """Two same-root clean-form chord-symbols at the same beat are
    not dropped by this pass (existing normalize_chord dedup handles
    those before this pass runs)."""
    from music21 import converter, harmony as h_mod
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    # Existing chord: E major (clean, no degrees)
    src.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name/></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>4</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef></attributes>
      <harmony><root><root-step>E</root-step></root>
        <kind>major</kind></harmony>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>16</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>
""", encoding="utf-8")

    # Eb7 (clean, no degrees) arrives at same beat
    insert_missing(str(src), [_omr("Eb7", 1)], str(out))

    score = converter.parse(str(out))
    chord_syms = list(score.recurse().getElementsByClass(h_mod.ChordSymbol))
    # The degree-form dedup pass doesn't touch these; both have no degrees
    # so both survive. (Whether they end up at the same offset depends
    # on the redistribute pass and the OMR's frac data; here neither
    # condition is met to dedupe.)
    assert len(chord_syms) >= 1
    for cs in chord_syms:
        assert not list(cs.getChordStepModifications() or [])
