"""Runtime configuration for the pipeline.

Replaces the legacy `scripts/env.sh` shell preamble. Discovery rules are
preserved verbatim so existing users hit the same defaults.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


__all__ = ["Config", "ConfigError"]


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or invalid."""


DEFAULT_STYLE_FILE = Path.home() / "Documents" / "MuseScore4" / "Styles" / "MyStyle.mss"
DEFAULT_AUDIVERIS = Path("/Applications/Audiveris.app/Contents/MacOS/Audiveris")
DEFAULT_MSCORE = Path("/Applications/MuseScore 4.app/Contents/MacOS/mscore")


def _detect_python() -> Path:
    """Pick the interpreter the legacy env.sh would have picked.

    Order: explicit VENV_PY > pyenv-active interpreter > current sys.executable.
    """
    explicit = os.environ.get("VENV_PY")
    if explicit:
        return Path(explicit)
    pyenv = shutil.which("pyenv")
    if pyenv is not None:
        try:
            import subprocess
            result = subprocess.run(
                [pyenv, "which", "python"],
                capture_output=True, text=True, check=False,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    return Path(sys.executable)


def _detect_oemer(python_bin: Path) -> Path | None:
    """Find the oemer CLI in the same directory as the interpreter, then PATH."""
    explicit = os.environ.get("OEMER_BIN")
    if explicit:
        return Path(explicit)
    sibling = python_bin.parent / "oemer"
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling
    found = shutil.which("oemer")
    return Path(found) if found else None


@dataclass(frozen=True, slots=True)
class Config:
    """All pipeline configuration in one place.

    Construct with `Config.from_env()` to honor the legacy environment-variable
    interface (BOOK_DIR, STYLE_FILE, AUDIVERIS_BIN, etc.). Construct directly
    in tests.
    """

    book_dir: Path
    style_file: Path = field(default=DEFAULT_STYLE_FILE)
    audiveris_bin: Path = field(default=DEFAULT_AUDIVERIS)
    mscore_bin: Path = field(default=DEFAULT_MSCORE)
    python_bin: Path = field(default_factory=lambda: Path(sys.executable))
    oemer_bin: Path | None = None
    chord_vlm_enabled: bool = False
    chord_vlm_backend: str = "ollama"
    chord_vlm_model: str = "qwen2.5vl:7b"
    classifier_path: Path | None = None
    chord_sweep_enabled: bool = False

    @classmethod
    def from_env(cls, book_dir: Path | str | None = None) -> "Config":
        """Build a Config from environment variables.

        `book_dir` overrides the BOOK_DIR env var. Both must produce a path.
        """
        book_dir_str = str(book_dir) if book_dir is not None else os.environ.get("BOOK_DIR")
        if not book_dir_str:
            raise ConfigError(
                "BOOK_DIR not set. Pass --book-dir on the CLI or "
                "`export BOOK_DIR=/path/to/songbook` before running."
            )
        book_path = Path(book_dir_str).expanduser()
        python_bin = _detect_python()
        classifier_env = os.environ.get("CHORD_CLASSIFIER_PATH")
        return cls(
            book_dir=book_path,
            style_file=Path(os.environ.get("STYLE_FILE", str(DEFAULT_STYLE_FILE))).expanduser(),
            audiveris_bin=Path(os.environ.get("AUDIVERIS_BIN", str(DEFAULT_AUDIVERIS))),
            mscore_bin=Path(os.environ.get("MSCORE_BIN", str(DEFAULT_MSCORE))),
            python_bin=python_bin,
            oemer_bin=_detect_oemer(python_bin),
            chord_vlm_enabled=os.environ.get("CHORD_VLM") == "1",
            chord_vlm_backend=os.environ.get("CHORD_VLM_BACKEND", "ollama"),
            chord_vlm_model=os.environ.get("CHORD_VLM_MODEL", "qwen2.5vl:7b"),
            classifier_path=Path(classifier_env).expanduser() if classifier_env else None,
            chord_sweep_enabled=os.environ.get("CHORD_SWEEP_ENABLE") == "1",
        )

    def to_env(self) -> dict[str, str]:
        """Export as env-var dict for subprocess calls that still read env."""
        env = {
            "BOOK_DIR": str(self.book_dir),
            "STYLE_FILE": str(self.style_file),
            "AUDIVERIS_BIN": str(self.audiveris_bin),
            "MSCORE_BIN": str(self.mscore_bin),
            "VENV_PY": str(self.python_bin),
            "CHORD_VLM_BACKEND": self.chord_vlm_backend,
            "CHORD_VLM_MODEL": self.chord_vlm_model,
        }
        if self.oemer_bin is not None:
            env["OEMER_BIN"] = str(self.oemer_bin)
        if self.classifier_path is not None:
            env["CHORD_CLASSIFIER_PATH"] = str(self.classifier_path)
        if self.chord_vlm_enabled:
            env["CHORD_VLM"] = "1"
        if self.chord_sweep_enabled:
            env["CHORD_SWEEP_ENABLE"] = "1"
        return env
