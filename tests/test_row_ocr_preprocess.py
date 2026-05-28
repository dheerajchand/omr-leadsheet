"""Regression: ``_to_music21_figure`` handles paren-around-alterations
and doubled-m OCR mangling (#63).

Spot-check on #11 Slap That Bass found two italic ``<words>``
fallbacks remaining after the earlier preprocess work: ``F7(b5)``
and ``E-mm7``. Both should parse to real ChordSymbols once the
figure is normalised.
"""
from __future__ import annotations

from omr_leadsheet.chord_ops.diff import _to_music21_figure


def test_strips_paren_around_b5_alteration() -> None:
    assert _to_music21_figure("F7(b5)") == "F7b5"
    assert _to_music21_figure("Cm7(b5)") == "Cm7b5"


def test_strips_paren_around_b9_alteration() -> None:
    assert _to_music21_figure("C7(b9)") == "C7b9"
    assert _to_music21_figure("G7(b13)") == "G7b13"


def test_strips_paren_around_sharp_alteration() -> None:
    assert _to_music21_figure("C7(#11)") == "C7#11"
    assert _to_music21_figure("F7(#5)") == "F7#5"


def test_strips_paren_around_add() -> None:
    assert _to_music21_figure("C(add9)") == "Cadd9"


def test_collapses_doubled_m() -> None:
    assert _to_music21_figure("Emm7") == "Em7"
    assert _to_music21_figure("E-mm7") == "E-m7"
    # The combined case (leading-flat + doubled m):
    assert _to_music21_figure("Bbmm7") == "B-m7"


def test_does_not_mangle_add_chord() -> None:
    """Important guard: the 'dd' in 'add' must survive."""
    assert _to_music21_figure("Cadd9") == "Cadd9"
    assert _to_music21_figure("Bbadd9") == "B-add9"


def test_existing_leading_flat_translation_preserved() -> None:
    assert _to_music21_figure("Eb7") == "E-7"
    assert _to_music21_figure("Bb") == "B-"
    assert _to_music21_figure("Cmaj7") == "Cmaj7"


def test_clean_figures_unchanged() -> None:
    assert _to_music21_figure("C") == "C"
    assert _to_music21_figure("G7") == "G7"
    assert _to_music21_figure("F#m7") == "F#m7"


def test_trailing_plus_swapped_for_music21() -> None:
    """#66: 'G9+' (trailing augmented marker on numeric extension)
    is swapped to 'G+9' so music21 parses it as
    augmented-dominant-ninth. Only fires on the plain root+digit+
    form; the quality-letter cases (Gm9+, Cmaj7+) stay verbatim
    because music21 rejects them too."""
    assert _to_music21_figure("G9+") == "G+9"
    assert _to_music21_figure("F7+") == "F+7"
    assert _to_music21_figure("Bb9+") == "B-+9"
    # No swap when quality letter is between root and digit
    assert _to_music21_figure("Gm9+") == "Gm9+"
    assert _to_music21_figure("Cmaj7+") == "Cmaj7+"
    # No swap when '+' isn't trailing
    assert _to_music21_figure("G+9") == "G+9"
    assert _to_music21_figure("G+") == "G+"
