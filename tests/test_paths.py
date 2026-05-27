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


def test_finds_snake_case(tmp_path: Path) -> None:
    (tmp_path / "music_xml").mkdir()
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


def test_candidate_sets_are_snake_case_only() -> None:
    """All four candidate sets carry the snake-case form only. Earlier
    Title Case duplicates were dropped after the legacy directories
    were removed from disk."""
    assert SONGS_DIR_CANDIDATES == ("individual_songs",)
    assert MXL_DIR_CANDIDATES == ("music_xml",)
    assert LYRICS_DIR_CANDIDATES == ("lyrics",)
    assert LEADSHEETS_DIR_CANDIDATES == ("lead_sheets",)
