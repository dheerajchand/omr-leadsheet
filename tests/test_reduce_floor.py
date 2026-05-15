"""Sub-vocal-range ghost-note filter in reduce._drop_subvocal_notes.

Regression coverage for issue #10: Audiveris's lossy piano/vocal staff
separation can leak piano-LH notes into the "vocal" part. After the
octave-down transpose those land at MIDI <52 — below singable range.
The filter replaces them with rests of equal duration so the bar's
metric integrity stays intact and the lead sheet shows blank where the
ghost was.
"""
from __future__ import annotations

from music21 import note as m21_note
from music21 import stream as m21_stream

from omr_leadsheet.pipeline.reduce import (
    VOCAL_FLOOR_MIDI,
    _drop_subvocal_notes,
)


def _make_part(pitches: list[str]) -> m21_stream.Part:
    """One measure, one quarter note per pitch token."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    for p in pitches:
        n = m21_note.Note(p)
        n.quarterLength = 1.0
        measure.append(n)
    part.append(measure)
    return part


def test_drops_sub_floor_note_replaces_with_rest() -> None:
    """A D3 (MIDI 50) ghost is replaced by a rest of the same duration;
    the surrounding above-floor notes are untouched.
    """
    part = _make_part(["E4", "D3", "G4"])  # MIDI 64, 50, 67
    dropped = _drop_subvocal_notes(part)

    assert dropped == 1
    measure = part.getElementsByClass("Measure")[0]
    elements = list(measure.notesAndRests)
    assert len(elements) == 3
    # Middle slot is now a Rest of the original quarter duration
    assert isinstance(elements[1], m21_note.Rest)
    assert elements[1].quarterLength == 1.0
    # Bookends survived
    assert isinstance(elements[0], m21_note.Note) and elements[0].nameWithOctave == "E4"
    assert isinstance(elements[2], m21_note.Note) and elements[2].nameWithOctave == "G4"


def test_floor_boundary_inclusive_above_exclusive_below() -> None:
    """A note exactly at VOCAL_FLOOR_MIDI is kept; one MIDI below is dropped."""
    floor_pitch = m21_note.Note()
    floor_pitch.pitch.midi = VOCAL_FLOOR_MIDI
    below = m21_note.Note()
    below.pitch.midi = VOCAL_FLOOR_MIDI - 1

    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    floor_pitch.quarterLength = 1.0
    below.quarterLength = 1.0
    measure.append(floor_pitch)
    measure.append(below)
    part.append(measure)

    dropped = _drop_subvocal_notes(part)
    assert dropped == 1
    elements = list(measure.notesAndRests)
    assert isinstance(elements[0], m21_note.Note)
    assert isinstance(elements[1], m21_note.Rest)


def test_no_op_when_part_is_clean() -> None:
    """A part with all-vocal-range notes passes through unchanged."""
    part = _make_part(["G3", "C4", "E4", "A4"])
    n_before = len(list(part.recurse().notes))

    dropped = _drop_subvocal_notes(part)

    assert dropped == 0
    assert len(list(part.recurse().notes)) == n_before


def test_preserves_duration_when_replacing() -> None:
    """A half-note ghost becomes a half-note rest, not a quarter rest."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    ghost = m21_note.Note("D3")
    ghost.quarterLength = 2.0
    measure.append(ghost)
    part.append(measure)

    _drop_subvocal_notes(part)
    rest = list(measure.notesAndRests)[0]
    assert isinstance(rest, m21_note.Rest)
    assert rest.quarterLength == 2.0
