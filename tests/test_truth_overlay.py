"""Tests for the per-song truth overlay (#80a/b). The overlay replaces
each truth-listed measure's chord set with the published chord list,
acting as a final correction for Audiveris's barline-attribution
errors that no upstream pipeline pass can fix without ground truth.
"""
from __future__ import annotations

from music21 import stream, note as m21note, harmony, pitch as m21pitch

from omr_leadsheet.pipeline.truth_overlay import (
    apply_truth_overlay,
    _infer_pitch,
    _inject_notes_from_rests,
)


def _score_with_chord(figure: str, mnum: int = 1) -> stream.Score:
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=mnum)
    m.append(m21note.Note("C4", quarterLength=4.0))
    m.insert(0, harmony.ChordSymbol(figure))
    p.append(m)
    sc.append(p)
    return sc


def test_overlay_replaces_chord_on_listed_measure() -> None:
    sc = _score_with_chord("G7", mnum=1)
    truth = {"measures": {"1": {"chords": ["D"]}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["measures_corrected"] == 1
    assert stats["chords_replaced"] == 1
    assert stats["chords_inserted"] == 1
    chords = list(
        sc.parts[0].recurse().getElementsByClass(harmony.ChordSymbol)
    )
    figs = [str(c.figure) for c in chords]
    assert figs == ["D"], f"expected only ['D']; got {figs}"


def test_overlay_inserts_multiple_chords_evenly_across_measure() -> None:
    sc = _score_with_chord("F", mnum=1)
    truth = {"measures": {"1": {"chords": ["D", "B7", "Em", "D", "A7"]}}}
    apply_truth_overlay(sc, truth)
    m = list(sc.parts[0].getElementsByClass("Measure"))[0]
    chords = [
        (str(c.figure), float(c.offset))
        for c in m.recurse().getElementsByClass(harmony.ChordSymbol)
    ]
    figs = [c[0] for c in chords]
    offsets = [c[1] for c in chords]
    assert figs == ["D", "B7", "Em", "D", "A7"]
    # Even spacing across a 4-quarter measure -> step 0.8
    assert offsets[0] == 0.0
    assert offsets[-1] < 4.0


def test_overlay_skips_measures_not_in_truth() -> None:
    """A measure that doesn't appear in the truth file is left alone."""
    sc = _score_with_chord("G7", mnum=2)
    truth = {"measures": {"1": {"chords": ["D"]}}}  # m1 only, but score has m2
    stats = apply_truth_overlay(sc, truth)
    assert stats["measures_corrected"] == 0
    chords = list(
        sc.parts[0].recurse().getElementsByClass(harmony.ChordSymbol)
    )
    figs = [str(c.figure) for c in chords]
    assert figs == ["G7"], f"untouched measure must keep its chord; got {figs}"


def test_overlay_handles_empty_chord_list() -> None:
    """Truth says 'no chord on this measure' -> remove existing without
    inserting anything."""
    sc = _score_with_chord("G7", mnum=1)
    truth = {"measures": {"1": {"chords": []}}}
    apply_truth_overlay(sc, truth)
    chords = list(
        sc.parts[0].recurse().getElementsByClass(harmony.ChordSymbol)
    )
    assert chords == []


def test_overlay_keeps_lyrics_intact() -> None:
    """Lyrics are not touched -- only chord symbols."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    n = m21note.Note("C4", quarterLength=4.0)
    n.addLyric("hello", lyricNumber=1)
    m.append(n)
    m.insert(0, harmony.ChordSymbol("G7"))
    p.append(m)
    sc.append(p)
    truth = {"measures": {"1": {"chords": ["D"]}}}
    apply_truth_overlay(sc, truth)
    notes = list(sc.parts[0].recurse().notes)
    note_obj = next(n for n in notes if not isinstance(n, harmony.ChordSymbol))
    lyrs = [lyr.text for lyr in note_obj.lyrics]
    assert lyrs == ["hello"]


# --- Note injection tests (#103) ---


def _score_with_rests(n_rests: int, rest_ql: float = 1.0,
                      mnum: int = 1) -> stream.Score:
    """Build a score whose only measure contains *n_rests* rests."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=mnum)
    for i in range(n_rests):
        m.insert(i * rest_ql, m21note.Rest(quarterLength=rest_ql))
    p.append(m)
    sc.append(p)
    return sc


def _score_mixed(n_notes: int, n_rests: int, mnum: int = 1) -> stream.Score:
    """Build a score with *n_notes* notes then *n_rests* rests in one measure."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=mnum)
    offset = 0.0
    for _ in range(n_notes):
        m.insert(offset, m21note.Note("E4", quarterLength=1.0))
        offset += 1.0
    for _ in range(n_rests):
        m.insert(offset, m21note.Rest(quarterLength=1.0))
        offset += 1.0
    p.append(m)
    sc.append(p)
    return sc


def test_inject_converts_rests_to_notes_for_lyrics() -> None:
    """When truth has 3 lyrics but measure has 0 notes (3 rests),
    all 3 rests should become cue-size notes with lyrics attached."""
    sc = _score_with_rests(3, rest_ql=1.0)
    truth = {"measures": {"1": {"lyrics_v1": ["one", "two", "three"]}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["notes_injected"] == 3
    assert stats["lyrics_overridden"] == 1
    m = list(sc.parts[0].getElementsByClass("Measure"))[0]
    notes = [n for n in m.recurse().notes if isinstance(n, m21note.Note)]
    assert len(notes) == 3
    lyrics = [n.lyrics[0].text for n in notes]
    assert lyrics == ["one", "two", "three"]
    for n in notes:
        assert n.style.noteSize == "cue"


def test_inject_fills_deficit_in_mixed_measure() -> None:
    """Measure with 2 notes + 2 rests, truth has 4 lyrics → inject 2."""
    sc = _score_mixed(2, 2)
    truth = {"measures": {"1": {"lyrics_v1": ["a", "b", "c", "d"]}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["notes_injected"] == 2
    m = list(sc.parts[0].getElementsByClass("Measure"))[0]
    notes = [n for n in m.recurse().notes if isinstance(n, m21note.Note)]
    assert len(notes) == 4
    lyrics = [n.lyrics[0].text for n in sorted(notes, key=lambda n: float(n.offset))]
    assert lyrics == ["a", "b", "c", "d"]


def test_inject_no_injection_when_notes_sufficient() -> None:
    """When note count >= lyric count, no injection happens."""
    sc = _score_mixed(3, 1)
    truth = {"measures": {"1": {"lyrics_v1": ["x", "y"]}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["notes_injected"] == 0
    rests = list(sc.parts[0].recurse().getElementsByClass(m21note.Rest))
    assert len(rests) == 1, "rest should be preserved when no injection needed"


def test_inject_uses_explicit_pitch() -> None:
    """inject_pitch in truth spec overrides inferred pitch."""
    sc = _score_with_rests(2, rest_ql=2.0)
    truth = {"measures": {"1": {
        "lyrics_v1": ["hi", "lo"],
        "inject_pitch": "G3",
    }}}
    apply_truth_overlay(sc, truth)
    m = list(sc.parts[0].getElementsByClass("Measure"))[0]
    notes = [n for n in m.recurse().notes if isinstance(n, m21note.Note)]
    for n in notes:
        assert n.pitch.nameWithOctave == "G3"


def test_inject_infers_pitch_from_neighbor() -> None:
    """When no inject_pitch, pitch is inferred from nearest note."""
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    m1.insert(0, m21note.Note("F#5", quarterLength=4.0))
    p.append(m1)
    m2 = stream.Measure(number=2)
    m2.insert(0, m21note.Rest(quarterLength=4.0))
    p.append(m2)
    sc.append(p)
    truth = {"measures": {"2": {"lyrics_v1": ["word"]}}}
    apply_truth_overlay(sc, truth)
    m = list(sc.parts[0].getElementsByClass("Measure"))[1]
    notes = [n for n in m.recurse().notes if isinstance(n, m21note.Note)]
    assert len(notes) == 1
    assert notes[0].pitch.nameWithOctave == "F#5"


def test_inject_subdivides_long_rest() -> None:
    """A whole rest (4.0 ql) should be subdivided into multiple notes."""
    sc = _score_with_rests(1, rest_ql=4.0)
    truth = {"measures": {"1": {"lyrics_v1": ["a", "b", "c", "d"]}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["notes_injected"] == 4
    m = list(sc.parts[0].getElementsByClass("Measure"))[0]
    notes = sorted(
        [n for n in m.recurse().notes if isinstance(n, m21note.Note)],
        key=lambda n: float(n.offset),
    )
    assert len(notes) == 4
    assert float(notes[0].duration.quarterLength) == 1.0


def test_inject_empty_lyrics_clears_without_injection() -> None:
    """lyrics_v1: [] should clear existing lyrics, not inject."""
    sc = _score_mixed(1, 1)
    n = list(sc.parts[0].recurse().notes)[0]
    n.addLyric("old", lyricNumber=1)
    truth = {"measures": {"1": {"lyrics_v1": []}}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["notes_injected"] == 0
    notes = [n for n in sc.parts[0].recurse().notes if isinstance(n, m21note.Note)]
    for n in notes:
        v1 = [lyr for lyr in n.lyrics if (lyr.number or 1) == 1]
        assert v1 == []
