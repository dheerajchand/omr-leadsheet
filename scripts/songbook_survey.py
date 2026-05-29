#!/usr/bin/env python3
"""Score every song's current state.

For each <song>/<song> - lead.final.musicxml under the songbook's
lead_sheets/ directory, report:
  - lyric-stat summary (counts of v1/v2 lyrics)
  - chord-stat summary (chord-symbol counts)
  - measures with naked notes (a note with no v1 lyric) -- a heuristic
    proxy for "place where the published has a syllable we lost"
  - whether a truth file exists for the song, and if so the
    truth_compare result

Use this output to triage which songs need attention.

Usage: songbook_survey.py <songbook_root>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from music21 import converter, harmony, note as m21note


def score_song(final_path: Path) -> dict:
    sc = converter.parse(str(final_path))
    p = sc.parts[0]
    measures = list(p.getElementsByClass("Measure"))
    n_notes = 0
    n_naked = 0
    n_chord = 0
    v1_lyrics = 0
    v2_lyrics = 0
    for m in measures:
        for n in m.recurse().notes:
            if isinstance(n, harmony.ChordSymbol):
                n_chord += 1
                continue
            if not isinstance(n, m21note.Note):
                continue
            n_notes += 1
            v1s = [lyr for lyr in n.lyrics if (lyr.number or 1) == 1]
            v2s = [lyr for lyr in n.lyrics if (lyr.number or 1) == 2]
            v1_lyrics += len(v1s)
            v2_lyrics += len(v2s)
            if not v1s:
                n_naked += 1
    return {
        "n_measures": len(measures),
        "n_notes": n_notes,
        "n_naked": n_naked,
        "n_chord": n_chord,
        "v1_lyrics": v1_lyrics,
        "v2_lyrics": v2_lyrics,
    }


def truth_file_for(song_name: str, truth_root: Path) -> Path | None:
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "_", song_name).strip("_").lower()
    cand = truth_root / f"{slug}.json"
    if cand.exists():
        return cand
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    lead_root = root / "lead_sheets"
    if not lead_root.is_dir():
        print(f"error: not a dir: {lead_root}", file=sys.stderr)
        return 2
    truth_root = (
        Path(__file__).resolve().parents[1] / "data" / "song_truth"
    )
    rows = []
    for song_dir in sorted(lead_root.iterdir()):
        if not song_dir.is_dir():
            continue
        final = song_dir / f"{song_dir.name} - lead.final.musicxml"
        if not final.is_file():
            rows.append({"song": song_dir.name, "status": "NO FINAL"})
            continue
        try:
            stats = score_song(final)
        except Exception as exc:
            rows.append({"song": song_dir.name, "status": f"PARSE ERR: {exc}"})
            continue
        has_truth = truth_file_for(song_dir.name, truth_root) is not None
        stats["song"] = song_dir.name
        stats["truth"] = "yes" if has_truth else "no"
        rows.append(stats)

    # Sort by naked-note count desc (most naked = most likely broken)
    rows_sorted = sorted(
        rows,
        key=lambda r: -(r.get("n_naked", 0))
        if isinstance(r.get("n_naked"), int)
        else 0,
    )
    print(f"{'Song':<55} {'measures':>9} {'notes':>6} {'naked':>6} "
          f"{'naked%':>7} {'chords':>7} {'truth':>6}")
    print("-" * 100)
    for r in rows_sorted:
        if "status" in r and r["status"] != "":
            print(f"{r['song']:<55} -- {r['status']}")
            continue
        name = r["song"][:54]
        nm = r["n_measures"]
        nn = r["n_notes"]
        nk = r["n_naked"]
        nkp = (100.0 * nk / nn) if nn else 0.0
        nc = r["n_chord"]
        tr = r["truth"]
        print(f"{name:<55} {nm:>9} {nn:>6} {nk:>6} {nkp:>6.1f}% "
              f"{nc:>7} {tr:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
