#!/usr/bin/env python3
"""Pre-process page PNGs so oemer can read piano-vocal scores.

Problem: oemer asserts `track_nums == 2`, failing on piano-vocal systems
which have 3 staves (vocal + piano RH + piano LH). Without this
pre-processing, oemer crashes on any page containing a full 3-staff
system.

Solution: use Audiveris's .omr to locate the piano LH staff in each
system (the bottom staff of every three), and paint a white rectangle
over it in the PNG. oemer then sees a clean 2-staff score.

Usage: oemer_prep.py <omr-path> <png-dir> <out-dir>

PNG dir contains the 400 DPI page renders named p-1.png, p-2.png, ...
The .omr and PNGs must describe the same PDF at approximately the same
DPI. We rescale Audiveris coords to the PNG resolution.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _staff_bounds(root: ET.Element) -> list[tuple[int, float, float]]:
    """Return [(staff_id, top_y, bottom_y), ...] sorted by top_y."""
    out: list[tuple[int, float, float]] = []
    for st in root.iter("staff"):
        sid = st.get("id")
        lines = st.find("lines")
        if sid is None or lines is None:
            continue
        line_ys: list[float] = []
        for ln in lines.iter("line"):
            pts = [float(p.get("y")) for p in ln.iter("point") if p.get("y") is not None]
            if pts:
                line_ys.append(sum(pts) / len(pts))
        if not line_ys:
            continue
        out.append((int(sid), min(line_ys), max(line_ys)))
    out.sort(key=lambda t: t[1])
    return out


def _audiveris_image_size(sheet_dir: str) -> tuple[int, int]:
    bin_png = os.path.join(sheet_dir, "BINARY.png")
    proc = subprocess.run(
        ["magick", "identify", "-format", "%w %h", bin_png],
        capture_output=True, text=True, check=False,
        timeout=60,
    )
    w, h = proc.stdout.strip().split()
    return int(w), int(h)


def _png_size(png_path: str) -> tuple[int, int]:
    proc = subprocess.run(
        ["magick", "identify", "-format", "%w %h", png_path],
        capture_output=True, text=True, check=False,
        timeout=60,
    )
    w, h = proc.stdout.strip().split()
    return int(w), int(h)


def process(omr_path: str, png_dir: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
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
            if not os.path.exists(xml_path):
                continue
            png_path = os.path.join(png_dir, f"p-{sheet_idx}.png")
            if not os.path.exists(png_path):
                continue

            root = ET.parse(xml_path).getroot()
            staves = _staff_bounds(root)
            if len(staves) < 3:
                # Not a piano-vocal system; copy through unchanged
                shutil.copy(png_path, os.path.join(out_dir, f"p-{sheet_idx}.png"))
                continue

            # Scale factor from Audiveris BINARY coords to our PNG coords
            a_w, a_h = _audiveris_image_size(os.path.join(td, sd))
            p_w, p_h = _png_size(png_path)
            sx, sy = p_w / a_w, p_h / a_h

            # Group staves into systems by y-distance. Within a system,
            # consecutive staves are closer together than the gap between
            # systems. Use the median inter-staff gap × 1.8 as threshold.
            staff_heights = [bot - top for _, top, bot in staves]
            avg_h = sum(staff_heights) / len(staff_heights)
            gaps = [staves[i + 1][1] - staves[i][2] for i in range(len(staves) - 1)]
            gaps_sorted = sorted(gaps)
            # Threshold: midpoint between the smallest gaps (intra-system) and
            # the largest (between-system). Use median as a proxy.
            mid_gap = gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else avg_h
            threshold = mid_gap * 1.8
            systems: list[list[int]] = [[0]]  # indices into `staves`
            for i in range(len(staves) - 1):
                if gaps[i] <= threshold:
                    systems[-1].append(i + 1)
                else:
                    systems.append([i + 1])
            # For each system: the TOP staff is the melody/vocal (keep), the
            # SECOND is typically piano RH (keep), anything below that (piano
            # LH and beyond) gets painted white. Also: if a system has only
            # 2 staves (piano intro), keep both.
            lh_staves: list[tuple[int, float, float]] = []
            for sys_idxs in systems:
                if len(sys_idxs) <= 2:
                    continue
                for idx in sys_idxs[2:]:
                    lh_staves.append(staves[idx])
            if not lh_staves:
                shutil.copy(png_path, os.path.join(out_dir, f"p-{sheet_idx}.png"))
                continue

            # Build an ImageMagick draw script that paints white rectangles
            # over each LH staff (plus a margin for ledger lines above and
            # below the actual staff lines).
            rects: list[str] = []
            margin_above = 55  # Audiveris coords - cover ledger lines + dynamics
            margin_below = 55
            for _, top_a, bot_a in lh_staves:
                y0 = int((top_a - margin_above) * sy)
                y1 = int((bot_a + margin_below) * sy)
                y0 = max(0, y0)
                y1 = min(p_h, y1)
                rects.append(f"rectangle 0,{y0} {p_w},{y1}")
            draw = " ".join(rects)

            out_png = os.path.join(out_dir, f"p-{sheet_idx}.png")
            try:
                subprocess.run(
                    ["magick", png_path,
                     "-fill", "white", "-stroke", "white",
                     "-draw", draw,
                     out_png],
                    capture_output=True, check=False,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                pass
            if not os.path.exists(out_png):
                # Fallback: pass through unchanged
                shutil.copy(png_path, out_png)
            print(f"  [prep] p-{sheet_idx}: painted {len(lh_staves)} LH staves white")


def main() -> None:
    process(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
