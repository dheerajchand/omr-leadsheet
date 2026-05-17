"""Per-step timeout threading for the CLI dispatchers (#3).

PR #2 capped both ``_run_module`` (cli.py) and ``_shell_module``
(pipeline/process.py) at a hard-coded 3600s to satisfy writing-code:15.
That kept I/O bounded but made the dispatchers the wrong place to set
the ceiling -- they don't know whether they're invoking Audiveris, an
OCR pass, or a 5-second lyric alignment.

The fix gives each dispatcher a ``timeout=`` kwarg whose default
preserves the historical 3600s safety cap. Pipeline stages that know
their workload pass an explicit per-step value; everyone else keeps
the same behavior.

These tests pin the threading contract: whatever the caller passes
must reach ``subprocess.run``'s ``timeout=`` argument verbatim, and
the default must remain 3600.0 so anyone who silently drops the
kwarg in a future refactor sees a test failure.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_completed(returncode: int = 0):
    import subprocess
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    return cp


def _typer_exit():
    """typer.Exit subclasses click.exceptions.Exit, not SystemExit."""
    import typer
    return typer.Exit


# --- cli._run_module ------------------------------------------------------


def test_run_module_default_timeout_is_3600() -> None:
    from omr_leadsheet import cli
    with patch("omr_leadsheet.cli.subprocess.run", return_value=_make_completed()) as run:
        with pytest.raises(_typer_exit()):  # _run_module raises typer.Exit (click.exceptions.Exit)
            cli._run_module("some.module", ["--flag"])
    assert run.call_args.kwargs["timeout"] == 3600.0


def test_run_module_forwards_caller_timeout() -> None:
    from omr_leadsheet import cli
    with patch("omr_leadsheet.cli.subprocess.run", return_value=_make_completed()) as run:
        with pytest.raises(_typer_exit()):
            cli._run_module("some.module", [], timeout=42.0)
    assert run.call_args.kwargs["timeout"] == 42.0


def test_run_module_reports_actual_timeout_on_expiry(capsys) -> None:
    """The error message must echo the caller's ceiling, not the
    historical 3600 literal."""
    import subprocess
    from omr_leadsheet import cli
    with patch(
        "omr_leadsheet.cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="x", timeout=42.0),
    ):
        with pytest.raises(_typer_exit()):
            cli._run_module("some.module", [], timeout=42.0)
    err = capsys.readouterr().err
    assert "42s" in err or "42.0s" in err, err
    assert "3600" not in err, err


# --- pipeline.process._shell_module ---------------------------------------


def test_shell_module_default_timeout_is_3600() -> None:
    from omr_leadsheet.pipeline import process
    from omr_leadsheet.config import Config
    cfg = Config(book_dir=Path("/tmp"))
    with patch("omr_leadsheet.pipeline.process.subprocess.run", return_value=_make_completed()) as run:
        process._shell_module("some.module", ["x"], config=cfg)
    assert run.call_args.kwargs["timeout"] == 3600.0


def test_shell_module_forwards_caller_timeout() -> None:
    from omr_leadsheet.pipeline import process
    from omr_leadsheet.config import Config
    cfg = Config(book_dir=Path("/tmp"))
    with patch("omr_leadsheet.pipeline.process.subprocess.run", return_value=_make_completed()) as run:
        process._shell_module("some.module", ["x"], config=cfg, timeout=123.0)
    assert run.call_args.kwargs["timeout"] == 123.0
