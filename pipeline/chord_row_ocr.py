#!/usr/bin/env python3
"""OCR chord symbols directly above each vocal staff.

Audiveris sometimes fails to even detect a chord-name glyph (as opposed
to detecting it but mis-reading the value). For those cases we do a
fresh OCR pass over the strip of pixels directly above each vocal
staff, where chord symbols sit in piano-vocal arrangements.

Pipeline per sheet:
  1. Extract BINARY.png from the .omr zip (Audiveris's own rendered image).
  2. Parse the .omr XML for staff y-coordinates and staff-barline x-ranges.
  3. Identify vocal staves (staves that own lyric <chord-syllable> relations).
  4. For each vocal staff:
       - Crop a strip from ~55 px above the top staff line to ~5 px above.
       - Run tesseract with a chord-friendly whitelist.
       - Find chord-like tokens (match /^[A-G][#b♯♭]?[a-zA-Z0-9+/-]*$/).
       - Convert token x-positions to (measure_number, offset_fraction)
         using the existing staff-barline table.
  5. Return the recovered chords — to be merged with Audiveris's parsed
     chord-names before insertion into the reduced MusicXML.

Usage: chord_row_ocr.py <path-to-.omr>

Integration: main pipeline imports `recover_chord_row_chords()`.
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


CHORD_REGEX = re.compile(r"^[A-G][#b♯♭]?(?:maj|min|aug|dim|sus|m|M|b|#|\+|\-|[0-9/\+])*$")
# Tight whitelist of characters that appear in chord symbols
CHORD_CHARS = "ABCDEFGabdefgimsu#b+-0123456789"


@dataclass
class RowChord:
    sheet: int
    staff: int
    x: float
    y: float
    value: str
    measure: int | None = None
    measure_frac: float | None = None


def _identify_vocal_staves(root: ET.Element) -> set[int]:
    """Staves that have lyric words attached. Matches the same heuristic
    used by head_recovery."""
    staves: set[int] = set()
    for w in root.iter("word"):
        s = w.get("staff")
        if s is not None:
            staves.add(int(s))
    return staves


def _staff_top_lines(root: ET.Element) -> dict[int, float]:
    """Top staff-line y-coordinate for each staff. The .omr XML has
    <staff><lines><line><point y=.../>.. </line>..</lines></staff>
    where the first <line> is the top staff line."""
    out: dict[int, float] = {}
    for st in root.iter("staff"):
        s_id = st.get("id")
        if s_id is None:
            continue
        lines = st.find("lines")
        if lines is None:
            continue
        first_line = lines.find("line")
        if first_line is None:
            continue
        pts = list(first_line.iter("point"))
        if not pts:
            continue
        # Average the top-line y across points so we don't bias to one end
        ys = [float(p.get("y")) for p in pts if p.get("y") is not None]
        if ys:
            out[int(s_id)] = sum(ys) / len(ys)
    return out


def _measure_xranges(root: ET.Element) -> dict[int, list[tuple[float, int]]]:
    """Per-staff list of (right_barline_x, measure_id) sorted by x.
    Mirrors chord_diff's logic."""
    sb_x: dict[str, tuple[float, int]] = {}
    for sb in root.iter("staff-barline"):
        sbid = sb.get("id")
        sf = sb.get("staff")
        bounds = sb.find("bounds")
        if sbid is None or sf is None or bounds is None:
            continue
        sb_x[sbid] = (float(bounds.get("x")), int(sf))
    per_staff: dict[int, list[tuple[float, int]]] = {}
    for m in root.iter("measure"):
        mid_str = m.get("id") or ""
        mm = re.match(r"(\d+)", mid_str)
        if not mm:
            continue
        mid = int(mm.group(1))
        rb = m.find("right-barline")
        if rb is None:
            continue
        sb_list = rb.find("staff-barlines")
        if sb_list is None or sb_list.text is None:
            continue
        for bid in sb_list.text.split():
            if bid in sb_x:
                x, staff = sb_x[bid]
                per_staff.setdefault(staff, []).append((x, mid))
    for lst in per_staff.values():
        lst.sort()
    return per_staff


def _measure_for(
    per_staff: dict[int, list[tuple[float, int]]],
    staff: int,
    x: float,
) -> tuple[int | None, float | None]:
    lst = per_staff.get(staff)
    if not lst:
        return None, None
    prev_bx = 0.0
    for bx, mid in lst:
        if x <= bx:
            width = bx - prev_bx
            frac = (x - prev_bx) / width if width > 0 else 0.0
            return mid, max(0.0, min(0.99, frac))
        prev_bx = bx
    return lst[-1][1], 0.99


