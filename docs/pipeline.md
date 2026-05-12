# Pipeline reference

Each step is implemented as a standalone script that reads/writes files,
so you can re-run any single stage during development without redoing
the expensive OMR pass.

## Per-song stages

`scripts/process_song.sh` chains the following:

### 1. Audiveris OMR — `Audiveris -batch -export`

Input: `Individual Songs/<song>.pdf`
Outputs: `MusicXML/<song>.omr` (project file with full glyph-level data)
         `MusicXML/<song>.mxl` (compressed MusicXML)

If OMR fails at default DPI, retried at 400 DPI via `pdftoppm` +
ImageMagick combine. Resulting `.mxl` is what music21 reads.

### 2. Tesseract lyric OCR — `pipeline/extract_lyrics.sh`

Input:  Source PDF.
Output: `Lyrics/<song>.txt`

Renders at 400 DPI, OCR's at PSM 6, filters lines with a system-dict
word check + lowercase-majority gate to remove music-notation noise.
This gives clean ground-truth lyric text for later spell-correction.

### 3. MusicXML cleanup — `pipeline/cleanup_mxl.py`

Audiveris sometimes emits unbalanced `<tuplet type="start">` without a
matching stop, which causes MuseScore to silently reject the whole
file (exit 40). This module rewrites every measure with mismatched
tuplet brackets, stripping them while leaving the underlying note
durations alone. Aggressive mode (`--aggressive`) strips **all**
tuplets — used as a final fallback if MuseScore still won't import.

### 4. Reducer — `pipeline/reduce_to_lead.py`

Turns the multi-staff piano-vocal score into a single-staff lead sheet.

* Picks the **vocal part** (most notes-with-lyrics; falls back to part 0
  for piano-solo scores).
* **Trims leading rest-only measures** (the piano intro before vocals
  enter).
* Optional `--keep-verse` keeps the verse before the refrain. By
  default the verse is dropped (refrain-only Real Book style).
* **Renumbers** measures from 1.
* Inserts **rehearsal letters** (A at m1, B at refrain start if
  verse kept, then a letter every `section_bars` bars).
* Optional **system breaks** at each rehearsal letter for sight-reading
  layout.
* **Collapses key signatures** to one per section by majority vote —
  defends against Audiveris misreading the key at a section change.
* **Octave-down transpose** + **treble-8vb clef** to match Real Book
  vocal-line conventions.
* Writes with `makeNotation=False` so music21 doesn't re-introduce
  bad XML during export.

### 5. Chord recovery — `pipeline/chord_diff.py` + `chord_row_ocr.py`

Two passes against the `.omr`:

a. `chord_diff` — parses `<chord-name value="...">` elements
   Audiveris detected but didn't emit to the `.mxl` (linking failure
   in the rhythm-resolution step). Diffs against the exported chord
   symbols and inserts the missing ones at the correct beat offset
   (computed from the chord-name's x-coordinate relative to its
   measure's x-range).

b. `chord_row_ocr` — runs tesseract directly on the strip of pixels
   above each vocal staff (where chord symbols sit). Uses three
   passes: PSM 6 over the whole strip, PSM 11 (sparse text), and a
   sliding window with PSM 8 (single word) for crowded chord rows.
   Tokens matching the chord regex `^[A-G][#b♯♭]?…` are merged with
   the Audiveris-detected chords, deduped by x-proximity.

Both feeds use a `--measure-offset` flag to map raw-mxl measure
numbers to the reduced file's renumbered measures.

### 6. Lyric correction — `pipeline/spell_check_lyrics.py`

Audiveris's lyric OCR is OK syllable-by-syllable but corrupts
many words (jazz font + tight kerning). We:

* Build a flat token stream from the tesseract-clean text, split by
  whitespace and hyphens (capturing syllable boundaries).
* Build the Audiveris lyric stream from music21, grouped by verse
  number (1, 2 for stacked stanzas in refrains).
* **Needleman-Wunsch align** both streams.
* For each aligned pair: if Audiveris is a real dictionary word
  (with extensions for common jazz syllables + modern English
  contractions web2 misses), keep it; otherwise replace with the
  tesseract truth.
* **Word splitting** for merged tokens like `dontknowwhere` →
  `don't know where` using a dictionary-based DP segmenter.
* **Insertion** for tesseract tokens with no Audiveris counterpart,
  but only when bounded by good context on both sides.

### 7. Optional: oemer second pass + merge — `pipeline/backends/`

When `--with-oemer` is passed:

a. `oemer_prep.py` paints piano-LH staves white in the page PNGs.
   This bypasses oemer's hard `assert track_nums == 2` that
   otherwise crashes on piano-vocal systems.

b. `oemer_backend.sh` runs oemer page-by-page, concatenates the
   per-page MusicXMLs into one score (`concat_oemer.py`).

c. `merge_omr.py` aligns Audiveris and oemer measures by **content
   fingerprint** (note count, duration, rhythm shape, first pitch)
   via Needleman-Wunsch. For each primary measure that has only rests
   but aligns confidently (neighbour-context similarity ≥ 0.55) to an
   oemer measure with notes, copies the oemer notes in and inserts a
   red `?` `TextExpression` so the user can verify.

### 8. Style + export — MuseScore CLI

`mscore -S <style.mss> -o <song.mscz> <song.musicxml>`

If MuseScore rejects the file (exit 40), retries with `cleanup_mxl
--aggressive` which strips all tuplet markup. The `.mscz` always
ends up produced, even if some rhythmic notation is lost.

### 9. Review artefacts

`pipeline/suspicious_measures.py` flags three classes:

* `all_rests_with_chords` — measure has chord symbols but no melody
  notes. Almost always a missed whole-note.
* `duration_mismatch` — measure duration differs from the prevailing
  time signature. Usually tuplet errors that didn't cause crashes
  but indicate Audiveris uncertainty.
* `missing_lyrics` — measure has notes but no lyrics, while
  neighbouring measures do. Suggests a dropped lyric line.

`pipeline/review_tool.py` builds a self-contained HTML page per
song with a row per flagged measure showing the source-image crop,
the pipeline's capture, and a correction text box. Corrections
auto-save to localStorage and can be exported to `corrections.json`.

## Cross-song stages

After all songs run, the batch produces:

* `LeadSheets/_SUMMARY.md` — per-song flag counts (`summary.py`)
* `LeadSheets/_summary.png` — stacked bar chart (`charts.py`)
* `LeadSheets/_totals.png` — totals by flag category

## Caching

`process_song.sh` caches:

* `.omr` and `.mxl` from Audiveris (don't re-OMR unless `--force`)
* `.txt` from tesseract
* `.musicxml` from oemer (per-song)

Re-running the post-OMR steps (reducer, chord recovery, lyric
correction, MuseScore export) is fast — typically <20 sec per song —
so iterating on those modules without re-OMR is the recommended
development loop.
