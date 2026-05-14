#!/usr/bin/env python3
"""Extract a labeled chord-symbol dataset from Audiveris .omr files.

For every <chord-name value="..."> that Audiveris parsed (value is not
None), crop the glyph region from the sheet's BINARY.png and save it
to disk under dataset/<value>/<hash>.png. The chord 'value' attribute
is the label.

Skips entries where value is None (those are detected-but-unread chord
glyphs you may want to feed through chord_ocr_recovery instead, then
hand-label).

Usage:
  dataset_extract.py <omr-dir> <out-dir>

Example:
  python dataset_extract.py \\
      ~/Desktop/MySongbook/MusicXML \\
      ~/code/omr-leadsheet/dataset

Then to inspect class counts:
  ls dataset/ | head -20
  for d in dataset/*; do printf '%-15s %d\\n' "$(basename $d)" "$(ls $d | wc -l)"; done | sort -k2 -n
"""
from __future__ import annotations
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def safe_filename(value: str) -> str:
    """Make a chord value safe to use as a directory name."""
    return (
        value.replace("/", "_slash_")
        .replace("#", "sharp")
        .replace("+", "aug")
        .replace(" ", "")
        .replace(":", "")
    )


def crop_chord(bin_png: str, x: int, y: int, w: int, h: int, out_path: str) -> bool:
    pad_x = max(10, int(w * 0.3))
    pad_y = max(10, int(h * 0.4))
    geom = (
        f"{int(w + 2 * pad_x)}x{int(h + 2 * pad_y)}"
        f"+{int(x - pad_x)}+{int(y - pad_y)}"
    )
    r = subprocess.run(
        ["magick", bin_png, "-crop", geom, "+repage", out_path],
        capture_output=True, check=False,
    )
    return r.returncode == 0 and os.path.exists(out_path)


def process_omr(omr_path: str, out_dir: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_dirs = sorted(
            d for d in os.listdir(td)
            if os.path.isdir(os.path.join(td, d)) and d.startswith("sheet#")
        )
        for sd in sheet_dirs:
            xml_path = os.path.join(td, sd, f"{sd}.xml")
            bin_png = os.path.join(td, sd, "BINARY.png")
            if not (os.path.exists(xml_path) and os.path.exists(bin_png)):
                continue
            root = ET.parse(xml_path).getroot()
            for c in root.iter("chord-name"):
                # Skip relation-tag chord-names (no value, no bounds)
                value = c.get("value")
                bounds = c.find("bounds")
                if value is None or bounds is None:
                    continue
                value = value.strip()
                if not value:
                    continue
                try:
                    x = int(float(bounds.get("x")))
                    y = int(float(bounds.get("y")))
                    w = int(float(bounds.get("w")))
                    h = int(float(bounds.get("h")))
                except (TypeError, ValueError):
                    continue
                cls_dir = os.path.join(out_dir, safe_filename(value))
                os.makedirs(cls_dir, exist_ok=True)
                # Deterministic filename per (omr, position) so re-runs don't
                # duplicate crops
                key = f"{os.path.basename(omr_path)}:{sd}:{x},{y}".encode()
                h_id = hashlib.sha1(key).hexdigest()[:12]
                out_path = os.path.join(cls_dir, f"{h_id}.png")
                if os.path.exists(out_path):
                    continue
                if crop_chord(bin_png, x, y, w, h, out_path):
                    counts[value] = counts.get(value, 0) + 1
    return counts


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: dataset_extract.py <omr-dir> <out-dir>", file=sys.stderr)
        sys.exit(2)
    omr_dir = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    total: dict[str, int] = {}
    omr_files = sorted(
        os.path.join(omr_dir, f) for f in os.listdir(omr_dir) if f.endswith(".omr")
    )
    for omr in omr_files:
        print(f"  {os.path.basename(omr)}")
        local = process_omr(omr, out_dir)
        for k, v in local.items():
            total[k] = total.get(k, 0) + v
    print(f"\nExtracted from {len(omr_files)} .omr files. Class counts:")
    for k in sorted(total, key=lambda x: -total[x]):
        print(f"  {k:<10}  {total[k]}")


if __name__ == "__main__":
    main()