def _ocr_run(img_path: str, psm: int, x_offset: int = 0) -> list[tuple[int, str]]:
    """Run tesseract in TSV mode. Returns [(x_center, token)]."""
    proc = subprocess.run(
        ["tesseract", img_path, "-",
         "--psm", str(psm),
         "-c", f"tessedit_char_whitelist={CHORD_CHARS}",
         "tsv"],
        capture_output=True, text=True, check=False,
    )
    out: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            left = int(parts[6])
            width = int(parts[8])
            conf = float(parts[10])
            text = parts[11].strip()
        except ValueError:
            continue
        if not text or not CHORD_REGEX.match(text):
            continue
        if conf < 25:
            continue
        # Single-letter tokens (A, D, F, etc.) are kept here so the classifier
        # can try to upgrade them to multi-char chords (A → A7, D → Dm7, …).
        # If the classifier doesn't upgrade them, they get rejected at the
        # end of _ocr_chord_row.
        out.append((x_offset + left + width // 2, text))
    return out


def _ocr_chord_row(png_path: str, top: int, bottom: int, img_width: int) -> list[tuple[int, str]]:
    """OCR a horizontal strip multiple ways and merge. Chord rows are
    often crowded — a single PSM fails to segment. We combine:
      - PSM 6 (uniform block) over the full strip
      - PSM 11 (sparse text) over the full strip
      - A sliding window with PSM 8 (single word) across the strip,
        catching crowded tokens that the whole-strip pass missed.
    Then dedupe by x-proximity.
    """
    if bottom <= top:
        return []
    strip_h = bottom - top
    with tempfile.TemporaryDirectory() as td:
        strip_path = os.path.join(td, "strip.png")
        subprocess.run(
            ["magick", png_path, "-crop", f"x{strip_h}+0+{top}", "+repage", strip_path],
            capture_output=True, check=False,
        )
        if not os.path.exists(strip_path):
            return []
        results: list[tuple[int, str]] = []
        # Whole-strip passes
        for psm in (6, 11):
            results.extend(_ocr_run(strip_path, psm))
        # Sliding window: 140 px wide, step 60 px, PSM 8
        win_w = 140
        step = 60
        x = 0
        while x < img_width:
            end = min(x + win_w, img_width)
            w = end - x
            win_path = os.path.join(td, f"win_{x}.png")
            subprocess.run(
                ["magick", png_path, "-crop", f"{w}x{strip_h}+{x}+{top}", "+repage", win_path],
                capture_output=True, check=False,
            )
            if os.path.exists(win_path):
                results.extend(_ocr_run(win_path, 8, x_offset=x))
            x += step
        # Dedupe by proximity — within 25px, keep the longer/more-specific token
        results.sort()
        deduped: list[tuple[int, str]] = []
        for xc, tok in results:
            if deduped and xc - deduped[-1][0] < 25:
                # Prefer longer chord figures (A7 > A, D7 > D, Cmaj7 > Cmaj)
                if len(tok) > len(deduped[-1][1]):
                    deduped[-1] = (xc, tok)
                continue
            deduped.append((xc, tok))

        # Optional: re-classify each token with the trained chord-symbol CNN.
        # Tesseract is good at *localising* chords; the CNN is better at
        # *recognising* them. If the CNN is confident, we trust its label.
        classifier_path = os.environ.get("CHORD_CLASSIFIER_PATH")
        if classifier_path and os.path.exists(classifier_path) and deduped:
            try:
                from classifier_infer import ChordClassifier
                clf = ChordClassifier(classifier_path)
                refined: list[tuple[int, str]] = []
                for xc, tok in deduped:
                    # Crop a window around the token's x-center
                    half = 40
                    x0 = max(0, xc - half)
                    w = min(img_width - x0, half * 2)
                    crop_path = os.path.join(td, f"clf_{xc}.png")
                    subprocess.run(
                        ["magick", png_path, "-crop",
                         f"{w}x{strip_h}+{x0}+{top}", "+repage", crop_path],
                        capture_output=True, check=False,
                    )
                    if not os.path.exists(crop_path):
                        refined.append((xc, tok))
                        continue
                    chord_str, conf = clf.recognise(crop_path)
                    # Confidence gate. Short predictions (bare letters like
                    # "A" or "D") are visually ambiguous with stray ink and
                    # need higher confidence to be trusted. Long ones can be
                    # accepted with lower confidence because their visual
                    # signature is more distinctive.
                    threshold = 0.8 if len(chord_str) <= 2 else 0.6
                    if conf >= threshold:
                        refined.append((xc, chord_str))
                    else:
                        refined.append((xc, tok))
                return refined
            except Exception as e:
                # Don't let the classifier break the pipeline; fall back to tesseract
                print(f"  (classifier disabled: {e})", file=__import__("sys").stderr)
        return deduped


def recover_chord_row_chords(omr_path: str) -> list[RowChord]:
    out: list[RowChord] = []
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
            vocal = _identify_vocal_staves(root)
            tops = _staff_top_lines(root)
            per_staff = _measure_xranges(root)

            # Get image width for sliding window
            from subprocess import run as _run
            img_width = 2500
            try:
                ident = _run(["magick", "identify", "-format", "%w", bin_png],
                             capture_output=True, text=True, check=False)
                img_width = int(ident.stdout.strip())
            except Exception:
                pass

            for staff_id in sorted(vocal):
                top_y = tops.get(staff_id)
                if top_y is None:
                    continue
                strip_top = max(0, int(top_y - 70))
                strip_bottom = int(top_y - 10)
                row_tokens = _ocr_chord_row(bin_png, strip_top, strip_bottom, img_width)
                for x_center, tok in row_tokens:
                    mid, frac = _measure_for(per_staff, staff_id, x_center)
                    out.append(RowChord(
                        sheet=sheet_idx, staff=staff_id,
                        x=float(x_center), y=float(top_y - 30),
                        value=tok, measure=mid, measure_frac=frac,
                    ))
    return out


def main() -> None:
    chords = recover_chord_row_chords(sys.argv[1])
    print(f"OCR'd {len(chords)} chord-like tokens from chord rows:")
    for c in chords:
        print(f"  sheet {c.sheet} staff {c.staff} m{c.measure} frac={c.measure_frac:.2f} value={c.value!r}")


if __name__ == "__main__":
    main()
