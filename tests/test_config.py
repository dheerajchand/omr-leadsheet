"""Config dataclass and from_env behaviour."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from omr_leadsheet.config import Config, ConfigError


def test_from_env_requires_book_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOK_DIR", raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()


def test_from_env_reads_book_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_DIR", str(tmp_path))
    cfg = Config.from_env()
    assert cfg.book_dir == tmp_path


def test_chord_vlm_toggle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOK_DIR", str(tmp_path))
    monkeypatch.setenv("CHORD_VLM", "1")
    monkeypatch.setenv("CHORD_VLM_BACKEND", "anthropic")
    cfg = Config.from_env()
    assert cfg.chord_vlm_enabled is True
    assert cfg.chord_vlm_backend == "anthropic"


def test_to_env_roundtrip(tmp_path: Path) -> None:
    cfg = Config(
        book_dir=tmp_path,
        style_file=tmp_path / "style.mss",
        audiveris_bin=Path("/opt/audiveris"),
        mscore_bin=Path("/opt/mscore"),
        python_bin=Path("/opt/python"),
        chord_vlm_enabled=True,
        classifier_path=tmp_path / "classifier.pt",
    )
    env = cfg.to_env()
    assert env["BOOK_DIR"] == str(tmp_path)
    assert env["CHORD_VLM"] == "1"
    assert env["CHORD_CLASSIFIER_PATH"] == str(tmp_path / "classifier.pt")
    assert "OEMER_BIN" not in env


def test_frozen() -> None:
    cfg = Config(book_dir=Path("/x"))
    with pytest.raises(Exception):
        cfg.book_dir = Path("/y")  # type: ignore[misc]
