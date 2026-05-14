# Pipeline reference

Each step writes to disk so any single stage can be re-run during
development without redoing the expensive OMR pass.

The orchestration lives in `omr_leadsheet.pipeline.process` and is
invoked by `omr-lead process` (one song) or `omr-lead batch` (every
PDF in `BOOK_DIR/individual_songs`).

## Per-song stages

### 1. Audiveris OMR — `omr_leadsheet.pipeline.process._run_omr`

Input: `individual_songs/<song>.pdf`

Output: `music_xml/<song>.omr` (project file with full glyph-level
data) plus `music_xml/<song>.mxl` (compressed MusicXML).

If OMR fails at default DPI, the pipeline retries at 400 DPI via
`pdftoppm` and ImageMagick. The resulting `.mxl` is what music21 reads.

### 2. MusicXML cleanup — `omr_leadsheet.pipeline.cleanup.cleanup`

Audiveris sometimes emits unbalanced `<tuplet type="start">` elements
without a matching stop, which causes MuseScore to silently reject
the whole file (exit 40). `cleanup` rewrites every measure with
mismatched tuplet brackets, stripping them while leaving the underlying
note durations alone. The aggressive mode strips **all** tuplets and
is used as a fallback if MuseScore still refuses to import.

### 3. Tesseract lyric OCR — `omr_leadsheet.pipeline.lyrics.extract`

Input: source PDF. Output: `lyrics/<song>.txt`.

Renders at 400 DPI, runs tesseract at PSM 6, filters lines with a
system-dictionary word check plus a lowercase-majority gate so
music-notation noise drops out. This gives ground-truth lyric text
for later spell-correction. The Python wrapper shells out to
`scripts/extract_lyrics.sh`.

### 4. Reducer — `omr_leadsheet.pipeline.reduce.reduce_score`

Turns the multi-staff piano-vocal score into a single-staff lead sheet:

- Picks the vocal part (most notes-with-lyrics; falls back to part 0
  for piano-solo scores)
- Trims leading rest-only measures (the piano intro before vocals
  enter)
- Renumbers measures from 1
- Inserts rehearsal letters (A at m1, B at refrain start when verse
  is kept, then a letter every `section_bars` bars)
- Collapses key signatures to one per section by majority vote
- Octave-down transpose plus treble-8vb clef for Real Book vocal-line
  conventions
- Writes with `makeNotation=False` so music21 does not re-introduce
  bad XML during export

### 5. Chord recovery

Three passes against the `.omr`, all of them feeding into
`omr_leadsheet.chord_ops.diff.insert_missing`:

a. **Audiveris-recognised chord-names** (`chord_ops.diff.parse_sheet`)
   — `<chord-name value="...">` elements Audiveris detected but did
   not export to the `.mxl` (linking failure in the rhythm-resolution
   step). Inserted at the correct beat offset from the chord-name's
   x-coordinate.

b. **MARCATO/ACCENT recovery** (`recognisers.row_ocr._recover_misclassified_articulations`)
   — Audiveris occasionally misclassifies a jazz-font chord glyph
   (A, C#+, etc.) as a marcato or accent articulation on the note
   below. The recovery walks every articulation in chord-row territory
   (20-120 px above any staff), crops a tight glyph window, and hands
   it to the configured chord recogniser (VLM by default, CNN as
   fallback).

c. **Blob scan** (`recognisers.blobs.scan_chord_row_blobs`, opt-in via
   `CHORD_VLM=1`) — finds chord glyphs Audiveris dropped entirely.
   Scans the chord-row strip above every staff for connected ink
   blobs (gap-separated columns), crops each blob with clean
   left/right boundaries, and asks the VLM to identify it. The wider
   110-px strip captures stacked extensions (9-over-7) that the
   narrower tesseract pass cuts off.

`chord_ops.diff.diff` enforces a specificity rule: an existing chord
suppresses a new one only when it is at least as specific. So
existing `Am7` suppresses a redundant `Am`, but existing `G7` does
**not** suppress a new `G9/7`. At insertion time, less-specific
duplicates already in the file are removed in favour of the new
more-specific chord.

### 6. Lyric correction — `omr_leadsheet.pipeline.spell_check`

Audiveris's lyric OCR is OK syllable-by-syllable but corrupts many
words (jazz font plus tight kerning). The corrector:

- Builds a flat token stream from the tesseract-clean text, split by
  whitespace and hyphens (capturing syllable boundaries)
- Builds the Audiveris lyric stream from music21, grouped by verse
  number
- Needleman-Wunsch aligns both streams
- For each aligned pair, keeps the Audiveris token if it is a real
  dictionary word (with extensions for common jazz syllables and
  modern English contractions web2 misses); otherwise substitutes
  the tesseract truth
- Splits merged tokens (e.g. `dontknowwhere`) via a dictionary-based
  DP segmenter
- Inserts tesseract tokens with no Audiveris counterpart when bounded
  by good context on both sides

### 7. Optional: oemer second pass + merge

When `omr-lead process --with-oemer` is passed:

a. `_legacy_backends/oemer_prep.py` paints piano-LH staves white in
   the page PNGs. This sidesteps oemer's hard `assert track_nums == 2`
   that would otherwise crash on piano-vocal systems.

b. `_legacy_backends/oemer_backend.sh` runs oemer page-by-page and
   concatenates per-page MusicXMLs into one score.

c. `omr_leadsheet.pipeline.merge_omr` aligns Audiveris and oemer
   measures by **content fingerprint** (note count, duration, rhythm
   shape, first pitch) via Needleman-Wunsch. For each primary measure
   that has only rests but aligns confidently (neighbour-context
   similarity >= 0.55) to an oemer measure with notes, copies the
   oemer notes in and inserts a red `?` TextExpression so the user can
   verify.

### 8. Style + export — MuseScore CLI

`mscore -S <style.mss> -o <song.mscz> <song.musicxml>`

If MuseScore rejects the file, the pipeline retries with
`cleanup(..., aggressive=True)`, which strips all tuplet markup. The
`.mscz` always ends up produced, even if some rhythmic notation is
lost.

### 9. Review artefacts — `omr_leadsheet.reporting.*`

`reporting.suspicious` flags three classes per measure:

- `all_rests_with_chords` — measure has chord symbols but no melody
  notes. Almost always a missed whole-note.
- `duration_mismatch` — measure duration differs from the prevailing
  time signature. Usually tuplet errors that did not crash but
  indicate Audiveris uncertainty.
- `missing_lyrics` — measure has notes but no lyrics, while
  neighbouring measures do. Suggests a dropped lyric line.

`reporting.review` builds a self-contained HTML page per song with a
row per flagged measure showing the source-image crop, the pipeline's
capture, and a correction text box. Corrections auto-save to
localStorage and can be exported to `corrections.json`.

## Cross-song reports

After `omr-lead batch` finishes, `reporting.summary` and
`reporting.charts` produce:

- `lead_sheets/_SUMMARY.md` — per-song flag counts
- `lead_sheets/_summary.png` — stacked bar chart
- `lead_sheets/_totals.png` — totals by flag category

## Caching

The pipeline caches every expensive step on disk:

- `.omr` and `.mxl` from Audiveris (re-run only with `--force`)
- `.clean.xml` from cleanup
- `.txt` from tesseract
- `.musicxml` from oemer (per-song)
- VLM responses at `~/.cache/chord_vlm/<sha>.json`

Re-running the post-OMR steps (reducer, chord recovery, lyric
correction, MuseScore export) is fast — typically <20 sec per song
when caches are warm — so iterating on those modules without re-OMR
is the recommended development loop.
