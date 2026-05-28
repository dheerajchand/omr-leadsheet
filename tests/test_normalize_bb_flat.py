"""Regression: ``normalize_chord`` unifies ``Bb`` lay spelling with
``B-`` music21 spelling (#59).

After PR #50 (#47), the row-OCR-emitted ``Eb7`` is translated to
``E-7`` for music21 parsing. But the dedup comparison in
``insert_missing`` used the original ``c.value`` ("Eb7") against
music21's reconstructed ``ex.figure`` ("E-7"). The two normalised
keys differed (``eb7`` vs ``e-7``) → dedup missed and a stack
survived on #13 m52.

The fix extends ``normalize_chord`` to translate the leading
flat-spelling so both forms share a key.
"""
from __future__ import annotations

from omr_leadsheet.chord_ops.diff import normalize_chord


def test_lay_flat_unifies_with_music21_hyphen() -> None:
    assert normalize_chord("Eb7") == normalize_chord("E-7")
    assert normalize_chord("Bb") == normalize_chord("B-")
    assert normalize_chord("Bbm6") == normalize_chord("B-m6")
    assert normalize_chord("Abmaj7") == normalize_chord("A-maj7")
    assert normalize_chord("Gb") == normalize_chord("G-")


def test_paren_strip_still_works() -> None:
    """The #49 paren-strip from PR #53 stays in effect."""
    assert normalize_chord("E(b7)") == normalize_chord("Eb7")
    assert normalize_chord("C7(b9)") == normalize_chord("C7b9")


def test_inner_b_preserved() -> None:
    """The regex is anchored to position 0 -- ``b`` inside
    parenthetical alterations is left alone (other than paren-strip).
    """
    # Both should normalise to the same paren-stripped form.
    assert normalize_chord("Cm7(b5)") == normalize_chord("Cm7b5")
    # The leading 'C' doesn't have a 'b' after it -- regex doesn't fire.
    assert normalize_chord("Cm7b5") == "cm7b5"


def test_non_flat_roots_unchanged() -> None:
    assert normalize_chord("Bdim") == "bdim"
    assert normalize_chord("Bsus4") == "bsus4"
    assert normalize_chord("F#m7") == "f#m7"
    assert normalize_chord("Cmaj7") == "cmaj7"


def test_already_hyphen_form_idempotent() -> None:
    assert normalize_chord("B-") == "b-"
    assert normalize_chord("E-m7") == "e-m7"


def test_lowercase_input_also_translates() -> None:
    """The translation runs after lowercasing so any case input
    converges on the same canonical form."""
    assert normalize_chord("eb7") == "e-7"
    assert normalize_chord("BB7") == "b-7"   # all-caps lay flat
    assert normalize_chord("Bb7") == normalize_chord("bb7")
