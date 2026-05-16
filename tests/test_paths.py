"""Shared sub-directory discovery for pipeline entry points.

Centralised after the same hardcode-mismatch bug hit batch (#18) and
process (#21). The helper standardises priority order (snake_case
project convention first) and error reporting.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from omr_leadsheet.pipeline._paths import (
    LEADSHEETS_DIR_CANDIDATES,
    LYRICS_DIR_CANDIDATES,
    MXL_DIR_CANDIDATES,
    SONGS_DIR_CANDIDATES,
    find_subdir,
)


def test_finds_snake_case_first(tmp_path: Path) -> None:
    (tmp_path / "music_xml").mkdir()
    assert find_subdir(tmp_path, MXL_DIR_CANDIDATES) == tmp_path / "music_xml"


def test_falls_back_to_title_case(tmp_path: Path) -> None:
    (tmp_path / "MusicXML").mkdir()
    assert find_subdir(tmp_path, MXL_DIR_CANDIDATES) == tmp_path / "MusicXML"


def test_snake_wins_over_title_when_both_exist(tmp_path: Path) -> None:
    (tmp_path / "music_xml").mkdir()
    (tmp_path / "MusicXML").mkdir()
    # On macOS case-insensitive FS music_xml/MusicXML resolve differently
    # because the underscore makes them distinct names.
    assert find_subdir(tmp_path, MXL_DIR_CANDIDATES) == tmp_path / "music_xml"


def test_must_exist_true_raises_when_none(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        find_subdir(tmp_path, MXL_DIR_CANDIDATES)
    msg = str(exc_info.value)
    for name in MXL_DIR_CANDIDATES:
        assert name in msg


def test_must_exist_false_returns_snake_case_default(tmp_path: Path) -> None:
    """For output dirs that callers will mkdir, return the first
    candidate even if it doesn't exist yet."""
    result = find_subdir(tmp_path, LEADSHEETS_DIR_CANDIDATES, must_exist=False)
    assert result == tmp_path / "lead_sheets"
    assert not result.exists()  # caller's job to create


def test_candidate_sets_lead_with_snake_case() -> None:
    """All four candidate sets must put the snake-case form first.
    This is the project convention; the helper assumes it for tie-break."""
    assert SONGS_DIR_CANDIDATES[0] == "individual_songs"
    assert MXL_DIR_CANDIDATES[0] == "music_xml"
    assert LYRICS_DIR_CANDIDATES[0] == "lyrics"
    assert LEADSHEETS_DIR_CANDIDATES[0] == "lead_sheets"
