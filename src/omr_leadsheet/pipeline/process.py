"""Run one PDF through the full pipeline.

Replacement for the legacy ``scripts/process_song.sh``. Stages are
identical and cached on disk:

    1. Audiveris OMR              ->  MusicXML/<song>.omr  + .mxl
    2. MusicXML cleanup           ->  MusicXML/<song>.clean.xml
    3. Tesseract lyric OCR        ->  Lyrics/<song>.txt
    4. Reducer                    ->  LeadSheets/<song>/<song> - lead.musicxml
    5. Chord-diff + recoveries    ->  ... - lead.chords.musicxml
    6. Head recovery              ->  ... - lead.heads.musicxml
    7. NW lyric spell-check       ->  ... - lead.corrected.musicxml
    8. Final tuplet cleanup       ->  ... - lead.final.musicxml
    9. MuseScore style + export   ->  <song>.mscz
   10. Suspicious-measure report  ->  <song>.review.md  +  review.html
"""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from omr_leadsheet.config import Config
from omr_leadsheet.pipeline import lyrics

__all__ = ["process"]


def _step(log: IO[str], song: str, message: str) -> None:
    line = f"  [{song}] {message}"
    print(line)
    log.write(line + "\n")
    log.flush()


def _intro_dropped(clean_xml: Path) -> int:
    """How many leading empty measures the reducer will drop."""
    from music21 import converter, note

    score = converter.parse(str(clean_xml))
    best = score.parts[0]
    best_lyrics = -1
    for part in score.parts:
        count = sum(
            1 for n in part.recurse().notes
            if isinstance(n, note.Note) and n.lyrics
        )
        if count > best_lyrics:
            best_lyrics, best = count, part
    intro = 0
    for measure in best.getElementsByClass("Measure"):
        if not list(measure.recurse().notes):
            intro += 1
        else:
            break
    return intro


