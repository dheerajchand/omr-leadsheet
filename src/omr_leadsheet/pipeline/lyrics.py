"""Tesseract-based lyric extraction.

A thin Python wrapper around the legacy ``scripts/extract_lyrics.sh``
shell pipeline (pdftoppm → tesseract → English-dictionary filter).
The shell helper stays because the pipeline composes well in bash
and chaining stdlib subprocess calls would not be clearer.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = ["extract"]


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SHELL_HELPER = _REPO_ROOT / "scripts" / "extract_lyrics.sh"


def extract(pdf: Path, out_txt: Path) -> None:
    """Extract clean lyric lines from ``pdf`` into ``out_txt``.

    Parameters
    ----------
    pdf : Path
        Source piano-vocal PDF.
    out_txt : Path
        Destination text file; overwritten if it exists.

    Raises
    ------
    FileNotFoundError
        If the shell helper script or input PDF is missing.
    subprocess.CalledProcessError
        If the underlying pdftoppm / tesseract chain fails.
    """
    if not _SHELL_HELPER.is_file():
        raise FileNotFoundError(f"shell helper missing: {_SHELL_HELPER}")
    if not pdf.is_file():
        raise FileNotFoundError(f"input pdf missing: {pdf}")
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["bash", str(_SHELL_HELPER), str(pdf), str(out_txt)],
        check=True,
    )
