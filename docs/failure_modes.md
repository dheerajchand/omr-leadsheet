# Failure modes — what to expect

A short field guide to the residual errors after the pipeline runs.
Tested on a 30-song book of Gershwin piano-vocal arrangements
(~3,500 measures total).

## Melodies — ~99% recall

Audiveris's note-head classifier is excellent. Pitched notes come
through correctly in almost every measure. The remaining 1% breaks
into two categories:

### Whole notes missed entirely

Audiveris occasionally fails to detect a hollow whole-note head,
especially when it sits on a measure with no other glyphs (typical
of a held vowel like "done.—" in vocal lines). The note never enters
the `.omr` at all, so no downstream recovery can fix it from that file.
Mitigations:

* The `all_rests_with_chords` flag identifies these measures (chord
  symbols exist but no melody). One per song or two is typical.
* The second-backend oemer pass + content-aligned merge catches some
  of them; on our test book it filled 8 out of 37 such measures.

### Wrong durations (tuplet miscounts)

`duration_mismatch` flags mean a measure's note durations don't add
up to the time signature. Often the notes are right but Audiveris
interpreted, say, a triplet as straight eighths or vice versa.
Notation looks slightly off in MuseScore but the pitches are correct.

## Chord symbols — ~85–90% reliable

Chord recognition is the weak spot. The pipeline runs three recovery
passes (`chord_diff`, `chord_row_ocr` with sliding window, multi-PSM
combined) and ends up catching most chord positions, but quality
degrades for:

### Stylised fonts

Audiveris and tesseract both struggle with jazz-style chord-symbol
fonts. The G⁹⁷ stacked-fraction notation in particular gets read as
"G7" — the 9 superscript is dropped. Same for similar stacked
constructions.

### Augmented chords (`C#+`, `A+`)

The `+` is often misread as a typographical mark or stripped by
the OCR whitelist. We recover `A+` when Audiveris caught it; we
typically lose it when only tesseract sees it.

### Dense chord rows

Pages where 5–7 chord changes happen on one staff line (verse
intros, fast passages) have tesseract failing to segment the
glyphs into separate words. Our sliding-window pass mitigates but
doesn't eliminate this.

## Lyrics — ~95% post-correction

After the Needleman-Wunsch alignment + dictionary spell-check, lyric
text is mostly clean. Residual issues:

### Merged syllables

`don'tknowwhere` is now split to `don't know where`, but compound
patterns Audiveris reads as one syllable can still trip the
splitter if the merged token isn't itself in the dictionary.

### Verse 2 alignment

Refrains with stacked verse 1 / verse 2 lyrics ("You say eether /
You say laughter") sometimes get verse 1 and verse 2 partially
crossed because their tesseract paired-line detection isn't perfect.
We restrict v2 insertions to v2's actual measure range to prevent
spreading them across the verse, but you'll still see odd v2
fragments in 1–2 measures per song.

### Missing measures

`missing_lyrics` flags entire measures with notes and no lyrics,
when neighbouring measures do have lyrics. Suggests a line of
lyric text the OCR dropped entirely.

## OMR engine failures

* **Audiveris rejects a sheet as "invalid"** — happens occasionally
  on dense or unusual pages (e.g. the last page of "All The Livelong
  Day" in our test). Workaround: re-render at 400 DPI and process
  pages one at a time; the pipeline does this automatically as a
  fallback.
* **MuseScore exit 40 / silent rejection** — usually a music21
  edge case with unbalanced tuplets. The `cleanup_mxl --aggressive`
  fallback in `process_song.sh` strips all tuplet notation as a last
  resort. You lose the visual tuplet bracket but the notes survive.
* **oemer `assert track_nums == 2`** — oemer's hard limitation on
  staff count per system. We work around this with `oemer_prep.py`,
  which paints the piano-LH staves white before oemer sees the
  page.

## Where reviewing pays off

For a 30-song book, expect ~10–40 flagged measures per song.
Singing through each `review.html` and noting fixes takes 5–10
minutes per song. That review time is also training data for the
classifier in `docs/classifier.md` — every chord correction you
make today reduces the residual chord miss rate in the next batch.