def _run_omr(
    config: Config, pdf: Path, mxl_dir: Path, mxl: Path, omr: Path, log: IO[str], song: str
) -> None:
    """Invoke Audiveris with a 400-DPI fallback if 200 DPI fails."""
    _step(log, song, "running Audiveris OMR")
    subprocess.run(
        [str(config.audiveris_bin), "-batch", "-export", "-output", str(mxl_dir), str(pdf)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        timeout=600,
    )
    if mxl.is_file():
        return
    _step(log, song, "OMR at 200 DPI failed, retrying at 400 DPI")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        subprocess.run(
            ["pdftoppm", "-r", "400", "-png", str(pdf), str(tmp_path / "page")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=300,
        )
        if shutil.which("magick") is None:
            return
        hi_pdf = tmp_path / "hi.pdf"
        pages = sorted(tmp_path.glob("page-*.png"))
        if not pages:
            return
        subprocess.run(
            ["magick", *[str(p) for p in pages], str(hi_pdf)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=300,
        )
        subprocess.run(
            [str(config.audiveris_bin), "-batch", "-export", "-output", str(mxl_dir), str(hi_pdf)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=600,
        )
        hi_mxl = mxl_dir / "hi.mxl"
        hi_omr = mxl_dir / "hi.omr"
        if hi_mxl.is_file():
            hi_mxl.rename(mxl)
        if hi_omr.is_file():
            hi_omr.rename(omr)


def _export_mscz(
    config: Config, lead_clean: Path, lead_corrected: Path, mscz: Path,
    out_dir: Path, song: str, log: IO[str],
) -> None:
    """Invoke MuseScore; on failure, retry after aggressive tuplet strip."""
    from omr_leadsheet.pipeline.cleanup import cleanup as cleanup_xml

    _step(log, song, "applying style -> .mscz")
    mscz.unlink(missing_ok=True)
    subprocess.run(
        [str(config.mscore_bin), "-S", str(config.style_file), "-o", str(mscz), str(lead_clean)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        timeout=300,
    )
    if mscz.is_file():
        return
    _step(log, song, "MuseScore rejected output, retrying with tuplets stripped")
    lead_notup = out_dir / f"{lead_corrected.stem.replace(' - lead.corrected', ' - lead.notuplets')}.musicxml"
    cleanup_xml(lead_corrected, lead_notup, aggressive=True)
    subprocess.run(
        [str(config.mscore_bin), "-S", str(config.style_file), "-o", str(mscz), str(lead_notup)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        timeout=300,
    )


@contextmanager
def _tee_log(pipeline_log: Path):
    """Open a pipeline log file for append-mode writing."""
    pipeline_log.parent.mkdir(parents=True, exist_ok=True)
    with pipeline_log.open("a") as log:
        log.write(f"--- {_dt.datetime.now(_dt.UTC).isoformat()} pipeline run\n")
        log.flush()
        yield log


def process(
    config: Config,
    pdf: Path,
    *,
    force: bool = False,
    with_oemer: bool = False,
) -> Path:
    """Drive a single song from PDF to .mscz. Returns the .mscz path."""
    if not pdf.is_file():
        raise FileNotFoundError(f"not a file: {pdf}")

    song = pdf.stem
    # Songbook sub-directory layouts vary (snake_case vs TitleCase).
    # Find existing dirs; create snake_case ones if none exist. See
    # pipeline/_paths.py for the candidate sets. Bug #21: previously
    # hardcoded TitleCase names caused process.py to miss the
    # snake_case cache and re-run Audiveris every time.
    from omr_leadsheet.pipeline._paths import (
        LEADSHEETS_DIR_CANDIDATES,
        LYRICS_DIR_CANDIDATES,
        MXL_DIR_CANDIDATES,
        find_subdir,
    )
    mxl_dir = find_subdir(config.book_dir, MXL_DIR_CANDIDATES, must_exist=False)
    lyr_dir = find_subdir(config.book_dir, LYRICS_DIR_CANDIDATES, must_exist=False)
    leadsheets_root = find_subdir(
        config.book_dir, LEADSHEETS_DIR_CANDIDATES, must_exist=False,
    )
    out_dir = leadsheets_root / song
    for d in (mxl_dir, lyr_dir, out_dir):
        d.mkdir(parents=True, exist_ok=True)

    omr = mxl_dir / f"{song}.omr"
    mxl = mxl_dir / f"{song}.mxl"
    clean_xml = mxl_dir / f"{song}.clean.xml"
    txt = lyr_dir / f"{song}.txt"
    lead = out_dir / f"{song} - lead.musicxml"
    lead_chords = out_dir / f"{song} - lead.chords.musicxml"
    lead_heads = out_dir / f"{song} - lead.heads.musicxml"
    lead_corr = out_dir / f"{song} - lead.corrected.musicxml"
    lead_final = out_dir / f"{song} - lead.final.musicxml"
    mscz = out_dir / f"{song}.mscz"
    review_md = out_dir / f"{song}.review.md"
    pipeline_log = out_dir / "_pipeline.log"

    with _tee_log(pipeline_log) as log:
        if force or not mxl.is_file():
            _run_omr(config, pdf, mxl_dir, mxl, omr, log, song)
        else:
            _step(log, song, "OMR cached")
        if not mxl.is_file():
            raise RuntimeError(f"OMR failed for {song} at both 200 and 400 DPI")

        from omr_leadsheet.pipeline.cleanup import cleanup as cleanup_xml
        if force or not clean_xml.is_file():
            _step(log, song, "cleaning raw MusicXML")
            cleanup_xml(mxl, clean_xml)

        if force or not txt.is_file():
            _step(log, song, "extracting lyrics via tesseract")
            lyrics.extract(pdf, txt)
        else:
            _step(log, song, "lyrics cached")

        from omr_leadsheet.pipeline.reduce import reduce_score
        _step(log, song, "reducing to lead sheet")
        reduce_score(str(clean_xml), str(lead), keep_verse=True)

        offset = -_intro_dropped(clean_xml)

        _step(log, song, f"recovering chord symbols from .omr (offset {offset})")
        _shell_module(
            "omr_leadsheet.chord_ops.diff",
            [str(omr), str(mxl),
             "--measure-offset", str(offset),
             "--insert-into", str(lead), "--out", str(lead_chords)],
            config=config,
        )

        _step(log, song, "recovering note-heads from .omr")
        try:
            _shell_module(
                "omr_leadsheet.pipeline.head_recovery",
                [str(omr), str(lead_chords), str(lead_heads),
                 "--measure-offset", str(offset)],
                config=config,
            )
        except subprocess.CalledProcessError:
            shutil.copy2(lead_chords, lead_heads)

        if txt.is_file():
            _step(log, song, "NW-aligning lyrics against tesseract")
            _shell_module(
                "omr_leadsheet.pipeline.spell_check",
                [str(lead_heads), str(txt), str(lead_corr)],
                config=config,
            )
        else:
            shutil.copy2(lead_heads, lead_corr)

        cleanup_xml(lead_corr, lead_final)

        _export_mscz(config, lead_final, lead_corr, mscz, out_dir, song, log)
        if not mscz.is_file():
            raise RuntimeError(f"MuseScore failed to produce {mscz}")

        _step(log, song, "writing review report")
        with review_md.open("w") as review:
            review.write(f"# Review: {song}\n\n")
            review.flush()
            subprocess.run(
                [str(config.python_bin), "-m", "omr_leadsheet.reporting.suspicious",
                 "--markdown", str(lead_corr)],
                stdout=review, check=False,
                timeout=300,
            )
        subprocess.run(
            [str(config.python_bin), "-m", "omr_leadsheet.reporting.review", str(out_dir)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            timeout=300,
        )

        _step(log, song, f"done -> {mscz}")

    return mscz


def _shell_module(module: str, args: list[str], *, config: Config) -> None:
    """Run a sub-module as ``python -m`` so legacy argparse mains keep working."""
    import os

    env = dict(os.environ)
    env.update(config.to_env())
    subprocess.run(
        [str(config.python_bin), "-m", module, *args],
        env=env, check=True,
        timeout=3600,
    )
