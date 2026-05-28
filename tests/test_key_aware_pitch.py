"""Regression: vocal-staff notes whose step is altered by the key
signature but which Audiveris emitted without an <alter> get the
key-signature alteration applied (#84).

Symptom on #13 LCWTO m19/m21: 'ee-ther' notes came through Audiveris
as <step>F</step> with no <alter> in a G-major key signature. Per
MusicXML spec that is F-natural, and MuseScore correctly draws a
natural sign. The published score had no natural -- the F was F# by
key signature implication."""
from __future__ import annotations

from music21 import stream, note as m21note, key, pitch

from omr_leadsheet.pipeline.key_aware_pitch import (
    apply_key_signature_to_implicit_notes,
)


def _score_with_key(sharps: int, notes: list[tuple[str, str | None]]) -> stream.Score:
    """Build a single-part score with given KeySignature.fifths and
    a sequence of (step_with_octave, accidental_name_or_None) notes."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    m.insert(0, key.KeySignature(sharps))
    for step_oct, acc in notes:
        n = m21note.Note(step_oct)
        # Force the explicit accidental from MusicXML serialization shape
        if acc is None:
            n.pitch.accidental = None
        else:
            n.pitch.accidental = pitch.Accidental(acc)
        m.append(n)
    p.append(m)
    sc.append(p)
    return sc


def test_f_natural_in_g_major_becomes_f_sharp() -> None:
    """The core #84 case: F-step with no accidental in G-major key sig
    gets F# applied."""
    sc = _score_with_key(1, [("F4", None), ("F4", None), ("F4", None)])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 3
    notes = list(sc.parts[0].recurse().notes)
    for n in notes:
        assert n.pitch.accidental is not None
        assert n.pitch.accidental.name == "sharp"
        assert n.pitch.nameWithOctave == "F#4"


def test_explicit_natural_is_preserved() -> None:
    """An F note with an explicit natural sign in G major must stay
    F-natural -- the published composer wrote it that way on purpose."""
    sc = _score_with_key(1, [("F4", "natural")])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 0
    n = list(sc.parts[0].recurse().notes)[0]
    assert n.pitch.accidental is not None
    assert n.pitch.accidental.name == "natural"


def test_explicit_sharp_unchanged() -> None:
    """An F-sharp note already correctly emitted by Audiveris must
    stay F-sharp (no double-fix)."""
    sc = _score_with_key(1, [("F4", "sharp")])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 0


def test_steps_not_in_key_sig_unchanged() -> None:
    """G, D, A in G major are NOT in the altered-pitch set, so the
    function must leave them alone."""
    sc = _score_with_key(1, [("G4", None), ("D4", None), ("A4", None)])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 0


def test_no_key_sig_leaves_everything_alone() -> None:
    """C-major (0 sharps/flats): nothing is altered by key sig."""
    sc = _score_with_key(0, [("F4", None), ("B4", None), ("C4", None)])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 0


def test_d_major_alters_f_and_c() -> None:
    """D major (2 sharps): both F and C step notes without an
    accidental get a sharp."""
    sc = _score_with_key(2, [("F4", None), ("C4", None), ("G4", None)])
    n_fixed = apply_key_signature_to_implicit_notes(sc)
    assert n_fixed == 2  # G is untouched
    notes = list(sc.parts[0].recurse().notes)
    assert notes[0].pitch.nameWithOctave == "F#4"
    assert notes[1].pitch.nameWithOctave == "C#4"
    assert notes[2].pitch.nameWithOctave == "G4"


def test_key_change_mid_part_uses_active_signature() -> None:
    """Two measures: m1 in D major, m2 in C major. A bare F in m1
    becomes F#, a bare F in m2 stays F."""
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    m1.insert(0, key.KeySignature(2))  # D major
    m1.append(m21note.Note("F4"))
    m2 = stream.Measure(number=2)
    m2.insert(0, key.KeySignature(0))  # C major
    m2.append(m21note.Note("F4"))
    p.append(m1)
    p.append(m2)
    sc.append(p)

    apply_key_signature_to_implicit_notes(sc)
    notes = list(sc.parts[0].recurse().notes)
    assert notes[0].pitch.nameWithOctave == "F#4", "m1 F should be sharpened"
    assert notes[1].pitch.nameWithOctave == "F4", "m2 F should stay natural"
