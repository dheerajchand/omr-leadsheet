#!/usr/bin/env python3
"""Find chord glyphs Audiveris missed entirely, via connected-component scan.

The MARCATO/ACCENT recovery in `chord_row_ocr._recover_misclassified_articulations`
catches glyphs Audiveris *misclassified* (a jazz-font A read as a marcato).
But some chord-row glyphs are dropped entirely — Audiveris produces no
element at all for them. The chord-row tesseract sweep would find these
if tesseract could read the jazz font, but it usually can't.

This module solves the dropped-glyph case directly:

  1. For every staff with barlines, crop the chord-row strip above it.
  2. Find connected ink blobs in the strip (groups of adjacent
     dark-pixel columns separated by ≥ MIN_GAP px of whitespace).
  3. For each blob, build a tight bounding box plus a small padding.
  4. Hand the crop to the chord recogniser (VLM or CNN). Reject if it
     answers SKIP / UNSURE.
  5. Convert (x, y) to (measure, frac) using the staff's barlines.

The blob-based approach avoids the partial-glyph mis-reads that sliding
windows produce: each blob has clean left/right boundaries because
inter-chord whitespace defines them.

Used by `recover_chord_row_chords` when `CHORD_VLM=1` is set.

Library usage::

  from omr_leadsheet.recognisers.blobs import scan_chord_row_blobs
  rows = scan_chord_row_blobs(bin_png, strip_top, strip_bottom, clf)
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass


MIN_GAP = 10          # px of whitespace columns separating two blobs
MIN_BLOB_W = 12       # narrower blobs are noise (a tie endpoint, an articulation)
MAX_BLOB_W = 200      # wider blobs are page-edge artifacts or staff lines
MIN_INK_FRAC = 0.04   # blob must have at least this fraction of dark pixels
MAX_INK_FRAC = 0.45   # blobs denser than this are stems/staff lines, not glyphs
PADDING_X = 8         # extra horizontal padding when cropping
PADDING_Y = 5         # extra vertical padding


@dataclass
class Blob:
    x_left: int
    x_right: int
    y_top: int
    y_bottom: int
    crop_path: str = ""


def _find_blobs(bin_png: str, strip_top: int, strip_bottom: int) -> list[Blob]:
    """Return horizontally-disjoint ink blobs in the strip [top, bottom)."""
    try:
        from PIL import Image
    except ImportError:
        return []
    if strip_bottom <= strip_top:
        return []
    img = Image.open(bin_png).convert("L")
    W, H = img.size
    top = max(0, strip_top)
    bottom = min(H, strip_bottom)
    if bottom - top < 5:
        return []
    strip = img.crop((0, top, W, bottom))
    px = strip.load()
    strip_h = bottom - top

    # Per-column "has any ink" boolean
    col_has_ink = [False] * W
    for x in range(W):
        for y in range(strip_h):
            if px[x, y] < 128:
                col_has_ink[x] = True
                break

    # Group runs of consecutive ink columns; gaps ≥ MIN_GAP end a blob
    blobs: list[Blob] = []
    i = 0
    while i < W:
        if not col_has_ink[i]:
            i += 1
            continue
        x_left = i
        x_right = i
        gap_run = 0
        while i < W:
            if col_has_ink[i]:
                x_right = i
                gap_run = 0
            else:
                gap_run += 1
                if gap_run >= MIN_GAP:
                    break
            i += 1
        # x_right is inclusive
        w = x_right - x_left + 1
        if not (MIN_BLOB_W <= w <= MAX_BLOB_W):
            continue
        # Find tight vertical bounds within the blob
        y_top, y_bot = strip_h, 0
        ink = 0
        for x in range(x_left, x_right + 1):
            for y in range(strip_h):
                if px[x, y] < 128:
                    ink += 1
                    if y < y_top: y_top = y
                    if y > y_bot: y_bot = y
        if y_bot < y_top:
            continue
        bbox_area = w * (y_bot - y_top + 1)
        if bbox_area <= 0:
            continue
        frac = ink / bbox_area
        if not (MIN_INK_FRAC <= frac <= MAX_INK_FRAC):
            continue
        blobs.append(Blob(
            x_left=x_left, x_right=x_right,
            y_top=top + y_top, y_bottom=top + y_bot,
        ))
    return blobs


def scan_chord_row_blobs(
    bin_png: str,
    strip_top: int,
    strip_bottom: int,
    clf,
) -> list[tuple[int, str, float]]:
    """Return [(x_center, chord_string, conf)] of recognised chord blobs.

    `clf` must implement .recognise(path_or_pil) -> (chord_str, conf).
    """
    blobs = _find_blobs(bin_png, strip_top, strip_bottom)
    if not blobs:
        return []
    out: list[tuple[int, str, float]] = []
    with tempfile.TemporaryDirectory() as td:
        for i, b in enumerate(blobs):
            x0 = max(0, b.x_left - PADDING_X)
            y0 = max(0, b.y_top - PADDING_Y)
            w = b.x_right - b.x_left + 1 + 2 * PADDING_X
            h = b.y_bottom - b.y_top + 1 + 2 * PADDING_Y
            crop_path = os.path.join(td, f"blob_{i}_{b.x_left}_{b.y_top}.png")
            subprocess.run(
                ["magick", bin_png, "-crop",
                 f"{w}x{h}+{x0}+{y0}", "+repage", crop_path],
                capture_output=True, check=False,
            )
            if not os.path.exists(crop_path):
                continue
            chord, conf = clf.recognise(crop_path)
            if not chord or conf < 0.55:
                continue
            xc = (b.x_left + b.x_right) // 2
            out.append((xc, chord, conf))
    return out
