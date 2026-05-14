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

__all__ = ["batch", "BatchResult"]


@dataclass(frozen=True, slots=True)
class BatchResult:
    processed: int
    failed: int
    log_path: Path


def batch(
    config: Config,
    *,
    force: bool = False,
    with_oemer: bool = False,
    only: str = "*.pdf",
) -> BatchResult:
    """Process every PDF in ``<book_dir>/Individual Songs/`` matching ``only``."""
    in_dir = config.book_dir / "Individual Songs"
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
