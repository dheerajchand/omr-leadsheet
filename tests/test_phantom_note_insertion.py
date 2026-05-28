"""Regression: when spell_check has a truth-gap that pass 2 can't
fill (no naked note in bracket) but the bracket has a Rest,
replace the rest with a phantom note carrying the lyric (#73 / #54).

Symptom on #13 LCWTO m16: Audiveris recovered 4 of 5 notes for the
phrase "Some-thing must be done.—". The 5th syllable "done" is in
the tesseract lyric.txt, but pass 2 can't insert it because m16's
4 notes all carry lyrics and the bracket continues into m17 which
is a rest. Pass 3 replaces that rest with a phantom note + lyric.
"""
from __future__ import annotations

from music21 import stream, note as m21note

from omr_leadsheet.pipeline.spell_check import (
    apply_alignment, audiveris_tokens,
)


def _build_score_with_4notes_and_a_rest() -> stream.Score:
    """4 audi notes (Some/thing/must/be) in m1, then a half-measure
    rest in m2. The rest is the phantom-insertion target for 'done'."""
    sc = stream.Score()
    p = stream.Part()
    # m1: A G F E quarter notes with lyrics
    m1 = stream.Measure(number=1)
    for step, syll in zip(["A", "G", "F", "E"], ["Some", "thing", "must", "be"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m1.append(n)
    # m2: a single half-note rest
    m2 = stream.Measure(number=2)
    r = m21note.Rest(quarterLength=2.0)
    m2.append(r)
    p.append(m1)
    p.append(m2)
    sc.append(p)
    return sc


def test_phantom_note_inserted_when_truth_gap_has_rest_in_bracket() -> None:
    sc = _build_score_with_4notes_and_a_rest()
    _, all_notes, by_verse = audiveris_tokens(sc)
    # Truth has the extra "done" syllable
    truth = ["Some", "thing", "must", "be", "done"]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    assert stats.get("phantom_inserted") == 1, (
        f"expected one phantom-inserted note; got stats={stats}"
    )
    # Scan m2: should now contain a Note with lyric "done" instead of a Rest.
    measures = list(sc.parts[0].getElementsByClass("Measure"))
    m2 = measures[1]
    notes_in_m2 = list(m2.recurse().notes)
    assert len(notes_in_m2) == 1, (
        f"m2 should have one phantom note; got {[n for n in m2.recurse()]}"
    )
    phantom = notes_in_m2[0]
    assert any(
        (lyr.number or 1) == 1 and lyr.text == "done"
        for lyr in phantom.lyrics
    ), f"phantom note should carry the 'done' lyric; got lyrics={phantom.lyrics}"


def test_phantom_only_when_truth_word_is_real() -> None:
    """OCR garbage like 'xqz' should not trigger a phantom insertion
    (is_real_word gate)."""
    sc = _build_score_with_4notes_and_a_rest()
    _, all_notes, by_verse = audiveris_tokens(sc)
    # Truth has OCR garbage instead of a real syllable at the end
    truth = ["Some", "thing", "must", "be", "xqz"]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    assert stats.get("phantom_inserted", 0) == 0, (
        "OCR garbage truth-gap should NOT trigger phantom insertion"
    )


def test_no_phantom_when_no_rest_in_bracket() -> None:
    """When the bracket has no Rest, pass 3 can't act -- the truth
    syllable is dropped (current behaviour preserved)."""
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    for step, syll in zip(["A", "G", "F", "E"], ["Some", "thing", "must", "be"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m1.append(n)
    p.append(m1)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["Some", "thing", "must", "be", "done"]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    # No rest -> no phantom -> done is dropped
    assert stats.get("phantom_inserted", 0) == 0


def test_phantom_pitch_matches_previous_note() -> None:
    """The phantom pitch is copied from the previous audi-aligned
    note (continuation/held interpretation)."""
    sc = _build_score_with_4notes_and_a_rest()
    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["Some", "thing", "must", "be", "done"]
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    measures = list(sc.parts[0].getElementsByClass("Measure"))
    m2 = measures[1]
    phantom = list(m2.recurse().notes)[0]
    # The previous note was E3 (the "be" syllable).
    assert phantom.pitch.nameWithOctave == "E3", (
        f"phantom pitch should match previous note E3; got {phantom.pitch.nameWithOctave}"
    )


def test_phantom_cap_shared_across_verses() -> None:
    """#75: when the same measure has a truth-gap in BOTH v1 and v2,
    the cap should fire across the shared set so only one phantom
    lands in that measure (not one per verse)."""
    from music21 import stream, note as m21note
    from omr_leadsheet.pipeline.spell_check import (
        apply_alignment, audiveris_tokens,
    )
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    n = m21note.Note("A3", quarterLength=1.0)
    n.addLyric("Some", lyricNumber=1)
    n.addLyric("Some", lyricNumber=2)
    m1.append(n)
    m2 = stream.Measure(number=2)
    m2.append(m21note.Rest(quarterLength=2.0))
    p.append(m1)
    p.append(m2)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth_v1 = ["Some", "done"]
    truth_v2 = ["Some", "done"]
    # Share the cap as the production main() does.
    cap: set = set()
    s1 = apply_alignment(by_verse[1], truth_v1, all_notes, 1, phantom_measures_used=cap)
    s2 = apply_alignment(by_verse[2], truth_v2, all_notes, 2, phantom_measures_used=cap)
    assert s1["phantom_inserted"] + s2["phantom_inserted"] == 1, (
        f"only one phantom should land in m2 across both verses; "
        f"got v1={s1['phantom_inserted']} v2={s2['phantom_inserted']}"
    )


def test_phantom_one_per_measure_cap() -> None:
    """If multiple truth-gaps would target the same measure, only
    one phantom gets inserted there."""
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    n = m21note.Note("A3", quarterLength=1.0)
    n.addLyric("Some", lyricNumber=1)
    m1.append(n)
    # m2: contains two rests; we should only fill one of them even
    # if two truth-gaps could land here.
    m2 = stream.Measure(number=2)
    m2.append(m21note.Rest(quarterLength=1.0))
    m2.append(m21note.Rest(quarterLength=1.0))
    p.append(m1)
    p.append(m2)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["Some", "two", "three"]  # two truth-gaps after "Some"
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    assert stats.get("phantom_inserted", 0) <= 1, (
        f"only one phantom per measure; got {stats.get('phantom_inserted')}"
    )
