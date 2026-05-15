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


def test_pickup_tolerance_inserts_at_distance_two_leading() -> None:
    """Boundary: a truth token aligned at distance 2 from the first
    audi-aligned note (two naked leading pickups) must still get
    inserted. Pins the exact PICKUP_TOLERANCE == 2 contract — if the
    constant were changed to 1, this would fail.
    """
    # Two naked leading pickups, then 3 audi-aligned notes.
    all_notes = [_make_note(None), _make_note(None)] + [
        _make_note(t) for t in ("call", "the", "whole")
    ]
    audi_pairs = [
        (i, all_notes[i], all_notes[i].lyrics[0]) for i in range(2, 5)
    ]
    truth = ["If", "call", "the", "whole"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 1
    # The insertion lands on one of the two naked pickup notes (the impl
    # picks the median naked slot; either index 0 or 1 is acceptable).
    inserted_at = [i for i in (0, 1) if all_notes[i].lyrics]
    assert len(inserted_at) == 1
    assert all_notes[inserted_at[0]].lyrics[0].text == "If"


def test_pickup_tolerance_inserts_at_distance_two_trailing() -> None:
    """Mirror of the leading distance-2 boundary test."""
    all_notes = [
        _make_note(t) for t in ("we", "call", "the")
    ] + [_make_note(None), _make_note(None)]
    audi_pairs = [
        (i, all_notes[i], all_notes[i].lyrics[0]) for i in range(0, 3)
    ]
    truth = ["we", "call", "the", "off"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 1
    inserted_at = [i for i in (3, 4) if all_notes[i].lyrics]
    assert len(inserted_at) == 1
    assert all_notes[inserted_at[0]].lyrics[0].text == "off"


def test_pickup_tolerance_skips_out_of_range_notes() -> None:
    """Out-of-tolerance: with three naked leading notes (at distances 1,
    2, 3 from the first audi-aligned note), the truth gap "If" can
    insert into the notes at distance 1 or 2 — but the note at distance
    3 is beyond PICKUP_TOLERANCE and stays naked.

    Pins the upper bound: if someone changes ``PICKUP_TOLERANCE`` to 3,
    note 0 would become a candidate and this test would fail.
    """
    # 3 naked leading + 3 audi-aligned. verse_range[0] = 3.
    # Distances from verse_range[0]: note 0 = 3, note 1 = 2, note 2 = 1.
    all_notes = [_make_note(None), _make_note(None), _make_note(None)] + [
        _make_note(t) for t in ("call", "the", "whole")
    ]
    audi_pairs = [
        (i, all_notes[i], all_notes[i].lyrics[0]) for i in range(3, 6)
    ]
    truth = ["If", "call", "the", "whole"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    # "If" lands on note 1 or note 2 (both within tolerance).
    assert stats["inserted"] == 1
    # The distance-3 note (index 0) MUST remain naked — that's the
    # boundary this test pins.
    assert not all_notes[0].lyrics, (
        "note at distance 3 from verse_range[0] must not receive a lyric; "
        "PICKUP_TOLERANCE=2 excludes it"
    )


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
