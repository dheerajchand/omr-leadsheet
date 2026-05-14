#!/usr/bin/env python3
"""Generate an overall review summary across all song folders.

Reads each per-song <dir>/<Song>.review.md and aggregates the suspicious
measure counts into a single markdown report. Useful to see at a glance
which songs need the most manual touch-up.

Usage: summary.py <leadsheets-root> <output.md>
"""
from __future__ import annotations
import os
import re
import sys
from collections import Counter


def parse_review(path: str) -> Counter:
    counts: Counter = Counter()
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r"\|\s*\d+\s*\|\s*([a-z_]+)\s*\|", line)
                if m:
                    counts[m.group(1)] += 1
    except FileNotFoundError:
        pass
    return counts


def main() -> None:
    root = sys.argv[1]
    out_path = sys.argv[2]

    rows: list[tuple[str, Counter, bool]] = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        review = os.path.join(folder, f"{name}.review.md")
        mscz = os.path.join(folder, f"{name}.mscz")
        rows.append((name, parse_review(review), os.path.exists(mscz)))

    all_reasons = sorted({r for _, c, _ in rows for r in c})

    lines = ["# Gershwin Songbook - Review Summary", ""]
    lines.append(f"Total songs: **{len(rows)}**. "
                 f".mscz present: **{sum(1 for _, _, ok in rows if ok)}**.")
    lines.append("")
    header = "| Song | .mscz | " + " | ".join(all_reasons) + " | Total flagged |"
    sep = "|---|:-:|" + "|".join([":-:"] * len(all_reasons)) + "|:-:|"
    lines.append(header)
    lines.append(sep)
    totals: Counter = Counter()
    for name, counts, ok in rows:
        row = [f"[{name}]({name}/{name}.mscz)",
               "✓" if ok else "✗"]
        for r in all_reasons:
            row.append(str(counts.get(r, 0)))
            totals[r] += counts.get(r, 0)
        row.append(str(sum(counts.values())))
        lines.append("| " + " | ".join(row) + " |")
    # Totals row
    lines.append("| **totals** | | " + " | ".join(str(totals[r]) for r in all_reasons)
                 + " | " + str(sum(totals.values())) + " |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Legend")
    lines.append("")
    descriptions = {
        "all_rests_with_chords":
            "Measure has chord symbols but no melody notes. "
            "Almost always a missed note (often a whole note).",
        "duration_mismatch":
            "Measure duration doesn't match the prevailing time signature. "
            "Tuplet or rhythm-count error from Audiveris.",
        "missing_lyrics":
            "Measure has notes but no lyrics, while adjacent measures do. "
            "Suggests an OCR miss on a line of lyric text.",
    }
    for r in all_reasons:
        lines.append(f"- **{r}** - {descriptions.get(r, '(no description)')}")
    lines.append("")
    lines.append("## Per-song reviews")
    lines.append("")
    for name, _, _ in rows:
        lines.append(f"- [{name}]({name}/{name}.review.md)")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
