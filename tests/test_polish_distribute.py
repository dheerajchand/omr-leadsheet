"""Regression: when polish() splits an Audi-aligned merged truth token
into multiple words, distribute the extras onto immediately-following
naked notes for the verse (#83).

Symptom on #13 LCWTO m11: tesseract OCR'd "I don't know where I'm" as
"dontknowwhere Im". Pre-fix, polish split "dontknowwhere" into "don't
know where" and stuffed the whole 3-word string into ONE note's lyric,
leaving adjacent naked notes empty. Post-fix the extras spread onto
the next available naked notes.

Also covers pass 2 polishing: a truth-gap token "Im" gets polished to
"I'm" before insertion onto a naked note.
"""
from __future__ import annotations

from music21 import stream, note as m21note

from omr_leadsheet.pipeline.spell_check import (
    apply_alignment, audiveris_tokens,
)


def test_pass1_distributes_multi_word_polish_across_naked_notes() -> None:
    """A merged truth token aligned to one audi note distributes its
    polished pieces onto adjacent naked notes for the same verse."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    # 4 notes: one with a garbled audi lyric (similar enough to truth
    # to trigger pass-1 replacement), three naked
    n0 = m21note.Note("A3", quarterLength=1.0)
    n0.addLyric("dontknowwh", lyricNumber=1)  # partial match -> sim >= 0.3
    m.append(n0)
    for step in ("B3", "C4", "D4"):
        m.append(m21note.Note(step, quarterLength=1.0))
    p.append(m)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["dontknowwhere"]
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    # The merged truth gets polished to "don't know where" and
    # distributed across the four notes.
    lyric_texts = []
    for n in all_notes:
        v1 = [lyr.text for lyr in n.lyrics if (lyr.number or 1) == 1]
        lyric_texts.append(v1[0] if v1 else None)
    assert lyric_texts[0] == "don't", f"first note got {lyric_texts[0]!r}"
    assert lyric_texts[1] == "know", f"second note got {lyric_texts[1]!r}"
    assert lyric_texts[2] == "where", f"third note got {lyric_texts[2]!r}"


def test_pass2_polishes_truth_gap_token() -> None:
    """A truth-gap token "Im" polishes to "I'm" before getting inserted
    onto a naked note."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    # 2 notes - one with audi, one naked
    n0 = m21note.Note("A3", quarterLength=1.0)
    n0.addLyric("hello", lyricNumber=1)
    m.append(n0)
    n1 = m21note.Note("B3", quarterLength=1.0)
    m.append(n1)
    p.append(m)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    # Truth: "hello" aligns to audi; "Im" is a truth-gap that needs
    # to land on the naked B3.
    truth = ["hello", "Im"]
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    v1_on_b3 = [lyr.text for lyr in all_notes[1].lyrics if (lyr.number or 1) == 1]
    assert v1_on_b3 == ["I'm"], (
        f"truth-gap 'Im' should be polished to \"I'm\"; got {v1_on_b3}"
    )


def test_polish_does_not_overwrite_existing_verse_lyrics() -> None:
    """Distribution stops at notes that already carry a same-verse
    lyric -- don't overwrite a real audi-aligned syllable."""
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    # 4 notes: garbled (similar enough to trigger replace), naked, naked, audi
    n0 = m21note.Note("A3", quarterLength=1.0)
    n0.addLyric("dontknowwh", lyricNumber=1)
    m.append(n0)
    for step in ("B3", "C4"):
        m.append(m21note.Note(step, quarterLength=1.0))
    n3 = m21note.Note("D4", quarterLength=1.0)
    n3.addLyric("real", lyricNumber=1)
    m.append(n3)
    p.append(m)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["dontknowwhere", "real"]
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    # The "real" audi lyric on note 3 must NOT be overwritten by the
    # distribution of "where" from "don't know where".
    v1_n3 = [lyr.text for lyr in all_notes[3].lyrics if (lyr.number or 1) == 1]
    assert "real" in v1_n3, f"existing 'real' must survive; got {v1_n3}"
