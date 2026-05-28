"""Tests for the cross-engine pitch alignment plumbing (#54 PR-A).

Covers the building blocks only: stream construction, pitch cost,
NW alignment, and candidate extraction. The actual insertion +
lyric-count gating live in PR-B.
"""
from __future__ import annotations

from omr_leadsheet.pipeline.cross_engine_recovery import (
    AudiNote, OemerNote, RecoveryCandidate,
    _pitch_cost, align_pitch_streams, find_recovery_candidates,
)


def _a(mn: int, step: str, octv: int = 4, alter: int = 0, dur: float = 1.0) -> AudiNote:
    return AudiNote(measure_number=mn, step=step, alter=alter, octave=octv, duration=dur)


def _o(idx: int, step: str, octv: int = 4, alter: int = 0, dur: float = 1.0) -> OemerNote:
    return OemerNote(index=idx, step=step, alter=alter, octave=octv, duration=dur)


def test_pitch_cost_exact_match_is_zero() -> None:
    assert _pitch_cost(_a(1, "A"), _o(0, "A")) == 0.0
    assert _pitch_cost(_a(1, "F", alter=1), _o(0, "F", alter=1)) == 0.0


def test_pitch_cost_octave_off_by_one_is_partial() -> None:
    """Engines often disagree on octave; allow a small penalty."""
    assert _pitch_cost(_a(1, "A", octv=4), _o(0, "A", octv=5)) == 0.3
    assert _pitch_cost(_a(1, "G", octv=3), _o(0, "G", octv=4)) == 0.3


def test_pitch_cost_different_pitch_is_full() -> None:
    assert _pitch_cost(_a(1, "A"), _o(0, "B")) == 1.0
    # Two octaves apart -> full mismatch (only ±1 is tolerated)
    assert _pitch_cost(_a(1, "A", octv=4), _o(0, "A", octv=6)) == 1.0


def test_alignment_matches_identical_streams() -> None:
    """Audi and oemer with same pitches -> every pair matched, no gaps."""
    audi = [_a(1, "A"), _a(1, "G"), _a(1, "F"), _a(1, "E")]
    oemer = [_o(i, s) for i, s in enumerate(["A", "G", "F", "E"])]
    al = align_pitch_streams(audi, oemer)
    assert all(ai is not None and oj is not None for ai, oj in al)
    assert len(al) == 4


def test_alignment_finds_oemer_extra_note() -> None:
    """Audi has 4 notes A-G-F-E; oemer has 5 with an extra D between E and a continuation.
    The alignment should surface the extra as an (audi=None, oemer=4) pair."""
    audi = [_a(1, "A"), _a(1, "G"), _a(1, "F"), _a(1, "E")]
    oemer = [
        _o(0, "A"), _o(1, "G"), _o(2, "F"), _o(3, "E"), _o(4, "D"),
    ]
    al = align_pitch_streams(audi, oemer)
    # The trailing D should appear as (None, 4)
    assert al[-1] == (None, 4)


def test_find_recovery_candidates_brackets_with_measure() -> None:
    """For each (None, j) gap, the previous/next audi measure
    numbers are recorded so PR-B can route the insertion."""
    audi = [_a(5, "A"), _a(5, "G"), _a(5, "F"), _a(5, "E"), _a(6, "C")]
    oemer = [
        _o(0, "A"), _o(1, "G"), _o(2, "F"), _o(3, "E"),
        _o(4, "D"),  # the "missing" note
        _o(5, "C"),
    ]
    candidates = find_recovery_candidates(audi, oemer)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.oemer.step == "D"
    assert c.prev_audi_measure == 5  # bracketed by m5 (E)
    assert c.next_audi_measure == 6  # ... and m6 (C)


def test_no_candidates_when_streams_match_exactly() -> None:
    audi = [_a(1, "A"), _a(1, "G")]
    oemer = [_o(0, "A"), _o(1, "G")]
    assert find_recovery_candidates(audi, oemer) == []


def test_audi_extras_are_not_candidates() -> None:
    """Notes Audiveris has but oemer missed are NOT recovery candidates
    (we only ADD missing notes, never remove existing ones)."""
    audi = [_a(1, "A"), _a(1, "G"), _a(1, "F"), _a(1, "E"), _a(1, "D")]
    oemer = [_o(0, "A"), _o(1, "G"), _o(2, "F"), _o(3, "E")]
    candidates = find_recovery_candidates(audi, oemer)
    assert candidates == []


def test_candidate_brackets_at_stream_edges() -> None:
    """When the gap is at the very start (no prev audi) or end
    (no next audi), the corresponding measure is None."""
    # Oemer has an extra D at the very start before audi's A
    audi = [_a(7, "A"), _a(7, "G")]
    oemer = [_o(0, "D"), _o(1, "A"), _o(2, "G")]
    candidates = find_recovery_candidates(audi, oemer)
    assert len(candidates) == 1
    assert candidates[0].oemer.step == "D"
    assert candidates[0].prev_audi_measure is None
    assert candidates[0].next_audi_measure == 7
