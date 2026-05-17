"""ChordSymbol text normalization in reduce._normalize_chord_text.

Regression coverage for #15. The CNN classifier path already routes its
output through ``chord_ops.parser.format_chord``, so it honours
``notation_style``. But Audiveris-recognized chord-name elements flow
straight from ``<chord-name value="...">`` through music21 to MusicXML
without ever passing through ``format_chord`` -- for LCWTO this is the
majority of all chord symbols. Without a normalization pass inside
``reduce_score``, ``NOTATION_STYLE=symbolic`` silently has no effect on
those chords.

The implementation rewrites ``ChordSymbol.chordKindStr`` (which music21
emits as the ``<kind text="...">`` attribute) rather than reassigning
``ChordSymbol.figure``: music21's figure setter re-parses through its
CHORD_TYPES table and rejects symbolic suffixes like ``t``, ``o``, ``0``.
"""
from __future__ import annotations

from pathlib import Path

from music21 import converter, harmony, stream as m21_stream

from omr_leadsheet.pipeline.reduce import _normalize_chord_text


def _part_with(figures: list[str]) -> m21_stream.Part:
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    for f in figures:
        measure.append(harmony.ChordSymbol(f))
    part.append(measure)
    return part


def _suffixes(part: m21_stream.Part) -> list[str]:
    return [
        (cs.chordKindStr or "")
        for cs in part.recurse().getElementsByClass(harmony.ChordSymbol)
    ]


def test_symbolic_rewrites_textual_minor_maj7_and_dim() -> None:
    part = _part_with(["Cm", "Dmaj7", "Edim"])
    rewritten = _normalize_chord_text(part, style="symbolic")
    out = _suffixes(part)
    assert rewritten == 3, out
    assert out == ["-", "t", "o"], out


def test_textual_emits_textual_tokens() -> None:
    part = _part_with(["Cm", "Dmaj7", "Edim"])
    rewritten = _normalize_chord_text(part, style="textual")
    out = _suffixes(part)
    assert rewritten == 3, out
    assert out == ["m", "maj7", "dim"], out


def test_idempotent_second_pass_is_zero_rewrites() -> None:
    part = _part_with(["Cm", "Dmaj7"])
    _normalize_chord_text(part, style="symbolic")
    # Second pass on already-normalized chords should rewrite nothing.
    assert _normalize_chord_text(part, style="symbolic") == 0


def test_returns_zero_when_part_has_no_chords() -> None:
    part = m21_stream.Part()
    part.append(m21_stream.Measure(number=1))
    assert _normalize_chord_text(part, style="symbolic") == 0


def test_emitted_musicxml_carries_kind_text_attribute(tmp_path: Path) -> None:
    """The rewritten suffix must land in <kind text="..."> in MusicXML,
    where MuseScore reads it as the displayed chord-quality glyph."""
    part = _part_with(["Cm"])
    score = m21_stream.Score()
    score.insert(0, part)
    _normalize_chord_text(part, style="symbolic")
    out = tmp_path / "cs.xml"
    score.write("musicxml", fp=str(out))
    xml = out.read_text()
    assert 'text="-"' in xml, xml
    # Structural kind is preserved -- consumers that ignore text still
    # see the correct chord quality.
    assert "<kind" in xml and ">minor<" in xml, xml


def test_structural_kind_is_not_corrupted() -> None:
    part = _part_with(["Cm"])
    _normalize_chord_text(part, style="symbolic")
    cs = next(iter(part.recurse().getElementsByClass(harmony.ChordSymbol)))
    assert cs.chordKind == "minor"
