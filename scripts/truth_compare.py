#!/usr/bin/env python3
"""Compare a generated lead-sheet MusicXML against a per-measure truth
file under data/song_truth/. Reports per-measure mismatches and a
single-line summary score.

Usage:
    truth_compare.py <generated.musicxml> <truth.json>

The truth schema is documented in data/song_truth/README.md.

Exit code 0 if every covered measure is a perfect match, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from music21 import converter, harmony, note


def load_truth(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_actual(score_path: str) -> dict[int, dict]:
    """Pull per-measure chord lists + v1 lyrics from a generated
    MusicXML. Returns {measure_number: {"chords": [...], "lyrics_v1": [...]}}."""
    sc = converter.parse(score_path)
    out: dict[int, dict] = {}
    p = sc.parts[0]
    for m in p.getElementsByClass("Measure"):
        mn = int(m.number) if m.number else 0
        chords = [
            str(c.figure)
            for c in m.recurse().getElementsByClass(harmony.ChordSymbol)
        ]
        lyrs = []
        for n in m.recurse().notes:
            if not isinstance(n, note.Note):
                continue
            for lyr in n.lyrics:
                if (lyr.number or 1) == 1:
                    lyrs.append(lyr.text)
        out[mn] = {"chords": chords, "lyrics_v1": lyrs}
    return out


def _normalize_chord(s: str) -> str:
    """Lowercase + strip whitespace + remove some music21 quirks so
    'C#+' compares equal to 'C#+' regardless of source."""
    return (s or "").strip().lower().replace(" ", "")


def _normalize_lyric(s: str) -> str:
    return (s or "").strip().lower()


def compare(truth: dict, actual: dict[int, dict]) -> dict:
    """Per-measure comparison. Returns
    {match: bool, per_measure: {n: {chord_diff, lyric_diff}}}."""
    per_measure: dict[int, dict] = {}
    all_match = True
    for mnum_s, expected in truth["measures"].items():
        mnum = int(mnum_s)
        got = actual.get(mnum, {"chords": [], "lyrics_v1": []})
        exp_chords = [_normalize_chord(c) for c in expected.get("chords", [])]
        got_chords = [_normalize_chord(c) for c in got.get("chords", [])]
        chord_match = exp_chords == got_chords
        exp_lyrics = [_normalize_lyric(l) for l in expected.get("lyrics_v1", [])]
        got_lyrics = [_normalize_lyric(l) for l in got.get("lyrics_v1", [])]
        lyric_match = exp_lyrics == got_lyrics
        per_measure[mnum] = {
            "chord_match": chord_match,
            "lyric_match": lyric_match,
            "expected_chords": expected.get("chords", []),
            "got_chords": got.get("chords", []),
            "expected_lyrics": expected.get("lyrics_v1", []),
            "got_lyrics": got.get("lyrics_v1", []),
        }
        if not (chord_match and lyric_match):
            all_match = False
    return {"all_match": all_match, "per_measure": per_measure}


def render_report(result: dict) -> str:
    lines = []
    total = len(result["per_measure"])
    chord_ok = sum(1 for m in result["per_measure"].values() if m["chord_match"])
    lyric_ok = sum(1 for m in result["per_measure"].values() if m["lyric_match"])
    lines.append(f"Coverage: {total} measure(s)")
    lines.append(f"Chords:   {chord_ok}/{total} match")
    lines.append(f"Lyrics:   {lyric_ok}/{total} match")
    lines.append("")
    for mnum in sorted(result["per_measure"]):
        m = result["per_measure"][mnum]
        ok = m["chord_match"] and m["lyric_match"]
        marker = "OK" if ok else "MISS"
        lines.append(f"m{mnum:>3} [{marker}]")
        if not m["chord_match"]:
            lines.append(f"     chords  expected={m['expected_chords']}")
            lines.append(f"             got     ={m['got_chords']}")
        if not m["lyric_match"]:
            lines.append(f"     lyrics  expected={m['expected_lyrics']}")
            lines.append(f"             got     ={m['got_lyrics']}")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    score_path, truth_path = sys.argv[1], sys.argv[2]
    if not Path(score_path).is_file():
        print(f"error: not a file: {score_path}", file=sys.stderr)
        return 2
    if not Path(truth_path).is_file():
        print(f"error: not a file: {truth_path}", file=sys.stderr)
        return 2
    truth = load_truth(truth_path)
    actual = extract_actual(score_path)
    result = compare(truth, actual)
    print(render_report(result))
    return 0 if result["all_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
