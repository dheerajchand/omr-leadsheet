"""Songs sub-directory discovery for batch processing.

Pre-fix, ``batch`` hardcoded ``"Individual Songs"`` (Title Case + space)
while the actual project convention is ``individual_songs`` (snake_case).
The directory mismatch caused ``omr-lead batch`` to silently report
``0 processed`` with no error, masking a totally-broken command. The
fix auto-detects from a candidate set and raises ``FileNotFoundError``
when none exist.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from omr_leadsheet.pipeline.batch import find_songs_dir


def test_finds_snake_case_dir(tmp_path: Path) -> None:
    """The project's actual convention: ``individual_songs``."""
    (tmp_path / "individual_songs").mkdir()
    assert find_songs_dir(tmp_path) == tmp_path / "individual_songs"


def test_finds_title_case_with_space(tmp_path: Path) -> None:
    """Historic layout some users may have: ``Individual Songs``."""
    (tmp_path / "Individual Songs").mkdir()
    assert find_songs_dir(tmp_path) == tmp_path / "Individual Songs"


def test_snake_case_wins_when_multiple_present(tmp_path: Path) -> None:
    """When more than one candidate exists, snake_case takes priority
    (it's the project convention; the other forms are tolerated for
    compatibility but shouldn't override)."""
    (tmp_path / "individual_songs").mkdir()
    (tmp_path / "Individual Songs").mkdir()
    assert find_songs_dir(tmp_path) == tmp_path / "individual_songs"


def test_raises_when_none_exist(tmp_path: Path) -> None:
    """Pre-fix: silent 0 processed. Post-fix: a clear FileNotFoundError
    naming all candidates tried so the user can rename their dir."""
    with pytest.raises(FileNotFoundError) as exc_info:
        find_songs_dir(tmp_path)
    msg = str(exc_info.value)
    assert "individual_songs" in msg
    assert "Individual Songs" in msg
