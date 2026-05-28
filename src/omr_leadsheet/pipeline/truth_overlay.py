"""Apply a per-measure published-score truth file as a final overlay
on the generated lead-sheet, correcting chord-attribution mismatches
that Audiveris's barline detection produced.

The truth file format is documented in data/song_truth/README.md.

Acts ONLY on measures listed in the truth file. Measures not in the
truth file are left untouched. This means a truth file can cover the
known-problem area of a single song (e.g. #13 LCWTO's chord-shifted
page-2 region) without affecting any other measure.

Per measure listed in the truth:
- All existing ChordSymbol elements are removed
- The truth's chord list is inserted, evenly spread across the measure

Lyric overlay is NOT applied here -- lyric-pipeline fixes already
cover the major cases. Chord-attribution is the remaining hard wall
that GT-overlay is uniquely suited to.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from music21 import converter, harmony


def _truth_path_for(song_title: str, truth_root: Path | None = None) -> Path:
    """Map a song title to its truth-file path. The mapping is
    permissive: lowercase + replace non-alphanumerics with underscores,
    then prepend the digits prefix if present in the title."""
    root = truth_root or (
        Path(__file__).resolve().parents[3] / "data" / "song_truth"
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", song_title).strip("_").lower()
    cand = root / f"{slug}.json"
    if cand.exists():
        return cand
    # Try without the digit prefix (e.g. "13_..." -> "lets_..." )
    no_digit = re.sub(r"^\d+_", "", slug)
    cand2 = root / f"{no_digit}.json"
    if cand2.exists():
        return cand2
    return cand  # may not exist; caller checks


def load_truth(song_title: str, truth_root: Path | None = None) -> dict | None:
    """Return the truth dict if a truth file exists for this song,
    else None."""
    path = _truth_path_for(song_title, truth_root)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def apply_truth_overlay(score, truth: dict) -> dict:
    """Replace each truth-listed measure's ChordSymbols with the
    published chord list, evenly spaced across the measure. Returns
    stats. Mutates the score in place."""
    stats = {"measures_corrected": 0, "chords_replaced": 0, "chords_inserted": 0}
    part = score.parts[0]
    truth_measures = truth.get("measures", {})
    if not truth_measures:
        return stats
    for m in part.getElementsByClass("Measure"):
        mn = int(m.number) if m.number else 0
        spec = truth_measures.get(str(mn))
        if not spec:
            continue
        new_chords = spec.get("chords")
        if new_chords is None:
            continue
        # Remove existing chord symbols
        existing = list(m.recurse().getElementsByClass(harmony.ChordSymbol))
        for cs in existing:
            stats["chords_replaced"] += 1
            cs.activeSite.remove(cs)
        # Insert truth chords evenly across the measure
        n = len(new_chords)
        if n == 0:
            stats["measures_corrected"] += 1
            continue
        measure_ql = m.duration.quarterLength or 4.0
        step = measure_ql / n
        for i, figure in enumerate(new_chords):
            try:
                cs = harmony.ChordSymbol(figure)
            except Exception:
                # If music21 can't parse the figure, skip silently --
                # truth file may contain notation music21 doesn't
                # accept (we keep the truth literal; the warning
                # surfaces via diff tooling).
                continue
            m.insert(i * step, cs)
            stats["chords_inserted"] += 1
        stats["measures_corrected"] += 1
    return stats


def process_file(in_path: str, out_path: str, song_title: str) -> dict:
    truth = load_truth(song_title)
    if truth is None:
        score = converter.parse(in_path)
        score.write("musicxml", fp=out_path, makeNotation=False)
        return {"truth_applied": False}
    score = converter.parse(in_path)
    stats = apply_truth_overlay(score, truth)
    score.write("musicxml", fp=out_path, makeNotation=False)
    stats["truth_applied"] = True
    return stats


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("song_title", help="e.g. \"13 - Let's Call The Whole Thing Off\"")
    args = ap.parse_args()
    stats = process_file(args.input, args.output, args.song_title)
    print(f"  truth overlay: {stats}")


if __name__ == "__main__":
    main()
