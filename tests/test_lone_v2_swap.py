"""Regression: lone-v2 measures get verse numbers swapped to v1 (#61).

Audiveris classifies lyrics by their vertical position relative to
the staff. In a 1st-ending bracketed block containing only verse 1
text, the single lyric line can land at the y-coordinate where
verse 2 would normally appear, and Audiveris mis-labels it verse=2.
The pre-NW swap pass in spell_check corrects measures where v1 is
completely absent but v2 has lyrics.
"""
from __future__ import annotations

from music21 import converter, note as m21_note, stream

from omr_leadsheet.pipeline.spell_check import _swap_lone_v2_measures_to_v1


def _score_with_lone_v2_measure() -> stream.Score:
    """Build a minimal 2-measure score programmatically: m1 has both
    v1 and v2 lyrics (a normal refrain measure); m2 has ONLY v2
    lyrics (the buggy 1st-ending pattern)."""
    sc = stream.Score()
    part = stream.Part()
    # m1: paired-verse normal measure
    m1 = stream.Measure(number=1)
    n1 = m21_note.Note("C5", quarterLength=1.0)
    n1.addLyric("You", lyricNumber=1)
    n1.addLyric("I", lyricNumber=2)
    m1.append(n1)
    n2 = m21_note.Note("D5", quarterLength=1.0)
    n2.addLyric("say", lyricNumber=1)
    n2.addLyric("say", lyricNumber=2)
    m1.append(n2)
    # m2: lone-v2 measure (the 1st-ending bug pattern)
    m2 = stream.Measure(number=2)
    n3 = m21_note.Note("E5", quarterLength=1.0)
    n3.addLyric("might", lyricNumber=2)
    m2.append(n3)
    n4 = m21_note.Note("F5", quarterLength=1.0)
    n4.addLyric("break", lyricNumber=2)
    m2.append(n4)
    part.append(m1)
    part.append(m2)
    sc.append(part)
    return sc


def test_lone_v2_measure_gets_swapped_to_v1() -> None:
    sc = _score_with_lone_v2_measure()
    swapped = _swap_lone_v2_measures_to_v1(sc)
    assert swapped == 2, f"expected 2 swaps in m2, got {swapped}"

    # m2's notes should now carry v1 lyrics, not v2.
    measures = list(sc.parts[0].getElementsByClass("Measure"))
    m2 = measures[1]
    for n in m2.recurse().notes:
        for lyr in n.lyrics:
            assert lyr.number == 1, (
                f"m2 note '{n.nameWithOctave}' lyric '{lyr.text}' should be "
                f"verse 1 after swap; got verse {lyr.number}"
            )


def test_paired_verse_measure_untouched() -> None:
    """A measure where both v1 and v2 have lyrics (normal refrain) is
    NOT modified by the swap pass."""
    sc = _score_with_lone_v2_measure()
    _swap_lone_v2_measures_to_v1(sc)

    measures = list(sc.parts[0].getElementsByClass("Measure"))
    m1 = measures[0]
    # m1 still has v1 + v2 lyrics, unchanged.
    v1_count = 0
    v2_count = 0
    for n in m1.recurse().notes:
        for lyr in n.lyrics:
            if lyr.number == 1:
                v1_count += 1
            elif lyr.number == 2:
                v2_count += 1
    assert v1_count == 2, f"m1 should still have 2 v1 lyrics; got {v1_count}"
    assert v2_count == 2, f"m1 should still have 2 v2 lyrics; got {v2_count}"


def test_no_lyrics_measure_does_nothing() -> None:
    """A measure with no lyrics at all is a no-op."""
    sc = stream.Score()
    part = stream.Part()
    m = stream.Measure(number=1)
    m.append(m21_note.Note("C5", quarterLength=4.0))  # no lyric
    part.append(m)
    sc.append(part)
    assert _swap_lone_v2_measures_to_v1(sc) == 0


def test_v1_only_measure_untouched() -> None:
    """A measure with only v1 lyrics is also a no-op (v1 isn't empty)."""
    sc = stream.Score()
    part = stream.Part()
    m = stream.Measure(number=1)
    n = m21_note.Note("C5", quarterLength=1.0)
    n.addLyric("hello", lyricNumber=1)
    m.append(n)
    part.append(m)
    sc.append(part)
    assert _swap_lone_v2_measures_to_v1(sc) == 0
