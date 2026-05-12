#!/usr/bin/env python3
"""Render summary charts from the per-song review.md files.

Emits:
  * <root>/_summary.png      — stacked horizontal bar per song, one colour
                                per flag category
  * <root>/_totals.png        — simple bar chart of total flags by category

Usage: charts.py <leadsheets-root>
"""
from __future__ import annotations
import os
import re
import sys
from collections import Counter
import matplotlib.pyplot as plt


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
    rows: list[tuple[str, Counter]] = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        review = os.path.join(folder, f"{name}.review.md")
        rows.append((name, parse_review(review)))
    if not rows:
        print("no review files found", file=sys.stderr)
        return

    categories = sorted({k for _, c in rows for k in c})
    palette = {
        "all_rests_with_chords": "#c0392b",  # red — likely missed notes
        "duration_mismatch":     "#f39c12",  # amber — rhythm warnings
        "missing_lyrics":        "#2980b9",  # blue — OCR misses
    }
    colours = [palette.get(c, "#888") for c in categories]

    # --- per-song stacked bar ---
    fig, ax = plt.subplots(figsize=(10, max(6, len(rows) * 0.28)))
    # Short names so the axis doesn't explode
    labels = [re.sub(r"^\d+\s*-\s*", "", n) for n, _ in rows]
    labels = [l[:40] + ("…" if len(l) > 40 else "") for l in labels]
    y = range(len(rows))
    left = [0] * len(rows)
    for cat, colour in zip(categories, colours):
        values = [c.get(cat, 0) for _, c in rows]
        ax.barh(y, values, left=left, color=colour, label=cat, edgecolor="white", linewidth=0.5)
        left = [l + v for l, v in zip(left, values)]
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Flagged measures")
    ax.set_title("Per-song suspicious-measure counts")
    ax.legend(loc="lower right", fontsize=8)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out = os.path.join(root, "_summary.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")

    # --- totals bar ---
    totals = Counter()
    for _, c in rows:
        totals.update(c)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(categories, [totals[c] for c in categories], color=colours)
    for i, c in enumerate(categories):
        ax.text(i, totals[c], str(totals[c]), ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("Total flagged measures (all 30 songs)")
    ax.set_title("Issues by category")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out = os.path.join(root, "_totals.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
