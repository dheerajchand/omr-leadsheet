#!/usr/bin/env python3
"""Recover chord symbols whose text Audiveris couldn't OCR.

When Audiveris detects a chord-name glyph but can't read its text, it
stores the entry in .omr with value=None. This tool:

  1. Extracts each sheet's BINARY.png from the .omr zip (pixel-exact
     to the bounds Audiveris recorded).
  2. For each chord-name with value=None, crops a small region around
     the recorded bounds (with padding) and runs tesseract configured
     for short chord-style text (A-G, #, b, 0-9, m, M, a, j, 7, 9, +,
 - ).
  3. Returns the recovered chord values as a list of (sheet, measure,
     x, value) records, with a confidence indicator.

Usage (standalone):
  chord_ocr_recovery.py <path-to-.omr>

Integration: the main pipeline's chord_diff.py can import
`recover_missing_chord_values` and merge the recovered entries with
Audiveris' parsed chord-names before insertion.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


CHORD_CHARS = "ABCDEFGabm#b♯♭+-0123456789MajmajinMsus"
TESSERACT_CONFIG = (
    "--psm 7 "  # single line
    f"-c tessedit_char_whitelist={CHORD_CHARS}"
)


@dataclass
class RecoveredChord:
    sheet: int
    staff: int
    x: float
    y: float
    value: str
    ocr_raw: str  # what tesseract actually produced before cleanup


def _clean_chord(text: str) -> str | None:
    """Normalise a raw OCR string into a music21-friendly chord figure.
    Returns None if it doesn't look like a chord."""
    t = re.sub(r"\s+", "", text.strip())
    if not t:
        return None
    # Must start with a root note A-G
    if not re.match(r"[A-G]", t):
        return None
    # Replace unicode sharp/flat with ascii
    t = t.replace("♯", "#").replace("♭", "b")
    # Common OCR confusions: 0→o (but chords rarely have o; leave), l→1, I→1
    # Limit length - chord figures over 10 chars are suspicious
    if len(t) > 10:
        t = t[:10]
    return t


def recover_missing_chord_values(omr_path: str) -> list[RecoveredChord]:
    out: list[RecoveredChord] = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_dirs = sorted(
            d for d in os.listdir(td)
            if os.path.isdir(os.path.join(td, d)) and d.startswith("sheet#")
        )
        for sd in sheet_dirs:
            sheet_idx = int(sd.split("#")[1])
            xml_path = os.path.join(td, sd, f"{sd}.xml")
            bin_png = os.path.join(td, sd, "BINARY.png")
            if not (os.path.exists(xml_path) and os.path.exists(bin_png)):
                continue
            root = ET.parse(xml_path).getroot()
            for c in root.iter("chord-name"):
                if c.get("value") is not None:
                    continue
                sf = c.get("staff")
                bounds = c.find("bounds")
                if sf is None or bounds is None:
                    continue
                x = float(bounds.get("x"))
                y = float(bounds.get("y"))
                w = float(bounds.get("w", 40))
                h = float(bounds.get("h", 30))
                # Pad the crop: chord text may have superscripted 9s etc.
                pad_x = max(int(w * 0.5), 15)
                pad_y = max(int(h * 0.8), 20)
                crop_path = os.path.join(td, f"crop_{sheet_idx}_{int(x)}_{int(y)}.png")
                # Use ImageMagick to crop
                geom = f"{int(w + 2 * pad_x)}x{int(h + 2 * pad_y)}+{int(x - pad_x)}+{int(y - pad_y)}"
                subprocess.run(
                    ["magick", bin_png, "-crop", geom, "+repage", crop_path],
                    capture_output=True, check=False,
                )
                if not os.path.exists(crop_path):
                    continue
                # OCR
                result = subprocess.run(
                    ["tesseract", crop_path, "-", "--psm", "7",
                     "-c", f"tessedit_char_whitelist={CHORD_CHARS}"],
                    capture_output=True, text=True, check=False,
                )
                raw = result.stdout.strip()
                cleaned = _clean_chord(raw)
                if cleaned:
                    out.append(RecoveredChord(
                        sheet=sheet_idx, staff=int(sf),
                        x=x, y=y, value=cleaned, ocr_raw=raw,
                    ))
    return out


def main() -> None:
    found = recover_missing_chord_values(sys.argv[1])
    print(f"Recovered {len(found)} chord values:")
    for c in found:
        print(f"  sheet {c.sheet} staff {c.staff} x={c.x:.0f}: "
              f"value={c.value!r} (raw={c.ocr_raw!r})")


if __name__ == "__main__":
    main()
