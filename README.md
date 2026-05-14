# omr-leadsheet

Convert scanned piano-vocal PDFs into jazz-style **single-staff lead sheets**
(`.mscz`) ready to open and finalise in MuseScore 4.

The pipeline runs Audiveris OMR over your source PDFs, then layers on
chord-symbol recovery (CNN + vision-language model), lyric OCR + spell
correction, optional second-engine OMR via
[oemer](https://github.com/BreezeWhite/oemer), and a music21-based
reducer that turns the piano-vocal grand staff into a Real Book–style
single-staff melody with chord symbols, rehearsal letters (A, B, C…),
and the original lyrics underneath.

For each song you get:

- `Song.mscz` — the lead sheet, ready to open in MuseScore.
- `review.html` — a per-song page with cropped source images of every
  measure flagged for review.
- `Song.review.md` — the same flags in markdown.

## Status

Tested on a 30-song book of Gershwin piano-vocal arrangements. All 30
songs produce `.mscz` files end-to-end. Note recall is ~99%; chord
recognition is now near-perfect with `CHORD_VLM=1` (qwen2.5vl via
ollama, or Claude via the Anthropic API). See `docs/vlm.md` and
`docs/failure_modes.md`.

## Dependencies

| Tool | Used for | Install |
|---|---|---|
| [Audiveris](https://github.com/Audiveris/audiveris) 5.10+ | Primary OMR (PDF -> MusicXML) | `.pkg` from the releases page |
| [MuseScore 4](https://musescore.org/) | Style application, `.mscz` export | App from musescore.org |
| Tesseract 5 | Source-PDF lyric OCR | `brew install tesseract` |
| Poppler (`pdftoppm`) | High-DPI PDF rendering | `brew install poppler` |
| ImageMagick (`magick`) | Image cropping / compositing | `brew install imagemagick` |
| Python 3.11+ | Pipeline runtime | system / pyenv |
| `ollama` (optional, recommended) | Local vision-language model for chord OCR — see `docs/vlm.md` | `brew install ollama && ollama pull qwen2.5vl:7b` |

You also need a MuseScore `.mss` style file in jazz lead-sheet style.
The repo ships no style file; supply your own and point `STYLE_FILE`
at it (or `omr-lead --style-file`).

## Install

```bash
git clone https://github.com/dheerajchand/omr-leadsheet ~/code/omr-leadsheet
cd ~/code/omr-leadsheet
pip install -e .                  # core
pip install -e ".[classifier]"    # also install torch for the CNN recogniser
pip install -e ".[dev]"           # plus pytest + ruff
```

`pip install -e .` adds an `omr-lead` console entry point.

## Quick start

```bash
# 1. Lay out your songbook elsewhere on disk
#    ~/Desktop/MySongbook/
#      Individual Songs/
#        01 - Song A.pdf
#        02 - Song B.pdf
#        ...

# 2. Point the tool at it (env var or --book-dir flag)
export BOOK_DIR=~/Desktop/MySongbook
export STYLE_FILE=~/Documents/MuseScore4/Styles/MyStyle.mss

# 3. Optional: enable vision-language chord recognition
export CHORD_VLM=1
ollama pull qwen2.5vl:7b

# 4. Process one song
omr-lead process "$BOOK_DIR/Individual Songs/01 - Song A.pdf"

# 5. Or run the whole batch
omr-lead batch
omr-lead batch --with-oemer       # extra ~2 min/page per song
```

Outputs land in `$BOOK_DIR/LeadSheets/<song>/`.

## CLI surface

```
omr-lead process <pdf>            Run one song end to end
omr-lead batch                    Process every PDF in BOOK_DIR/Individual Songs
omr-lead inspect <mxl>            Print a high-level summary of a MusicXML file
omr-lead review <song-dir>        Rebuild review.html for one song
omr-lead train <dataset> <out>    Train the CNN chord classifier
omr-lead dataset extract          Build training dataset from .omr chord-names
omr-lead dataset extract-unlabeled
omr-lead dataset prefill          Pre-fill labels.csv with classifier guesses
omr-lead dataset context-crops    Render wider context crops for each label
omr-lead dataset label-ui         Build a one-page HTML reviewer
omr-lead dataset import           Apply hand-corrected labels back to dataset/
omr-lead dataset synth            Render synthetic chord crops
omr-lead dataset clean            Apply dataset_corrections.json
```

Each subcommand also accepts `--help`. Legacy environment variables
(`BOOK_DIR`, `STYLE_FILE`, `AUDIVERIS_BIN`, `MSCORE_BIN`, `CHORD_VLM`,
`CHORD_VLM_BACKEND`, `CHORD_VLM_MODEL`, `CHORD_CLASSIFIER_PATH`,
`CHORD_SWEEP_ENABLE`) still work; they feed `Config.from_env()` at
startup.

## Repository layout

```
omr-leadsheet/
├── pyproject.toml
├── README.md
├── LICENSE
├── docs/
│   ├── pipeline.md
│   ├── classifier.md
│   ├── failure_modes.md
│   └── vlm.md
├── src/omr_leadsheet/
│   ├── cli.py                 typer entry point
│   ├── config.py              Config dataclass (replaces env.sh)
│   ├── pipeline/              process, batch, reduce, cleanup, lyrics, head_recovery
│   ├── recognisers/           vlm, cnn, blobs, row_ocr
│   ├── chord_ops/             parser, diff
│   ├── dataset/               extract, prefill, label-ui, import, synth, clean
│   ├── training/              train (CNN)
│   ├── reporting/             review, suspicious, charts, summary
│   └── utils/                 log, inspect
├── scripts/
│   └── extract_lyrics.sh      shell helper called by pipeline.lyrics
├── tests/                     pytest suite (no real OMR data required)
├── dataset/                   training crops, one folder per chord class
└── classifier.pt              trained CNN checkpoint
```

## Docs

- [`getting-started.md`](docs/getting-started.md) — full install + run walkthrough
- [`pipeline.md`](docs/pipeline.md) — stage-by-stage reference
- [`vlm.md`](docs/vlm.md) — ollama + Anthropic backends for chord recognition
- [`classifier.md`](docs/classifier.md) — training the CNN classifier
- [`failure_modes.md`](docs/failure_modes.md) — known weak spots

## License

MIT. See `LICENSE`.
