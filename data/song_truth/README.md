# Per-Measure Song Truth

A small JSON-per-song schema for declaring the *published* per-measure
chord progression, key/time signature, and lyric expectations.

Used by `scripts/truth_compare.py` to score our pipeline output against
the published score. The intent is a regression-detection tool, not a
universal ground-truth corpus — partial coverage is fine; measures not
listed in a truth file are not compared.

## Schema

```json
{
  "song": "13 - Let's Call The Whole Thing Off",
  "key_fifths": 2,
  "time_signature": "2/2",
  "comment": "Free-form notes about transcription decisions",
  "measures": {
    "9": {
      "lyrics_v1": ["Good-ness", "knows", "what", "the", "end", "will", "be,"],
      "chords": ["D", "B7", "Em", "D", "A7"]
    },
    "10": {
      "lyrics_v1": ["Oh,", "I"],
      "chords": ["D"]
    }
  }
}
```

Field semantics:
- `key_fifths` — `<key><fifths>N</fifths></key>` value, positive = sharps
- `time_signature` — `<beats>/<beat-type>`
- `measures[N].lyrics_v1` — verse-1 syllable list in note order. Hyphenated
  syllables are kept as separate tokens (e.g. `Good-ness` = one node, but
  if Audiveris split it into `Good` + `ness` we'd record that).
- `measures[N].chords` — chord-symbol list in beat order across the
  measure. Chord-symbol notation follows the published score (e.g.
  `C#+` for C-sharp augmented, `F#9⁷` rendered as `F#9/7` per
  MuseScore's stacked-numeral convention).

Measures not listed are skipped during comparison.
