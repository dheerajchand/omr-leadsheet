#!/usr/bin/env python3
"""Render wider context crops alongside each tight glyph crop.

The labeling UI shows a tight crop (good for the classifier) but if you
can't tell what the glyph is from that alone, a wider view of the
surrounding score helps. This script reads the existing labels.csv,
parses the position out of each filename, and writes a 500x300 crop
centered on that point into <labeling-dir>/context/.

Usage: dataset_context_crops.py <labeling-dir> <omr-dir>
"""
from __future__ import annotations
import csv
import os
import re
import subprocess
import sys
import tempfile
import zipfile


# filename format: <safe_src>_sheet<N>(_art)?_<x>_<y>.png
FN_RE = re.compile(r"^(.+)_sheet(\d+)(?:_art)?_(\d+)_(\d+)\.png$")

CONTEXT_W = 500
CONTEXT_H = 300


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: dataset_context_crops.py <labeling-dir> <omr-dir>", file=sys.stderr)
        sys.exit(2)
    base, omr_dir = sys.argv[1], sys.argv[2]
    ctx_dir = os.path.join(base, "context")
    os.makedirs(ctx_dir, exist_ok=True)
    csv_path = os.path.join(base, "labels.csv")
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    # Group by source so we extract each .omr once
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        # The position info we need is in the filename
        m = FN_RE.match(r["filename"])
        if not m:
            continue
        r["_sheet"] = int(m.group(2))
        r["_x"] = int(m.group(3))
        r["_y"] = int(m.group(4))
        by_source.setdefault(r["source"], []).append(r)

    n_done = 0
    for src, items in sorted(by_source.items()):
        omr_path = os.path.join(omr_dir, f"{src}.omr")
        if not os.path.exists(omr_path):
            print(f"  skipping {src}: .omr not found")
            continue
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(omr_path) as z:
                z.extractall(td)
            for r in items:
                sheet_dir = os.path.join(td, f"sheet#{r['_sheet']}")
                bin_png = os.path.join(sheet_dir, "BINARY.png")
                if not os.path.exists(bin_png):
                    continue
                out_path = os.path.join(ctx_dir, r["filename"])
                if os.path.exists(out_path):
                    n_done += 1
                    continue
                x0 = max(0, r["_x"] - CONTEXT_W // 2)
                y0 = max(0, r["_y"] - CONTEXT_H // 2)
                subprocess.run(
                    ["magick", bin_png, "-crop",
                     f"{CONTEXT_W}x{CONTEXT_H}+{x0}+{y0}", "+repage", out_path],
                    capture_output=True, check=False,
                    timeout=60,
                )
                if os.path.exists(out_path):
                    n_done += 1
        print(f"  {src}: {len(items)} contexts")
    print(f"\nWrote {n_done} context crops → {ctx_dir}")


if __name__ == "__main__":
    main()
