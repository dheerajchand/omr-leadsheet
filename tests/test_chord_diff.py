"""chord_ops.diff normalization and specificity rules."""
from __future__ import annotations

import pytest

from omr_leadsheet.chord_ops.diff import OMRChord, diff, normalize_chord


def _chord(value: str, measure: int) -> OMRChord:
    return OMRChord(
        sheet=1, staff=1, value=value,
        x=0.0, y=0.0,
        measure_local=measure, measure_global=measure, measure_frac=0.0,
    )


def test_normalize_strips_whitespace_and_lowercases() -> None:
    assert normalize_chord("G 7") == normalize_chord("G7") == "g7"
    assert normalize_chord(" Bbm7 ") == "bbm7"


def test_diff_does_not_suppress_substring_match_without_offset_context() -> None:
    """#12 regression. The earlier substring rule treated 'C' as already
    covered by ANY longer chord in the same measure containing 'c'
    (e.g. 'Cmaj7'), discarding short diatonic chords on busy bars before
    they reached insert_missing. The new rule is exact-match-only in
    diff(); offset-bounded dedup (Am when Am7 is within half a beat at
    the same offset) belongs in insert_missing where the offsets are
    available."""
    target = _chord("C", 4)
    # In a real busy bar this 'C' might sit at beat 4 while a separate
    # 'Cmaj7' sits at beat 1; both belong on the chord row. diff() must
    # not pre-filter the 'C'.
    missing = diff([target], mxl=[(4, "Cmaj7")])
    assert missing == [target], "single-letter diatonic chord must survive diff()"


def test_diff_does_not_suppress_am_when_am7_present_at_unknown_offset() -> None:
    """The old rule killed an Am when Am7 was anywhere in the same
    measure; that's the same #12 bias. insert_missing handles the real
    'Am7 sits at the same beat as Am' case via its offset-bounded
    second-pass dedup; diff() must let the Am through."""
    target = _chord("Am", 4)
    missing = diff([target], mxl=[(4, "Am7")])
    assert missing == [target], "Am must survive diff(); insert_missing decides if it duplicates"


def test_diff_does_not_suppress_more_specific_target() -> None:
    target = _chord("G9/7", 4)
    missing = diff([target], mxl=[(4, "G7")])
    assert missing == [target], "G9/7 is strictly more specific than G7 and must pass"


def test_diff_skips_exact_duplicate() -> None:
    target = _chord("Em", 7)
    assert diff([target], mxl=[(7, "Em")]) == []


def test_diff_no_overlap() -> None:
    target = _chord("A7", 3)
    assert diff([target], mxl=[(3, "Bm7")]) == [target]
