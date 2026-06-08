"""Shared barline and measure-geometry extraction from Audiveris .omr files.

The .omr format is a ZIP archive with per-sheet directories (sheet#1/,
sheet#2/, ...).  Each directory contains an XML file with barline,
staff, and measure metadata, plus a BINARY.png raster at 200 DPI.

This module consolidates the barline-to-measure mapping that was
previously duplicated across chord_ops/diff.py, recognisers/row_ocr.py,
pipeline/head_recovery.py, and reporting/review.py.
"""
from __future__ import annotations

import base64
import io
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment,misc]


@dataclass
class MeasureBounds:
    measure_number: int
    sheet_idx: int
    x_left: float
    x_right: float
    y_top: float
    y_bottom: float


def measure_bounds_from_omr(omr_path: str | Path) -> dict[int, MeasureBounds]:
    """Return {global_measure_number: MeasureBounds} for every measure."""
    omr_path = str(omr_path)
    out: dict[int, MeasureBounds] = {}
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_dirs = sorted(
            d for d in os.listdir(td)
            if os.path.isdir(os.path.join(td, d)) and d.startswith("sheet#")
        )
        global_offset = 0
        for sd in sheet_dirs:
            sheet_idx = int(sd.split("#")[1])
            xml_path = os.path.join(td, sd, f"{sd}.xml")
            if not os.path.exists(xml_path):
                continue
            root = ET.parse(xml_path).getroot()

            sb_x: dict[str, tuple[float, int]] = {}
            for sb in root.iter("staff-barline"):
                sbid = sb.get("id")
                sf = sb.get("staff")
                bounds = sb.find("bounds")
                if sbid is None or sf is None or bounds is None:
                    continue
                sb_x[sbid] = (float(bounds.get("x")), int(sf))

            staff_y: dict[int, tuple[float, float]] = {}
            for st in root.iter("staff"):
                sid = st.get("id")
                lines = st.find("lines")
                if sid is None or lines is None:
                    continue
                pts: list[float] = []
                for ln in lines.iter("line"):
                    for p in ln.iter("point"):
                        try:
                            pts.append(float(p.get("y")))
                        except (TypeError, ValueError):
                            continue
                if pts:
                    staff_y[int(sid)] = (min(pts), max(pts))

            vocal_staves: set[int] = set()
            for w in root.iter("word"):
                if w.get("staff") is not None:
                    vocal_staves.add(int(w.get("staff")))

            m_x_by_id: dict[int, list[tuple[float, int]]] = {}
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
                        bx, staff = sb_x[bid]
                        m_x_by_id.setdefault(mid, []).append((bx, staff))

            per_staff_bars: dict[int, list[tuple[float, int]]] = {}
            for mid, entries in m_x_by_id.items():
                for bx, staff in entries:
                    per_staff_bars.setdefault(staff, []).append((bx, mid))
            for v in per_staff_bars.values():
                v.sort()

            seen: dict[int, MeasureBounds] = {}
            staff_priority = sorted(vocal_staves) + sorted(
                s for s in per_staff_bars if s not in vocal_staves
            )
            for staff in staff_priority:
                lst = per_staff_bars.get(staff)
                if not lst:
                    continue
                prev_x = 0.0
                for bx, mid in lst:
                    if mid in seen:
                        prev_x = bx
                        continue
                    top, bottom = staff_y.get(staff, (0.0, 0.0))
                    seen[mid] = MeasureBounds(
                        measure_number=mid,
                        sheet_idx=sheet_idx,
                        x_left=prev_x,
                        x_right=bx,
                        y_top=top,
                        y_bottom=bottom,
                    )
                    prev_x = bx
            for mid, val in seen.items():
                out[global_offset + mid] = val

            all_mids_set = set()
            for lst in per_staff_bars.values():
                for _, mid in lst:
                    all_mids_set.add(mid)
            global_offset += max(all_mids_set) if all_mids_set else 0
    return out


def crop_measure(
    omr_path: str | Path,
    bounds: MeasureBounds,
    *,
    pad_x: int = 15,
    pad_above: int = 90,
    pad_below: int = 200,
) -> bytes | None:
    """Crop a single measure from BINARY.png, return PNG bytes.

    Uses Pillow if available, falls back to ImageMagick ``magick`` CLI.
    The default pad_below=200 captures lyrics below the staff.
    """
    omr_path = str(omr_path)
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        bin_png = os.path.join(td, f"sheet#{bounds.sheet_idx}", "BINARY.png")
        if not os.path.exists(bin_png):
            return None

        x0 = max(0, int(bounds.x_left - pad_x))
        x1 = int(bounds.x_right + pad_x)
        y0 = max(0, int(bounds.y_top - pad_above))
        y1 = int(bounds.y_bottom + pad_below)

        if Image is not None:
            img = Image.open(bin_png)
            x1 = min(x1, img.width)
            y1 = min(y1, img.height)
            cropped = img.crop((x0, y0, x1, y1))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()

        import subprocess
        width = x1 - x0
        height = y1 - y0
        crop_path = os.path.join(td, "crop.png")
        try:
            subprocess.run(
                ["magick", bin_png, "-crop",
                 f"{width}x{height}+{x0}+{y0}",
                 "+repage", crop_path],
                capture_output=True, check=True, timeout=60,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
        if not os.path.exists(crop_path):
            return None
        with open(crop_path, "rb") as f:
            return f.read()


def crop_measure_base64(
    omr_path: str | Path,
    bounds: MeasureBounds,
    **kwargs,
) -> str | None:
    """Like crop_measure but returns a base64-encoded string."""
    data = crop_measure(omr_path, bounds, **kwargs)
    if data is None:
        return None
    return base64.b64encode(data).decode("ascii")
