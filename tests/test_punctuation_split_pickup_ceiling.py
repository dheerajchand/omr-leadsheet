"""Regression: tokenizer drops words glued by punctuation, and pass-2
trailing PICKUP_TOLERANCE invents v2 lyrics in v1-only tail passages (#81).

Symptom A on #13 LCWTO m2: tesseract emitted "pret-ty pass,Our ro-mance"
with no space after the comma. The tokenizer's WORD.match grabbed only
"pass" from "pass,Our"; "Our" was lost.

Symptom B on #13 LCWTO m47: v2's last audi token sat in m45; the
trailing PICKUP_TOLERANCE=2 reached forward into m47 (a v1-only tail
measure) and landed v2 truth tokens "For"/"we" onto those notes.
"""
from __future__ import annotations

from music21 import stream, note as m21note

from omr_leadsheet.pipeline.spell_check import (
    _line_to_tokens, apply_alignment, audiveris_tokens,
)


def test_tokenizer_yields_both_words_when_glued_by_comma() -> None:
    """`pass,Our` -> ["pass", "Our"]."""
    toks = _line_to_tokens("pret-ty pass,Our ro-mance")
    assert "pass" in toks
    assert "Our" in toks


def test_tokenizer_yields_words_when_glued_by_period() -> None:
    """A glued period also yields both words."""
    toks = _line_to_tokens("done.But oh")
    assert "done" in toks
    assert "But" in toks


def test_trailing_pickup_does_not_invent_v2_in_long_v1_tail() -> None:
    """Mirror of #82's leading-side fix: a long v1-only measure at the
    END of the song (after the last v2 audi token) must not absorb v2
    truth tokens via trailing PICKUP_TOLERANCE."""
    sc = stream.Score()
    p = stream.Part()
    # m1-m2: stacked v1+v2. v2 audi spans m1-m2.
    for mnum, ((s1a, s2a), (s1b, s2b)) in enumerate(
        [(("I", "You"), ("go", "stay"))], start=1
    ):
        m = stream.Measure(number=mnum)
        for step, s1, s2 in zip(["G3", "A3"], [s1a, s1b], [s2a, s2b]):
            n = m21note.Note(step, quarterLength=1.0)
            n.addLyric(s1, lyricNumber=1)
            n.addLyric(s2, lyricNumber=2)
            m.append(n)
        p.append(m)
    # m2: v1-only, 4 notes long -- not a plausible pickup measure
    m2 = stream.Measure(number=2)
    for step, syll in zip(["B3", "C4", "D4", "E4"], ["For", "we", "know", "we"]):
        n = m21note.Note(step, quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m2.append(n)
    p.append(m2)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    # v2 truth has the v1-only tail ("For", "we") as well as the
    # v2 first phrase. The trailing tail must NOT land on m2 notes.
    v2_truth = ["You", "stay", "For", "we"]
    apply_alignment(by_verse[2], v2_truth, all_notes, verse_num=2)

    # m2 notes (idx 2..5) must remain v2-clean.
    for n in all_notes[2:]:
        v2_lyrs = [lyr.text for lyr in n.lyrics if (lyr.number or 1) == 2]
        assert v2_lyrs == [], (
            f"v1-only tail must stay v2-clean; got {v2_lyrs}"
        )
