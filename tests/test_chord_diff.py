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


def test_diff_treats_present_more_specific_as_covering() -> None:
    target = _chord("Am", 4)
    missing = diff([target], mxl=[(4, "Am7")])
    assert missing == [], "Am7 already present should suppress redundant Am"


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
