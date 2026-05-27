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
    """The project's only convention: ``individual_songs``."""
    (tmp_path / "individual_songs").mkdir()
    assert find_songs_dir(tmp_path) == tmp_path / "individual_songs"


def test_raises_when_none_exist(tmp_path: Path) -> None:
    """Pre-fix: silent 0 processed. Post-fix: a clear FileNotFoundError
    naming the candidate tried so the user can rename their dir."""
    with pytest.raises(FileNotFoundError) as exc_info:
        find_songs_dir(tmp_path)
    msg = str(exc_info.value)
    assert "individual_songs" in msg
