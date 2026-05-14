#!/usr/bin/env python3
"""Flag measures that likely have OMR errors, for manual review.

A "suspicious" measure is one that suggests an OMR problem without being
wrong per se. The tool reports these so that a user reviewing a batch of
30+ songs can focus their attention instead of scanning every measure.

Current heuristics:
  * **All-rests + chord symbols** - the measure has no pitched notes but
    has one or more chord symbols. Almost always a missed melody note
    (e.g., a whole note misread as a rest).
  * **Unexpectedly short measure** - measure duration differs from the
    prevailing time signature's expected duration. Can mean tuplet errors
    or rhythm miscounts.
  * **No lyric syllables in a lyric-heavy song** - a measure that has
    notes but no lyrics, when the surrounding measures do. Can mean the
    OCR failed on a line of text.

Usage: suspicious_measures.py <musicxml> [<musicxml> ...]
"""
from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
from music21 import converter, note, harmony, meter


@dataclass
class Finding:
    measure: int
    reason: str
    detail: str


def analyse(path: str) -> list[Finding]:
    score = converter.parse(path)
    # Pick the vocal part
    best_idx, best_count = 0, -1
    for i, p in enumerate(score.parts):
        c = sum(1 for n in p.recurse().notes if isinstance(n, note.Note) and n.lyrics)
        if c > best_count:
            best_idx, best_count = i, c
    part = score.parts[best_idx]

    out: list[Finding] = []

    # Prevailing duration = most common measure.duration.quarterLength
    from collections import Counter
    dur_counter: Counter = Counter()
    for m in part.getElementsByClass("Measure"):
        dur_counter[float(m.duration.quarterLength)] += 1
    prevailing_dur = dur_counter.most_common(1)[0][0] if dur_counter else 4.0

    # Per-measure lyric count
    lyric_counts: dict[int, int] = {}
    for m in part.getElementsByClass("Measure"):
        c = 0
        for n in m.recurse().notes:
            if isinstance(n, note.Note) and n.lyrics:
                c += len(n.lyrics)
        lyric_counts[m.number] = c

    # Are there lyrics overall? If yes, measures with notes-but-no-lyrics are suspicious
    total_lyrics = sum(lyric_counts.values())
    has_lyrics_overall = total_lyrics > 10

    for m in part.getElementsByClass("Measure"):
        notes = [n for n in m.recurse().notes if isinstance(n, note.Note)]
        chords = list(m.recurse().getElementsByClass(harmony.ChordSymbol))
        dur = float(m.duration.quarterLength)

        # 1. All-rests + chord symbols
        if not notes and chords:
            chord_figs = ", ".join(cs.figure for cs in chords)
            out.append(Finding(
                measure=m.number,
                reason="all_rests_with_chords",
                detail=f"no melody notes; chords present: [{chord_figs}]",
            ))

        # 2. Unexpectedly short/long measure
        if abs(dur - prevailing_dur) > 0.01 and dur > 0:
            out.append(Finding(
                measure=m.number,
                reason="duration_mismatch",
                detail=f"duration={dur:.3f}, prevailing={prevailing_dur:.3f}",
            ))

        # 3. Notes without lyrics in a lyric-heavy song (check if neighbors have lyrics)
        if has_lyrics_overall and notes and lyric_counts.get(m.number, 0) == 0:
            prev_ly = lyric_counts.get(m.number - 1, 0)
            next_ly = lyric_counts.get(m.number + 1, 0)
            if prev_ly > 0 and next_ly > 0:
                out.append(Finding(
                    measure=m.number,
                    reason="missing_lyrics",
                    detail=f"{len(notes)} notes, 0 lyrics, neighbours have lyrics",
                ))

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--markdown", action="store_true", help="Emit markdown")
    args = ap.parse_args()

    for path in args.files:
        findings = analyse(path)
        if args.markdown:
            title = path.split("/")[-1]
            print(f"## {title}")
            if not findings:
                print("_No suspicious measures._\n")
                continue
            print()
            print("| measure | reason | detail |")
            print("|---:|---|---|")
            for f in findings:
                print(f"| {f.measure} | {f.reason} | {f.detail} |")
            print()
        else:
            print(f"=== {path} ===")
            if not findings:
                print("  (no suspicious measures)")
                continue
            for f in findings:
                print(f"  m{f.measure} [{f.reason}]: {f.detail}")


if __name__ == "__main__":
    main()
