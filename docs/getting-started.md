# Getting started

End-to-end walkthrough: install, point the tool at a songbook, run one
song, then run the whole book.

## 1. Install the tool

```bash
git clone https://github.com/dheerajchand/omr-leadsheet ~/code/omr-leadsheet
cd ~/code/omr-leadsheet
pip install -e .                  # adds the omr-lead command
```

Optional extras:

```bash
pip install -e ".[classifier]"    # adds torch for the CNN recogniser
pip install -e ".[oemer]"         # adds oemer second-engine OMR
pip install -e ".[dev]"           # adds pytest and ruff
```

The CLI now lives at `omr-lead` (typer-backed). Run `omr-lead --help`
to see every subcommand.

## 2. System dependencies

| Tool | Purpose | macOS install |
|---|---|---|
| Audiveris 5.10+ | Primary OMR | `.pkg` from the releases page |
| MuseScore 4 | Style application, `.mscz` export | App from musescore.org |
| Tesseract 5 | Lyric OCR | `brew install tesseract` |
| Poppler | High-DPI PDF rendering | `brew install poppler` |
| ImageMagick | Image cropping / compositing | `brew install imagemagick` |
| ollama (optional) | Local VLM for chord recognition | `brew install ollama && ollama pull qwen2.5vl:7b` |

You also need a MuseScore `.mss` style file in jazz lead-sheet style
(the example deployment uses MuseJazz Text plus a custom chord-symbol
style). The repo ships none; supply your own and point `STYLE_FILE`
at it.

## 3. Songbook layout

The tool reads from a separate **songbook directory**. The conventional
layout:

```
<songbook>/
├── individual_songs/             one PDF per song
├── music_xml/                    Audiveris outputs (created on first run)
├── lyrics/                       tesseract output (created on first run)
├── lead_sheets/                  pipeline output, one folder per song
└── style/Dheeraj-Jazz.mss        MuseScore style file (optional in this location)
```

`individual_songs/` is the only directory you create up front. The
rest are populated by the pipeline.

If you have an existing tree using the old title-case names
(`Individual Songs`, `LeadSheets`, etc.) the legacy layout works too
because the pipeline scripts treat the path strings as opaque. The
new layout is recommended for new books.

## 4. Configure

The pipeline reads its configuration from environment variables. Set
them in your shell rc or a per-project `.envrc` (with direnv).

```bash
export BOOK_DIR=~/path/to/songbook
export STYLE_FILE="$BOOK_DIR/style/Dheeraj-Jazz.mss"

# Recommended: enable the vision-language chord recogniser
export CHORD_VLM=1
export CHORD_VLM_BACKEND=ollama          # the default; "anthropic" is the alternative
export CHORD_VLM_MODEL=qwen2.5vl:7b      # ollama model tag

# Optional: point at a trained CNN classifier as fallback
export CHORD_CLASSIFIER_PATH=~/code/omr-leadsheet/classifier.pt
```

Every variable above is also a CLI flag on `omr-lead process` and
`omr-lead batch` - see `omr-lead process --help`.

## 5. Run one song

```bash
omr-lead process "$BOOK_DIR/individual_songs/13 - Let's Call The Whole Thing Off.pdf"
```

Output lands at `$BOOK_DIR/lead_sheets/<song>/`:

- `<song>.mscz` - the final lead sheet
- `<song>.review.md` - flagged measures in markdown
- `review.html` - interactive HTML reviewer
- `<song> - lead.*.musicxml` - intermediate stages, kept for debugging
- `_pipeline.log` - per-song run log

Pass `--force` to redo every cached step. Pass `--with-oemer` to run
the second-engine OMR pass.

## 6. Run the whole book

```bash
omr-lead batch                    # every PDF in individual_songs/
omr-lead batch --only "01*.pdf"   # only filenames matching the glob
omr-lead batch --force            # rebuild everything
```

A batch log lands at `lead_sheets/_batch.log` with one line per song
plus pass/fail status.

## 7. Pairing with a private data repo

If your songbook is commercial sheet music (or anything else not safe
to publish), keep it in a private git repo separate from
`omr-leadsheet`. The tool stays public and reusable; the data stays
where only you can see it.

```bash
mkdir -p ~/code/my-songbook/individual_songs
cd ~/code/my-songbook
git init
gh repo create my-songbook --private --source=. --remote=origin
# Drop PDFs into individual_songs/, commit, push.
```

`omr-lead` operates against any songbook directory you point
`--book-dir` (or `BOOK_DIR`) at. The two repos stay independent.

## 8. What to read next

- [`pipeline.md`](pipeline.md) - what each stage of the pipeline does
- [`vlm.md`](vlm.md) - how to set up ollama or the Anthropic API for
  chord recognition
- [`classifier.md`](classifier.md) - training the CNN classifier from
  hand-labeled data
- [`failure_modes.md`](failure_modes.md) - known weak spots and
  workarounds
