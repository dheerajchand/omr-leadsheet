"""Top-level ``omr-lead`` CLI.

Subcommands:

    omr-lead process <pdf>          Run one song through the pipeline
    omr-lead batch                  Process every PDF in BOOK_DIR/Individual Songs
    omr-lead dataset extract        Build training dataset from .omr chord-names
    omr-lead dataset extract-unlabeled
    omr-lead dataset prefill        Pre-fill labels.csv with classifier guesses
    omr-lead dataset context-crops  Generate wider context crops for each label
    omr-lead dataset label-ui       Build a one-page HTML labeling reviewer
    omr-lead dataset import         Apply hand-corrected labels into dataset/
    omr-lead dataset synth          Render synthetic chord crops
    omr-lead dataset clean          Apply dataset_corrections.json
    omr-lead train                  Train the CNN classifier
    omr-lead inspect <mxl>          Print high-level summary of a MusicXML file
    omr-lead review <song-dir>      Build the HTML review tool for a song
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from omr_leadsheet.config import Config

__all__ = ["app"]


app = typer.Typer(
    name="omr-lead",
    no_args_is_help=True,
    help="Convert scanned piano-vocal PDFs into jazz lead sheets.",
)
dataset_app = typer.Typer(no_args_is_help=True, help="Training-data tooling.")
app.add_typer(dataset_app, name="dataset")


def _config(book_dir: Path | None) -> Config:
    return Config.from_env(book_dir)


@app.command()
def process(
    pdf: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    book_dir: Path = typer.Option(None, "--book-dir", envvar="BOOK_DIR"),
    force: bool = typer.Option(False, "--force", help="Re-run every cached step"),
    with_oemer: bool = typer.Option(False, "--with-oemer", help="Run oemer second OMR pass"),
) -> None:
    """Run one PDF through the full pipeline."""
    from omr_leadsheet.pipeline.process import process as run

    mscz = run(_config(book_dir), pdf, force=force, with_oemer=with_oemer)
    typer.echo(f"done -> {mscz}")


@app.command()
def batch(
    book_dir: Path = typer.Option(None, "--book-dir", envvar="BOOK_DIR"),
    force: bool = typer.Option(False, "--force"),
    with_oemer: bool = typer.Option(False, "--with-oemer"),
    only: str = typer.Option("*.pdf", "--only", help="Glob to filter PDFs"),
) -> None:
    """Process every PDF in ``<book_dir>/Individual Songs/``."""
    from omr_leadsheet.pipeline.batch import batch as run

    result = run(_config(book_dir), force=force, with_oemer=with_oemer, only=only)
    typer.echo(f"processed={result.processed} failed={result.failed} log={result.log_path}")


@app.command()
def inspect(mxl: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Print a quick summary of a .mxl or .musicxml file."""
    _run_module("omr_leadsheet.utils.inspect", [str(mxl)])


@app.command()
def review(song_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Rebuild the HTML review page for a single song."""
    _run_module("omr_leadsheet.reporting.review", [str(song_dir)])


@app.command()
def train(
    dataset_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    out: Path = typer.Argument(...),
    epochs: int = typer.Option(30, "--epochs"),
    batch_size: int = typer.Option(32, "--batch-size"),
    lr: float = typer.Option(1e-3, "--lr"),
    val_split: float = typer.Option(0.1, "--val-split"),
    min_per_class: int = typer.Option(3, "--min-per-class"),
) -> None:
    """Train the CNN chord-symbol classifier."""
    _run_module("omr_leadsheet.training.train", [
        str(dataset_dir), str(out),
        "--epochs", str(epochs),
        "--batch-size", str(batch_size),
        "--lr", str(lr),
        "--val-split", str(val_split),
        "--min-per-class", str(min_per_class),
    ])


# --- dataset subcommands -----------------------------------------------------


@dataset_app.command("extract")
def dataset_extract(
    omr_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    out_dir: Path = typer.Argument(...),
) -> None:
    """Extract labeled chord-name crops from .omr files."""
    _run_module("omr_leadsheet.dataset.extract", [str(omr_dir), str(out_dir)])


@dataset_app.command("extract-unlabeled")
def dataset_extract_unlabeled(
    omr_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    out_dir: Path = typer.Argument(...),
) -> None:
    """Extract unlabeled chord crops and articulation candidates for hand-labeling."""
    _run_module("omr_leadsheet.dataset.extract_unlabeled", [str(omr_dir), str(out_dir)])


@dataset_app.command("prefill")
def dataset_prefill(
    labeling_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Pre-fill labels.csv with the current classifier's best guess."""
    _run_module("omr_leadsheet.dataset.prefill", [str(labeling_dir)])


@dataset_app.command("context-crops")
def dataset_context_crops(
    labeling_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    omr_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Render wider context crops alongside each tight glyph crop."""
    _run_module("omr_leadsheet.dataset.context_crops", [str(labeling_dir), str(omr_dir)])


@dataset_app.command("label-ui")
def dataset_label_ui(
    labeling_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Build label.html, a one-page HTML reviewer for crops."""
    _run_module("omr_leadsheet.dataset.label_ui", [str(labeling_dir)])


@dataset_app.command("import")
def dataset_import(
    labeling_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    dataset_dir: Path = typer.Argument(...),
) -> None:
    """Apply hand-corrected labels into the training dataset."""
    _run_module("omr_leadsheet.dataset.import_corrections", [str(labeling_dir), str(dataset_dir)])


@dataset_app.command("synth")
def dataset_synth(out_dir: Path = typer.Argument(...)) -> None:
    """Render synthetic chord-symbol crops covering every root x quality x extension."""
    _run_module("omr_leadsheet.dataset.synth_renderer", [str(out_dir)])


@dataset_app.command("clean")
def dataset_clean(
    dataset_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    corrections_json: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Apply dataset_corrections.json (class renames) to the dataset tree."""
    _run_module("omr_leadsheet.dataset.clean_labels", [str(dataset_dir), str(corrections_json)])


# --- helpers -----------------------------------------------------------------


def _run_module(module: str, args: list[str]) -> None:
    """Run a sub-module's argparse main via ``python -m``.

    Used as a transition shim: the underlying scripts retain their CLI surface
    so external callers (tests, scripts) keep working while subcommands here
    expose a typer-shaped front door.
    """
    result = subprocess.run([sys.executable, "-m", module, *args], timeout=3600)
    raise typer.Exit(code=result.returncode)


if __name__ == "__main__":
    app()
