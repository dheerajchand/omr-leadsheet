"""Run :func:`process` over every PDF in a songbook.

Replacement for ``scripts/batch_all.sh``. Each song writes its own
``_pipeline.log``; this module additionally appends a one-line
``ok/FAILED`` outcome per song to ``LeadSheets/_batch.log``.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
from dataclasses import dataclass
from pathlib import Path

from omr_leadsheet.config import Config
from omr_leadsheet.pipeline.process import process

__all__ = ["batch", "BatchResult", "find_songs_dir"]


# Candidate sub-directory names for the song PDFs, tried in order. The
# project convention is ``individual_songs`` (snake_case), but historic
# layouts and other songbooks may use the title-case form.
_SONGS_DIR_CANDIDATES = ("individual_songs", "Individual Songs", "Individual_Songs")


@dataclass(frozen=True, slots=True)
class BatchResult:
    processed: int
    failed: int
    log_path: Path


def find_songs_dir(book_dir: Path) -> Path:
    """Return the first existing songs sub-directory under ``book_dir``.

    Raises ``FileNotFoundError`` listing the candidates tried if none
    exist. Pre-fix, batch silently looked at a non-existent
    ``Individual Songs`` and reported ``0 processed`` with no error.
    """
    for name in _SONGS_DIR_CANDIDATES:
        candidate = book_dir / name
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"No songs sub-directory found under {book_dir}. "
        f"Tried: {', '.join(_SONGS_DIR_CANDIDATES)}."
    )


def batch(
    config: Config,
    *,
    force: bool = False,
    with_oemer: bool = False,
    only: str = "*.pdf",
) -> BatchResult:
    """Process every PDF under ``<book_dir>/<songs_dir>/`` matching ``only``.

    ``songs_dir`` is auto-detected from a small set of candidate names
    via :func:`find_songs_dir`; raises ``FileNotFoundError`` if none
    exist (replaces the silent ``0 processed`` behavior pre-fix).
    """
    in_dir = find_songs_dir(config.book_dir)
    lead_sheets = config.book_dir / "LeadSheets"
    lead_sheets.mkdir(parents=True, exist_ok=True)
    log_path = lead_sheets / "_batch.log"
    log_path.write_text("")

    pdfs = sorted(p for p in in_dir.glob("*.pdf") if fnmatch.fnmatch(p.name, only))
    processed = 0
    failed = 0
    with log_path.open("a") as log:
        log.write(f"Starting batch at {_dt.datetime.now().isoformat()}\n")
        for index, pdf in enumerate(pdfs, start=1):
            header = f"===== [{index}] {pdf.name} ====="
            print(header)
            log.write(header + "\n")
            log.flush()
            try:
                process(config, pdf, force=force, with_oemer=with_oemer)
                processed += 1
                log.write("  ok\n")
            except Exception as exc:
                failed += 1
                log.write(f"  FAILED: {exc}\n")
                print(f"  FAILED: {exc}")
        finished = f"Done at {_dt.datetime.now().isoformat()}: {len(pdfs)} processed, {failed} failed"
        print(finished)
        log.write(finished + "\n")

    return BatchResult(processed=processed, failed=failed, log_path=log_path)
