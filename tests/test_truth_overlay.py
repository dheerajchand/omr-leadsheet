"""Tests for the per-song truth overlay (#80a/b). The overlay replaces
each truth-listed measure's chord set with the published chord list,
acting as a final correction for Audiveris's barline-attribution
errors that no upstream pipeline pass can fix without ground truth.
"""
from __future__ import annotations

from music21 import stream, note as m21note, harmony

from omr_leadsheet.pipeline.truth_overlay import apply_truth_overlay


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
