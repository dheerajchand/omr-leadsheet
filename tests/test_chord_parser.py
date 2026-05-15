"""chord_ops.parser round-trip and edge cases."""
from __future__ import annotations

import pytest

from omr_leadsheet.chord_ops.parser import (
    ALTERATIONS,
    EXTENSIONS,
    QUALITIES,
    ROOTS,
    ChordFields,
    format_chord,
    normalize_for_musescore,
    parse_chord,
)


# --- canonical round-trip in symbolic style (the default) -----------------

@pytest.mark.parametrize(
    "chord",
    ["C", "G7", "A-", "D-7", "Ft", "F#", "C#-7", "A+", "F#o7", "G0"],
)
def test_parse_round_trip_symbolic(chord: str) -> None:
    """Symbolic-style chords round-trip through parse→format."""
    fields = parse_chord(chord)
    assert fields is not None
    assert format_chord(fields, style="symbolic") == chord


# --- canonical round-trip in textual style --------------------------------

@pytest.mark.parametrize(
    "chord",
    ["C", "G7", "Am", "Dm7", "Fmaj7", "F#", "C#m7", "Aaug", "F#dim7", "Gm7b5"],
)
def test_parse_round_trip_textual(chord: str) -> None:
    """Textual-style chords round-trip through parse→format."""
    fields = parse_chord(chord)
    assert fields is not None
    assert format_chord(fields, style="textual") == chord


# --- alias canonicalisation -----------------------------------------------

@pytest.mark.parametrize(
    "input,canonical_symbolic",
    [
        ("Bb", "A#"),                    # flat → sharp
        ("Ebdim", "D#o"),                # flat root + textual quality
        ("Aaug", "A+"),                  # textual aug → symbolic
        ("Gsus4", "Gsus"),               # sus variants → "sus"
        ("Am", "A-"),                    # textual minor → symbolic
        ("Fmaj7", "Ft"),                # textual maj7 → symbolic triangle
        ("F#dim", "F#o"),                # dim → o
        ("Gø", "G0"),                    # half-dim glyph → 0
        ("F△7", "Ft"),                  # triangle glyph → t7
        ("C♯m7", "C#-7"),                # unicode sharp + minor 7
        ("D△", "Dt"),                    # triangle alone = maj7 (bare t)
        ("CM7", "Ct"),                   # textual M7 → bare t
    ],
)
def test_parser_canonicalises_aliases(input: str, canonical_symbolic: str) -> None:
    """All quality aliases reduce to the canonical symbolic form."""
    assert format_chord(parse_chord(input), style="symbolic") == canonical_symbolic


# --- the 9-over-7 stacking preservation -----------------------------------

def test_nine_over_seven_emits_literal_97() -> None:
    """MuseScore parses `9` and `97` as distinct chord descriptors with
    different playback voicings (handbook + empirical playback), so the
    formatter must preserve the literal stacking, not collapse to `9` or
    emit a slash-bass form like `9/7`.
    """
    f = parse_chord("G97")
    assert f is not None
    assert f.extension == "9_over_7"
    assert format_chord(f, style="symbolic") == "G97"
    assert format_chord(f, style="textual") == "G97"


def test_nine_over_seven_no_slash() -> None:
    """Specifically: never emit `/7`, which MuseScore parses as a slash-
    bass note rather than a chord extension.
    """
    f = parse_chord("F#97")
    assert "/" not in format_chord(f, style="symbolic")
    assert "/" not in format_chord(f, style="textual")


# --- unicode normalization -------------------------------------------------

@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("F♯m7", "F#m7"),
        ("B♭", "Bb"),
        ("C°7", "Co7"),
        ("Cø", "C0"),
        ("F△7", "Ft7"),  # mechanical glyph→ASCII; canonicalisation is parser's job
        ("C–", "C-"),  # en-dash → hyphen
    ],
)
def test_normalize_for_musescore(raw: str, normalized: str) -> None:
    assert normalize_for_musescore(raw) == normalized


# --- class lists -----------------------------------------------------------

def test_class_lists_have_sentinels() -> None:
    assert "C" in ROOTS
    assert "major" in QUALITIES
    assert "half-dim" in QUALITIES, "half-diminished must be a recognised quality"
    assert "none" in EXTENSIONS, "extension class list must include the no-extension sentinel"
    assert "none" in ALTERATIONS, "alteration class list must include the no-alteration sentinel"
