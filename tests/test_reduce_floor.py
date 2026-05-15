"""Sub-vocal-range ghost-note + vertical-chord cleaner in reduce._drop_subvocal_notes.

Regression coverage for issue #10. Audiveris's lossy piano/vocal staff
separation can leak piano-LH notes into the "vocal" part, surfacing as
two distinct kinds of garbage after the octave-down transpose:

  * single Notes below MIDI 52 (sub-singable bass-clef territory)
  * vertical Chord objects where the top pitch is the actual vocal
    melody and the lower pitches are piano voicing bleed-through

Production data for *Let's Call The Whole Thing Off*: 51 Chord objects
in 53 measures, 34 of which match the second shape exactly.
"""
from __future__ import annotations

from music21 import chord as m21_chord
from music21 import note as m21_note
from music21 import stream as m21_stream

from omr_leadsheet.pipeline.reduce import (
    VOCAL_FLOOR_MIDI,
    _drop_subvocal_notes,
)


def _make_part(pitches: list[str]) -> m21_stream.Part:
    """One measure (numbered 1), one quarter note per pitch token."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    for p in pitches:
        n = m21_note.Note(p)
        n.quarterLength = 1.0
        measure.append(n)
    part.append(measure)
    return part


# --- single-Note path -----------------------------------------------------

def test_drops_sub_floor_note_replaces_with_rest() -> None:
    """A D3 (MIDI 50) ghost is replaced by a rest of the same duration;
    the surrounding above-floor notes are untouched."""
    part = _make_part(["E4", "D3", "G4"])  # MIDI 64, 50, 67
    stats = _drop_subvocal_notes(part)

    assert stats["count"] == 1
    measure = part.getElementsByClass("Measure")[0]
    elements = list(measure.notesAndRests)
    assert len(elements) == 3
    assert isinstance(elements[1], m21_note.Rest)
    assert elements[1].quarterLength == 1.0
    assert isinstance(elements[0], m21_note.Note) and elements[0].nameWithOctave == "E4"
    assert isinstance(elements[2], m21_note.Note) and elements[2].nameWithOctave == "G4"


def test_floor_boundary_inclusive_above_exclusive_below() -> None:
    """A note exactly at VOCAL_FLOOR_MIDI is kept; one MIDI below is dropped."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    floor_pitch = m21_note.Note()
    floor_pitch.pitch.midi = VOCAL_FLOOR_MIDI
    floor_pitch.quarterLength = 1.0
    below = m21_note.Note()
    below.pitch.midi = VOCAL_FLOOR_MIDI - 1
    below.quarterLength = 1.0
    measure.append(floor_pitch)
    measure.append(below)
    part.append(measure)

    stats = _drop_subvocal_notes(part)
    assert stats["count"] == 1
    elements = list(measure.notesAndRests)
    assert isinstance(elements[0], m21_note.Note)
    assert isinstance(elements[1], m21_note.Rest)


def test_no_op_when_part_is_clean_monophonic() -> None:
    """A part with all-vocal-range single notes passes through unchanged."""
    part = _make_part(["G3", "C4", "E4", "A4"])
    n_before = len(list(part.recurse().notes))
    stats = _drop_subvocal_notes(part)
    assert stats["count"] == 0
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


# --- Chord reduction path -------------------------------------------------

def test_chord_with_vocal_top_reduces_to_top_pitch() -> None:
    """The dominant production-data shape: a Chord with the vocal melody
    on top and piano voicing below. After reduction, the Chord becomes a
    single Note at the top pitch — vocal line preserved, piano shed."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    ch = m21_chord.Chord(["D3", "F#3", "A3"])  # MIDIs 50, 54, 57
    ch.quarterLength = 1.0
    measure.append(ch)
    part.append(measure)

    stats = _drop_subvocal_notes(part)

    assert stats["count"] == 1
    elements = list(measure.notesAndRests)
    assert len(elements) == 1
    assert isinstance(elements[0], m21_note.Note)
    assert elements[0].nameWithOctave == "A3"
    assert elements[0].quarterLength == 1.0


def test_chord_with_all_sub_floor_pitches_becomes_rest() -> None:
    """A Chord whose top pitch is itself below the floor — all bleed,
    no melody — becomes a Rest just like a sub-floor Note."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    ch = m21_chord.Chord()
    for midi in (40, 44, 47):  # all below 52
        n = m21_note.Note()
        n.pitch.midi = midi
        ch.add(n.pitch)
    ch.quarterLength = 1.5
    measure.append(ch)
    part.append(measure)

    stats = _drop_subvocal_notes(part)

    assert stats["count"] == 1
    elements = list(measure.notesAndRests)
    assert len(elements) == 1
    assert isinstance(elements[0], m21_note.Rest)
    assert elements[0].quarterLength == 1.5


