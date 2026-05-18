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

from omr_leadsheet.pipeline.spell_check import apply_alignment, is_real_word


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


# --- is_real_word single-char trust (issue #11) ---------------------------

def test_legitimate_single_char_words_are_real() -> None:
    """`a`, `i`, `o` are real single-char English words; trust them."""
    assert is_real_word("a")
    assert is_real_word("I")  # casing irrelevant
    assert is_real_word("o")
    # With trailing punctuation:
    assert is_real_word("I,")
    assert is_real_word("a.")


def test_other_single_chars_not_trusted() -> None:
    """Pre-fix, `is_real_word` returned True for every len<3 token,
    which let OCR-truncated single-letter syllables (the→t, etc.) pass
    NW-alignment without being replaced by the truth-aligned partner.
    Now: single chars outside the SINGLE_CHAR_WORDS whitelist are NOT
    treated as real, so NW replacement can fire.
    """
    assert not is_real_word("t"), "the OCR-truncation case from LCWTO m33"
    assert not is_real_word("x")
    assert not is_real_word("b")
    assert not is_real_word("z")
    # Empty token must also be rejected (previously short-circuited True)
    assert not is_real_word("")


def test_two_char_tokens_still_trusted() -> None:
    """Two-char tokens are mostly legitimate (to, of, go, on, in, my, we,
    he, by, do, ...). Trust them broadly — the false-positive rate is
    much lower than at 1 char.
    """
    for tok in ("to", "of", "go", "on", "in", "my", "we", "he", "is", "no"):
        assert is_real_word(tok), f"{tok!r} should be trusted"


def test_dictionary_path_still_works() -> None:
    """3+ char tokens still pass through the dictionary check.

    (Note: `/usr/share/dict/words` is the 1913 web2 dict which lacks
    many modern plurals like "things"; we test with words that are
    in both the modern English set and web2.)
    """
    assert is_real_word("hello")
    assert is_real_word("thing")
    assert is_real_word("call")
    assert not is_real_word("xkqz"), "non-word should be rejected"


def test_multi_token_same_bracket_preserves_truth_stream_order() -> None:
    """Regression for #29 v2 word-order. When multiple truth tokens fall
    in the same audi-side bracket, pass 2 used to pick the middle of
    naked-list per iteration, which scrambled the visual order on the
    staff (LCWTO m33 v2: tokens E1..E5 landed on notes 137,138,136,139,135
    -- read top-to-bottom as E,C,A,B,D, not E1..E5).

    With leftmost-first, multi-token same-bracket inserts preserve the
    alignment-order (which corresponds to truth-stream order). 3 truth
    tokens in a 4-naked-note bracket land on notes 0,1,2 in order.
    """
    # 4 naked notes with no audi lyrics, bracketed by 2 audi-aligned
    # notes at the start and end. verse_range will be (0, 5) because of
    # the leading audi.
    all_notes = (
        [_make_note("start")]
        + [_make_note(None) for _ in range(4)]
        + [_make_note("end")]
    )
    audi_pairs = [
        (0, all_notes[0], all_notes[0].lyrics[0]),
        (5, all_notes[5], all_notes[5].lyrics[0]),
    ]
    # Truth has 3 extra words between "start" and "end" that all fall
    # in the single audi-side gap between notes 0 and 5.
    truth = ["start", "alpha", "beta", "gamma", "end"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 3
    # Read the naked notes in order; they must appear in truth-stream
    # order, not in some scrambled middle-of-naked rotation.
    inserted_texts = [
        all_notes[i].lyrics[0].text
        for i in range(1, 5)
        if all_notes[i].lyrics
    ]
    assert inserted_texts == ["alpha", "beta", "gamma"], (
        f"truth-stream order broken: {inserted_texts}"
    )


def test_wide_bracket_rejected_to_avoid_inventing_lyrics() -> None:
    """Regression for #29 v2 over-insertion. When the audi-side gap
    between adjacent audi-aligned tokens spans more notes than
    BRACKET_NOTE_CAP, pass 2 refuses to insert -- the gap most likely
    means the verse simply doesn't sing through here (LCWTO m33 v2 had
    a 6-note bracket where v2 has no sung content, but pass 2 filled
    it with 5 chorus-phrase tokens that belong elsewhere in the song).

    Cap is 4 notes; this test uses a 6-note bracket and asserts pass 2
    inserts nothing.
    """
    # 6 naked notes between two audi-aligned notes (bracket size = 6).
    all_notes = (
        [_make_note("start")]
        + [_make_note(None) for _ in range(6)]
        + [_make_note("end")]
    )
    audi_pairs = [
        (0, all_notes[0], all_notes[0].lyrics[0]),
        (7, all_notes[7], all_notes[7].lyrics[0]),
    ]
    # Words are multi-char so they clear is_real_word's single-char gate.
    truth = ["start", "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "end"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    # Bracket is too wide -- pass 2 must not insert anything in it.
    assert stats["inserted"] == 0, stats
    for i in range(1, 7):
        assert not all_notes[i].lyrics, (
            f"note {i} should remain naked in wide-bracket case"
        )


def test_narrow_bracket_still_filled() -> None:
    """Boundary check: a 4-note bracket (= cap) DOES get filled.
    Pins the lower bound of the cap so a future tightening to 3
    notes fails this test loudly."""
    all_notes = (
        [_make_note("start")]
        + [_make_note(None) for _ in range(4)]
        + [_make_note("end")]
    )
    audi_pairs = [
        (0, all_notes[0], all_notes[0].lyrics[0]),
        (5, all_notes[5], all_notes[5].lyrics[0]),
    ]
    # Multi-char tokens so is_real_word accepts each.
    truth = ["start", "alpha", "beta", "gamma", "delta", "end"]

    stats = apply_alignment(audi_pairs, truth, all_notes, verse_num=1)

    assert stats["inserted"] == 4
