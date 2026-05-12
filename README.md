# omr-leadsheet

Convert scanned piano-vocal PDFs into jazz-style **single-staff lead sheets**
(`.mscz`) ready to open and finalise in MuseScore 4.

The pipeline runs Audiveris OMR over your source PDFs, then layers on
chord-symbol recovery, lyric OCR + spell-correction, optional second-engine
OMR via [oemer](https://github.com/BreezeWhite/oemer), and a music21-based
"reducer" that turns the piano-vocal grand staff into a Real Book–style
single-staff melody with chord symbols, rehearsal letters (A, B, C…), and
the original lyrics underneath.

For each song you get:

- `Song.mscz` — the lead sheet, ready to open in MuseScore.
- `review.html` — a per-song page with cropped source images of every
  measure the pipeline flagged for review, so you can spot fixes faster
  than scrolling through MuseScore.
- `Song.review.md` — the same flags in markdown.

## Status

Tested on a 30-song book of Gershwin piano-vocal arrangements. All 30
songs produce `.mscz` files end-to-end. Note recall is ~99%; chord
recognition is the remaining weak spot (~10% miss/garble rate on the
test book, driven mostly by the stylised "jazz font" the source uses).
See `docs/failure_modes.md`.

## Dependencies

| Tool | Used for | Install |
|---|---|---|
| [Audiveris](https://github.com/Audiveris/audiveris) 5.10+ | Primary OMR (PDF → MusicXML) | `.pkg` from the releases page |
| [MuseScore 4](https://musescore.org/) | Style application, `.mscz` export | App from musescore.org |
| Tesseract 5 | Source-PDF lyric OCR | `brew install tesseract` |
| Poppler (`pdftoppm`) | High-DPI PDF rendering | `brew install poppler` |
| ImageMagick (`magick`) | Image cropping/compositing | `brew install imagemagick` |
| Python 3.11+ | Pipeline scripts | system / pyenv |
| `music21`, `matplotlib` | MusicXML manipulation, charts | `pip install -r requirements.txt` |
| `oemer` (optional) | Second OMR backend for reconciliation | `pip install oemer` |

You also need a MuseScore `.mss` style file in jazz lead-sheet style
(MuseJazz font, chord-symbol styling, etc.). The repo ships an example
configuration but not a style file — supply your own and point
`STYLE_FILE` at it.

## Quick start

```bash
# 1. Clone and set up
git clone <this repo> ~/code/omr-leadsheet
cd ~/code/omr-leadsheet
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Lay out your source book
#    ~/Desktop/MySongbook/
#      Individual Songs/
#        01 - Song A.pdf
#        02 - Song B.pdf
#        ...

# 3. Configure
export BOOK_DIR=~/Desktop/MySongbook
export STYLE_FILE=~/Documents/MuseScore4/Styles/MyStyle.mss

# 4. Run on one song
./scripts/process_song.sh "$BOOK_DIR/Individual Songs/01 - Song A.pdf"

# 5. Or run the whole batch (optionally with second-backend OMR)
./scripts/batch_all.sh
./scripts/batch_all.sh --with-oemer   # ~2 min/page extra per song
```

Outputs land in `$BOOK_DIR/LeadSheets/<song>/` with a `_SUMMARY.md` and
chart PNGs at the top level.

## What the pipeline does

```
        ┌──────────────────────────────────────────────────────────┐
        │                  Source piano-vocal PDF                   │
        └──────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
        Audiveris OMR        Tesseract OCR         oemer (optional)
        .omr + .mxl          lyric text            .musicxml
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    ▼
                          MusicXML cleanup (tuplets)
                                    │
                                    ▼
                          Reducer (music21):
                          - keep vocal staff
                          - drop intro
                          - octave-down, treble-8vb clef
                          - rehearsal letters A, B, C…
                                    │
                                    ▼
                          Chord recovery:
                          - Audiveris unlinked-chord recovery
                          - chord-row OCR with sliding window
                                    │
                                    ▼
                          Lyric correction:
                          - NW alignment vs tesseract truth
                          - word splitting + contractions
                                    │
                                    ▼
                          Optional: merge_omr.py with oemer
                          (content-aligned, marks ? on filled measures)
                                    │
                                    ▼
                          MuseScore: apply style, export .mscz
                                    │
                                    ▼
                          suspicious_measures.py
                          + review_tool.py
                          (flags + interactive HTML review)
```

## Repository layout

```
omr-leadsheet/
├── README.md
├── requirements.txt
├── pipeline/                   Python + bash modules
│   ├── reduce_to_lead.py       Piano-vocal → single-staff melody
│   ├── chord_diff.py           Recover Audiveris-unlinked chord symbols
│   ├── chord_row_ocr.py        Tesseract pass over the chord row
│   ├── cleanup_mxl.py          Strip unbalanced tuplet markup
│   ├── extract_lyrics.sh       pdftoppm + tesseract → clean lyrics
│   ├── spell_check_lyrics.py   NW-align Audiveris lyrics to tesseract truth
│   ├── head_recovery.py        Recover unlinked note-heads from .omr
│   ├── suspicious_measures.py  Flag likely-OCR-errors
│   ├── review_tool.py          Per-song HTML review page
│   ├── summary.py, charts.py   Cross-song reports
│   └── backends/
│       ├── oemer_backend.sh    Run oemer per page, concatenate
│       ├── oemer_prep.py       Paint piano-LH staves white before oemer
│       └── concat_oemer.py
├── scripts/
│   ├── env.sh                  Path configuration
│   ├── process_song.sh         End-to-end for one PDF
│   └── batch_all.sh            Loop over Individual Songs/
└── docs/
    ├── pipeline.md             Detailed pipeline reference
    ├── failure_modes.md        Where and why it goes wrong
    └── classifier.md           Training a chord-symbol classifier
```

## License

MIT. See `LICENSE`.
