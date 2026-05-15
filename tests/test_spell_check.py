"""apply_alignment pass-2 (truth-gap insertion) behavior.

Regression coverage for the pickup-lyric attachment fix: when Audiveris
fails to attach a syllable to a pickup/anacrusis note at the start of a
verse, the truth-OCR pass must still be allowed to insert that syllable
on the naked pickup note. Before the fix, the verse-range clamp excluded
any naked note whose index was below ``min(audi_aligned_note_indices)``,
which always excluded leading pickups.
"""
from __future__ import annotations

from music21 import note as m21_note

from omr_leadsheet.pipeline.spell_check import apply_alignment


def _make_note(lyric_text: str | None = None, verse: int = 1) -> m21_note.Note:
    n = m21_note.Note("C4")
    n.quarterLength = 0.5
    if lyric_text is not None:
        n.addLyric(lyric_text)
        n.lyrics[0].number = verse
    return n


def test_pickup_syllable_attaches_to_naked_leading_note() -> None:
    """Reproduces the "If" pickup case from #7.

    Scenario: bar contains a pickup eighth at index 0 (no Audiveris-attached
    lyric) followed by four notes that DO have audi-attached lyrics
    ``["we", "call", "the", "whole"]``. The tesseract pass produces the
    full phrase ``["If", "we", "call", "the", "whole"]``. Needleman-Wunsch
    aligns "If" to a truth-gap (audi=None). pass-2 must insert "If" on the
    naked pickup note at index 0.
    """
    # Build all 5 notes; note 0 is the pickup with no lyric, 1..4 carry audi-lyrics
    all_notes = [_make_note(None)] + [
        _make_note(t) for t in ("we", "call", "the", "whole")
    ]
    audi_pairs = [
        (i, all_notes[i], all_notes[i].lyrics[0])
        for i in range(1, 5)
    ]
    truth = ["If", "we", "call", "the", "whole"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 1, (
        f"expected 1 inserted truth-gap syllable, got {stats!r}"
    )
    assert len(all_notes[0].lyrics) == 1, (
        "pickup note must receive the inserted lyric"
    )
    assert all_notes[0].lyrics[0].text == "If"
    assert all_notes[0].lyrics[0].number == 1


def test_trailing_pickup_syllable_attaches_to_naked_trailing_note() -> None:
    """Mirror of the leading-pickup case for the right-side clamp.

    The symmetric ``PICKUP_TOLERANCE`` extension should let a trailing
    truth-gap land on a naked note that sits *after* the last
    audi-aligned lyric, not just before the first. Catches a one-sided
    regression where only the left edge was loosened.
    """
    all_notes = [_make_note(t) for t in ("we", "call", "the", "whole")] + [
        _make_note(None)
    ]
    audi_pairs = [
        (i, all_notes[i], all_notes[i].lyrics[0])
        for i in range(0, 4)
    ]
    truth = ["we", "call", "the", "whole", "off"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 1, (
        f"expected 1 inserted trailing truth-gap syllable, got {stats!r}"
    )
    assert len(all_notes[4].lyrics) == 1, (
        "trailing naked note must receive the inserted lyric"
    )
    assert all_notes[4].lyrics[0].text == "off"
    assert all_notes[4].lyrics[0].number == 1


def test_no_insertion_when_truth_matches_audi() -> None:
    """Sanity: when truth tokens already line up 1:1 with audi tokens,
    pass-2 inserts nothing — neither the pickup tolerance nor anything else
    should hallucinate syllables on naked notes.
    """
    all_notes = [_make_note(t) for t in ("we", "call", "the")]
    audi_pairs = [(i, all_notes[i], all_notes[i].lyrics[0]) for i in range(3)]
    truth = ["we", "call", "the"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 0
