"""Regression: phantom-note insertion (pass 3) was firing on every
truth-gap with a real word, even when the previous audi anchor's
truth match was many positions before the gap.

Symptom on #13 LCWTO m26: prev audi anchor "off!" matched truth["off"]
at some index. The next available truth-gap that pass 3 found was
either "I" or "say" -- both real words appearing much later in the
truth list (in "I like..." and "You say..." phrases). Pass 3
inserted them onto a phantom G3 at the m26 rest, producing a
spurious extra syllable.

Now pass 3 also requires that the truth-gap token come IMMEDIATELY
after the previous audi anchor's truth match (ti - prev_ti <= 1).
The legitimate #73 m17 "done" case has prev_ti=("be") with the gap
at ti=("done") adjacent.
"""
from __future__ import annotations

from music21 import stream, note as m21note

from omr_leadsheet.pipeline.spell_check import (
    apply_alignment, audiveris_tokens,
)


def _build_score_with_rest_after_phrase() -> stream.Score:
    """m1 has 4 notes with v1 lyrics, m2 has a single half-note rest."""
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    for step, syll in zip(["A", "G", "F", "E"], ["Some", "thing", "must", "be"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m1.append(n)
    m2 = stream.Measure(number=2)
    m2.append(m21note.Rest(quarterLength=2.0))
    p.append(m1)
    p.append(m2)
    sc.append(p)
    return sc


def test_phantom_inserts_adjacent_truth_token() -> None:
    """The m17 'done' case: truth ['Some','thing','must','be','done']
    has 'done' immediately after 'be', so pass 3 phantom-inserts."""
    sc = _build_score_with_rest_after_phrase()
    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["Some", "thing", "must", "be", "done"]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    assert stats.get("phantom_inserted") == 1


def test_phantom_refuses_non_adjacent_truth_token() -> None:
    """When the truth-gap token sits many positions after the
    previous audi anchor's truth match (i.e. other truth content
    between them all aligned as gaps too, and the first-adjacent gap
    is already absorbed), pass 3 must refuse to phantom-insert later
    gaps. Setup: audi has 4 notes, truth has 5 syllables that align,
    then a long run of distant truth tokens before "done". After the
    first adjacent gap ("foo") consumes the only rest, "done" at
    ti=10 cannot phantom-insert because (a) no rest left in scan_range
    AND (b) ti is no longer adjacent to any prev paired audi."""
    sc = _build_score_with_rest_after_phrase()
    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["Some", "thing", "must", "be"] + [
        "foo", "bar", "baz", "qux", "zip", "zap", "done",
    ]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    # Exactly one phantom got inserted (the first adjacent gap "foo").
    # The non-adjacent later gaps did NOT.
    assert stats.get("phantom_inserted", 0) == 1
    # And confirm what's there is "foo" (adjacent gap), not "done".
    m2 = list(sc.parts[0].getElementsByClass("Measure"))[1]
    notes_in_m2 = list(m2.recurse().notes)
    assert len(notes_in_m2) == 1
    phantom = notes_in_m2[0]
    texts = [lyr.text for lyr in phantom.lyrics]
    assert "done" not in texts, (
        f"non-adjacent 'done' must not phantom-insert; got {texts}"
    )


def test_phantom_refuses_single_letter_truth_token() -> None:
    """Single-character truth tokens like 'I' or 'a' recur too often
    in a typical song -- the bar for phantom-insertion has to be
    higher than one ambiguous letter."""
    sc = _build_score_with_rest_after_phrase()
    _, all_notes, by_verse = audiveris_tokens(sc)
    # Truth ends with 'I' adjacent to 'be', tempting pass 3 to phantom.
    truth = ["Some", "thing", "must", "be", "I"]
    stats = apply_alignment(by_verse[1], truth, all_notes, verse_num=1)
    assert stats.get("phantom_inserted", 0) == 0, (
        "single-letter truth-gap should not become a phantom"
    )
