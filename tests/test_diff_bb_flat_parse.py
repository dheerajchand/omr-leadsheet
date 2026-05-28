"""Regression: Bb-rooted chord-symbols parse into real ChordSymbols
rather than falling through to italic TextExpression fallback (#47).

music21's ChordSymbol parser treats lowercase ``b`` as a chord-quality
abbreviation, not a flat accidental, so common chord-row spellings
like ``Bb``, ``Bbm6``, ``Bbm`` raised ValueError and ``insert_missing``
inserted them as ``<words font-style="italic">`` instead of proper
``<harmony>`` elements.

The fix translates the leading root-letter ``b`` to ``-`` (music21's
flat marker) before parsing, so ``Bb`` -> ``B-``, ``Bbm6`` ->
``B-m6``. The ``b`` inside parenthetical alterations (``Cm7(b5)``)
is preserved.
"""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.chord_ops.diff import OMRChord, _to_music21_figure, insert_missing


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
        <key><fifths>-2</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <note><pitch><step>B</step><alter>-1</alter><octave>4</octave></pitch>
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


def test_to_music21_figure_translates_leading_flat() -> None:
    assert _to_music21_figure("Bb") == "B-"
    assert _to_music21_figure("Bbm6") == "B-m6"
    assert _to_music21_figure("Bbm") == "B-m"
    assert _to_music21_figure("Bb7") == "B-7"
    assert _to_music21_figure("Eb") == "E-"
    assert _to_music21_figure("Ebmaj7") == "E-maj7"
    assert _to_music21_figure("Abm7") == "A-m7"


def test_to_music21_figure_preserves_inner_b_but_strips_parens() -> None:
    """The leading root-letter flat is translated; parens around
    alterations are also stripped (#63), so the inner ``b`` survives
    as a music21-parseable alteration token."""
    assert _to_music21_figure("Cm7(b5)") == "Cm7b5"
    assert _to_music21_figure("G7(b9)") == "G7b9"
    # Leading flat AND parenthetical inner alteration:
    # leading 'Bb' -> 'B-' AND '(b5)' -> 'b5'.
    assert _to_music21_figure("Bbm7(b5)") == "B-m7b5"


def test_to_music21_figure_leaves_non_flat_roots_alone() -> None:
    assert _to_music21_figure("Bdim") == "Bdim"
    assert _to_music21_figure("Bm") == "Bm"
    assert _to_music21_figure("Bsus4") == "Bsus4"
    assert _to_music21_figure("B") == "B"
    assert _to_music21_figure("F#") == "F#"
    assert _to_music21_figure("C#m7") == "C#m7"


def test_to_music21_figure_leaves_already_hyphen_form_alone() -> None:
    """Idempotent on the already-translated form."""
    assert _to_music21_figure("B-") == "B-"
    assert _to_music21_figure("B-m6") == "B-m6"


def test_bb_chord_emits_real_harmony_not_italic_text(tmp_path: Path) -> None:
    """End-to-end: a row-OCR'd ``Bb`` chord lands as a proper
    ``<harmony>`` element with ``root-alter=-1``, not as
    ``<words font-style="italic">``."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    inserted = insert_missing(str(src), [_omr_chord("Bb", 1)], str(out))
    assert inserted == 1

    xml = out.read_text(encoding="utf-8")
    assert "<harmony" in xml, f"Bb should emit a <harmony>; output:\n{xml}"
    assert "<root-step>B</root-step>" in xml
    assert "<root-alter>-1</root-alter>" in xml
    # The italic TextExpression fallback must NOT fire.
    assert 'font-style="italic"' not in xml, (
        f"Bb should not fall through to italic TextExpression; output:\n{xml}"
    )


def test_bbm6_round_trips_to_minor_sixth_chord(tmp_path: Path) -> None:
    """``Bbm6`` previously failed to parse and rendered as italic
    text. Post-fix it should parse to a minor-sixth chord with root
    B-flat."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    insert_missing(str(src), [_omr_chord("Bbm6", 1)], str(out))

    xml = out.read_text(encoding="utf-8")
    assert "<root-step>B</root-step>" in xml
    assert "<root-alter>-1</root-alter>" in xml
    assert "minor-sixth" in xml
    assert 'font-style="italic"' not in xml


def test_bb6_parses_to_major_sixth_after_translation(tmp_path: Path) -> None:
    """Side benefit: ``Bb6`` previously "parsed" but with the wrong
    kind (major) and the wrong root (B-natural). After translation to
    ``B-6`` music21 produces major-sixth with root B-flat."""
    src = tmp_path / "src.musicxml"
    out = tmp_path / "out.musicxml"
    src.write_text(_minimal_score_xml(), encoding="utf-8")

    insert_missing(str(src), [_omr_chord("Bb6", 1)], str(out))

    xml = out.read_text(encoding="utf-8")
    assert "<root-step>B</root-step>" in xml
    assert "<root-alter>-1</root-alter>" in xml
    assert "major-sixth" in xml, (
        "Bb6 should now parse to major-sixth (the 6 was being silently "
        "dropped before the fix); output was:\n" + xml
    )