def test_chord_top_lyric_carries_over() -> None:
    """When a Chord is reduced to its top pitch, any lyric attached to
    the Chord stays attached to the resulting Note. The OMR sometimes
    attaches the vocal syllable to the Chord (which represents the
    vocal note plus piano bleed)."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    ch = m21_chord.Chord(["D3", "F#3", "A3"])
    ch.quarterLength = 1.0
    ch.addLyric("hello")
    measure.append(ch)
    part.append(measure)

    _drop_subvocal_notes(part)

    elements = list(measure.notesAndRests)
    assert isinstance(elements[0], m21_note.Note)
    assert elements[0].nameWithOctave == "A3"
    assert len(elements[0].lyrics) == 1
    assert elements[0].lyrics[0].text == "hello"


def test_clean_chord_still_reduced_to_top() -> None:
    """A Chord with all pitches above the floor is still reduced — the
    vocal part is monophonic by definition; any vertical Chord at all
    is OMR-introduced piano content to be flattened. Just because every
    pitch is in vocal range doesn't mean it's legitimate divisi (lead
    sheets don't have divisi)."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    ch = m21_chord.Chord(["C4", "E4", "G4"])
    ch.quarterLength = 1.0
    measure.append(ch)
    part.append(measure)

    stats = _drop_subvocal_notes(part)
    assert stats["count"] == 1
    elements = list(measure.notesAndRests)
    assert isinstance(elements[0], m21_note.Note)
    assert elements[0].nameWithOctave == "G4"


# --- Voice container recursion --------------------------------------------

def test_notes_inside_voice_are_processed() -> None:
    """Notes inside a Voice container (multi-voice measures) must still
    be seen by the floor guard. The previous implementation walked
    `el.voices` rather than recursing into Voice elements themselves
    and silently skipped these."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=1)
    voice = m21_stream.Voice()
    good = m21_note.Note("E4"); good.quarterLength = 1.0
    ghost = m21_note.Note("D3"); ghost.quarterLength = 1.0
    voice.append(good)
    voice.append(ghost)
    measure.insert(0, voice)
    part.append(measure)

    stats = _drop_subvocal_notes(part)

    assert stats["count"] == 1
    voice_elements = list(voice.notesAndRests)
    assert isinstance(voice_elements[0], m21_note.Note)
    assert isinstance(voice_elements[1], m21_note.Rest)


# --- Drops list / observability -------------------------------------------

def test_drops_list_records_measure_offset_and_replacement() -> None:
    """The `drops` list lets callers debug which bars had ghost content
    without re-walking the score after the fact."""
    part = m21_stream.Part()
    measure = m21_stream.Measure(number=42)
    a = m21_note.Note("E4"); a.quarterLength = 1.0
    b = m21_note.Note("D3"); b.quarterLength = 1.0
    ch = m21_chord.Chord(["D3", "F#3", "A3"]); ch.quarterLength = 1.0
    measure.append(a)
    measure.append(b)
    measure.append(ch)
    part.append(measure)

    stats = _drop_subvocal_notes(part)

    assert stats["count"] == 2
    measure_nums = [d[0] for d in stats["drops"]]
    assert measure_nums == [42, 42]
    replacement_reprs = sorted(d[3] for d in stats["drops"])
    assert replacement_reprs == ["A3", "Rest"]
