#!/usr/bin/env python3
"""Emit a starter truth file for a song based on its current
pipeline output. The human then refines it by editing measures
against the published score.

The starter file:
  - Encodes the song's existing per-measure chord list and v1 lyric
    list as if they were ground truth. The truth-overlay will apply
    them losslessly so re-running with this file produces the same
    output as without it.
  - Includes the comment field "STARTER -- edit each measure against
    the published score" so the file is clearly marked as not yet
    verified ground truth.

Workflow:
  1. truth_init.py <song.musicxml> <song_title>   # emit starter
  2. Edit data/song_truth/<slug>.json against the published score
  3. Re-run the pipeline (truth overlay picks up the file automatically)
  4. scripts/truth_compare.py verifies the result

Usage:
    truth_init.py <final.musicxml> <song_title>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from music21 import converter, harmony, note as m21note


def _slug(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").lower()


def extract_truth_template(final_path: Path) -> dict:
    sc = converter.parse(str(final_path))
    p = sc.parts[0]
    measures = {}
    for m in p.getElementsByClass("Measure"):
        mn = str(int(m.number) if m.number else 0)
        chords = [
            str(c.figure)
            for c in m.recurse().getElementsByClass(harmony.ChordSymbol)
        ]
        lyrics_v1 = []
        for n in m.recurse().notes:
            if not isinstance(n, m21note.Note):
                continue
            for lyr in n.lyrics:
                if (lyr.number or 1) == 1:
                    lyrics_v1.append(lyr.text)
        if chords or lyrics_v1:
            measures[mn] = {
                "lyrics_v1": lyrics_v1,
                "chords": chords,
            }
    return measures


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    final_path = Path(sys.argv[1])
    song_title = sys.argv[2]
    if not final_path.is_file():
        print(f"error: not a file: {final_path}", file=sys.stderr)
        return 2

    measures = extract_truth_template(final_path)
    truth = {
        "song": song_title,
        "key_fifths": None,
        "time_signature": None,
        "comment": (
            "STARTER -- edit each measure against the published score. "
            "Replace incorrect lyric tokens and chord figures. Add "
            "merge_measures entries when Audiveris over-segmented a "
            "measure. Delete measures that don't need correction."
        ),
        "measures": measures,
    }

    truth_root = Path(__file__).resolve().parents[1] / "data" / "song_truth"
    truth_root.mkdir(parents=True, exist_ok=True)
    out_path = truth_root / f"{_slug(song_title)}.json"
    if out_path.exists():
        print(f"refusing to overwrite existing truth file: {out_path}",
              file=sys.stderr)
        return 1
    with open(out_path, "w") as f:
        json.dump(truth, f, indent=2)
    print(f"starter truth written: {out_path}")
    print(f"  {len(measures)} measure(s) templated")
    print("Edit this file against the published score, then re-run the pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
