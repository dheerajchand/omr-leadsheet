# Unfixable Issues Report — Song Truth Overlays

Truth overlays can only redistribute lyrics across notes the pipeline already
detected.  When the pipeline read a note as a rest (or missed it entirely), there
is no `<note>` element to attach a lyric to, and the truth overlay cannot help.

This report catalogs every measure where published lyrics exceed available notes.

---

## Fully Unfixable (lost syllables, no notes to attach them to)

| Song | Measure | Published text | Issue |
|------|---------|---------------|-------|
| 01 - The Real American Folk Song | m6 | "The Ne-a-pol-i-tan" | Only 2 notes; "a-pol-i-tan" (4 syllables) lost to 3 rest-detected notes |
| 01 - The Real American Folk Song | m14 | "folk songs plain-tive and" | Only 2 notes; "plain-tive and" (3 syllables) lost to 2 rests |
| 01 - The Real American Folk Song | m17 | "-cu-liar" (from "pe-cu-liar") | Only 1 note; "-liar" lost to 4 rests |
| 01 - The Real American Folk Song | m18 | "pe-cu-liar way." | "liar" from preceding word lost — no notes in m17 |
| 01 - The Real American Folk Song | m41 | "syn-co-pat-ed sort of me-ter...strain." | Only 1 note + 3 rests; "-pat-ed sort of me-ter,...strain." lost |
| 02 - Bess You Is My Woman | m5 | "you mus' laugh an' sing an' dance..." | Only 2 notes + 6 rests; 6 syllables lost |
| 15 - Shall We Dance | m7 | "Blues?" | 0 notes detected (whole note missed); entire lyric lost |
| 16 - They All Laughed | m18 | "man-y, man-y times the" | Pipeline lost a note (triplet); 6 syllables on 5 notes |
| 27 - They Can't Take That Away From Me | m19 | (piano interlude) | 0 notes, 7 rests — no vocal part |
| 27 - They Can't Take That Away From Me | m20 | (piano interlude) | 0 notes, 1 rest — no vocal part |
| 27 - They Can't Take That Away From Me | m43 | (ending area) | 0 notes, 7 rests — no vocal notes |
| 27 - They Can't Take That Away From Me | m44 | (ending area) | 0 notes, 1 rest — no vocal notes |
| 27 - They Can't Take That Away From Me | m52 | (1st ending) | 0 notes, 3 rests — no vocal notes |

**Total: 13 fully unfixable measures across 5 songs.**

---

## Partial Fits (syllable-count mismatch resolved by merging or truncating)

These measures have fewer notes than published syllables.  The truth file provides
as many syllables as there are notes, merging hyphenated continuations onto the
last available note (e.g., `"gic-'ly"` or `"all-time."`) or truncating the tail.

| Song | Measure | Notes | Published syllables | Resolution |
|------|---------|-------|--------------------:|------------|
| 01 - The Real American Folk Song | m9 | 3 | 2 | Held note (extra note, not short) |
| 11 - Slap That Bass | m38 | 5 | 6 | Merged "har-mon-ic" → "mon-ic!" on last note |
| 15 - Shall We Dance | m25 | 2 | 3 | "on" truncated |
| 15 - Shall We Dance | m29 | 2 | 3 | "on" truncated |
| 15 - Shall We Dance | m45 | 2 | 3 | "al-so" merged on last note |
| 30 - All The Livelong Day | m4 | 5 | 2 | Held notes (extra notes, not short) |
| 30 - All The Livelong Day | m10 | 6 | 4 | Held notes |
| 30 - All The Livelong Day | m24 | 4 | 3 | Held note |
| 30 - All The Livelong Day | m31 | 5 | 6 | Merged "gic-'ly" on last note |
| 30 - All The Livelong Day | m36 | 5 | 4 | Held note |
| 30 - All The Livelong Day | m41 | 5 | 6 | Merged "all-time." on last note |

**Total: 11 partial-fit measures.** All resolved in truth files — no data loss.

---

## Summary

- **29 songs** have truth overlay files (song #14 is a piano solo, no lyrics).
- **13 measures** across 5 songs are fully unfixable (pipeline lost the notes).
- **11 measures** have syllable/note mismatches resolved by merging in the truth file.
- All other corrected measures (400+) are fully fixable via truth overlay.

### Potential remediation for unfixable measures

1. **Re-run Audiveris** on the affected pages with tuned parameters to recover missed notes.
2. **Manual MusicXML edits** — insert `<note>` elements where the pipeline detected rests.
3. **Post-overlay text injection** — a new pipeline stage that inserts lyrics into the
   rendered output even when no `<note>` exists, using measure timing from the truth file.
