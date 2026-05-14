"""chord_ops.parser round-trip and edge cases."""
from __future__ import annotations

import pytest

from omr_leadsheet.chord_ops.parser import (
    ALTERATIONS,
    EXTENSIONS,
    QUALITIES,
    ROOTS,
    format_chord,
    parse_chord,
)


@pytest.mark.parametrize(
    "chord",
    ["C", "G7", "Am", "Dm7", "Fmaj7", "F#", "C#m7", "A+"],
)
def test_parse_round_trip_canonical(chord: str) -> None:
    """Round-trip holds for chord strings already in canonical form."""
    fields = parse_chord(chord)
    assert format_chord(fields) == chord


@pytest.mark.parametrize(
    "input,canonical",
    [("Bb", "A#"), ("Ebdim", "D#dim"), ("Aaug", "A+"), ("Gsus4", "Gsus")],
)
def test_parser_canonicalises_aliases(input: str, canonical: str) -> None:
    """Flats become enharmonic sharps, aug/sus get short forms."""
    assert format_chord(parse_chord(input)) == canonical


def test_class_lists_have_sentinels() -> None:
    assert "C" in ROOTS
    assert "major" in QUALITIES
    assert "none" in EXTENSIONS, "extension class list must include the no-extension sentinel"
    assert "none" in ALTERATIONS, "alteration class list must include the no-alteration sentinel"
