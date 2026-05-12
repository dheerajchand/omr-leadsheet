"""Minimal structured logging helper for the Gershwin pipeline.

One function, `get_logger(name, log_file)`, returns a Logger that writes:
  - to stdout (INFO+), with a compact `[song] message` format
  - to a file at `log_file` (DEBUG+), with timestamps + level

No dependencies beyond the stdlib `logging` module.
"""
from __future__ import annotations
import logging
from pathlib import Path


def get_logger(name: str, log_file: str | Path | None = None) -> logging.Logger:
    """Return a configured logger. Idempotent (safe to call repeatedly)."""
    log = logging.getLogger(name)
    if getattr(log, "_gershwin_configured", False):
        return log
    log.setLevel(logging.DEBUG)
    log.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(f"[{name}] %(message)s"))
    log.addHandler(console)

    if log_file is not None:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(message)s",
            datefmt="%H:%M:%S",
        ))
        log.addHandler(fh)

    log._gershwin_configured = True  # type: ignore[attr-defined]
    return log
