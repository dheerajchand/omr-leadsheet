"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_book(tmp_path: Path) -> Path:
    """A bare BOOK_DIR layout with the directories the pipeline expects."""
    for sub in ("Individual Songs", "MusicXML", "Lyrics", "LeadSheets"):
        (tmp_path / sub).mkdir()
    return tmp_path
