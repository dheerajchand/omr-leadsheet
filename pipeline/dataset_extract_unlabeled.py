#!/usr/bin/env python3
"""Extract unlabeled and weakly-labeled chord-symbol crops for hand-labeling.

The companion to dataset_extract.py. That script pulls every
<chord-name value="X"> where Audiveris already produced a label. This
one pulls the ones it *couldn't* — the crops the model has never seen:

  1. <chord-name> elements where Audiveris produced no `value`
     attribute (it found a chord glyph but couldn't read it).
  2. <articulation shape="MARCATO|ACCENT"> elements that sit in
     chord-row territory above a vocal staff (Audiveris misclassified
     the chord glyph as an articulation — these were what the recovery
     pass already finds, but here we keep them for re-training).
  3. <chord-name value="..."> entries where the value contains a `#`
     (sharps are under-represented and historically mislabeled, e.g.
     Eb79 should have been Eb97 — worth re-auditing).

Output:
  <out-dir>/crops/<source>_<sheet>_<x>_<y>.png   (one crop per glyph)
  <out-dir>/labels.csv                            (filename,source,
                                                  audiveris_guess,
                                                  context,correct_label)

You then fill in the `correct_label` column. A blank label means
"skip / not a chord". Run dataset_import_corrections.py to move the
labeled crops into dataset/<correct_label>/.

Usage:
  dataset_extract_unlabeled.py <omr-dir> <out-dir>
"""
from __future__ import annotations
import csv
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


CHORD_REGEX = re.compile(r"^[A-G][#b]?(?:maj|min|aug|dim|sus|m|M|\+|\-|[0-9])*$")


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:60]


def _staff_top(root: ET.Element) -> dict[int, float]:
    out: dict[int, float] = {}
    for st in root.iter("staff"):
        sid = st.get("id")
        if sid is None: continue
        line = st.find("lines/line")
        if line is None: continue
        ys = [float(p.get("y")) for p in line.iter("point") if p.get("y")]
        if ys: out[int(sid)] = sum(ys) / len(ys)
    return out


def _vocal_staves(root: ET.Element) -> set[int]:
    out: set[int] = set()
    for w in root.iter("word"):
        s = w.get("staff")
        if s is not None:
            try: out.add(int(s))
            except ValueError: pass
    return out


def _crop(bin_png: str, x: int, y: int, w: int, h: int, out_path: str) -> bool:
    pad_x = max(15, int(w * 0.3))
    pad_y = max(15, int(h * 0.4))
    geom = (
        f"{int(w + 2*pad_x)}x{int(h + 2*pad_y)}"
        f"+{int(x - pad_x)}+{int(y - pad_y)}"
    )
    r = subprocess.run(
        ["magick", bin_png, "-crop", geom, "+repage", out_path],
        capture_output=True, check=False,
    )
    return r.returncode == 0 and os.path.exists(out_path)


def process_omr(omr_path: str, crops_dir: str, rows: list[dict]) -> None:
    src = os.path.splitext(os.path.basename(omr_path))[0]
    safe_src = _safe(src)
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        for sd in sorted(d for d in os.listdir(td)
                         if os.path.isdir(os.path.join(td, d)) and d.startswith("sheet#")):
            xml_path = os.path.join(td, sd, f"{sd}.xml")
            bin_png = os.path.join(td, sd, "BINARY.png")
            if not (os.path.exists(xml_path) and os.path.exists(bin_png)):
                continue
            root = ET.parse(xml_path).getroot()
            tops = _staff_top(root)
            vocal = _vocal_staves(root)

            # 1) Unlabeled chord-name glyphs
            for c in root.iter("chord-name"):
                b = c.find("bounds")
                if b is None: continue
                val = (c.get("value") or "").strip()
                try:
                    x = int(float(b.get("x"))); y = int(float(b.get("y")))
                    w = int(float(b.get("w"))); h = int(float(b.get("h")))
                except (TypeError, ValueError):
                    continue
                context = None
                if not val:
                    context = "chord-name (unlabeled)"
                elif "#" in val:
                    context = f"chord-name w/ sharp (audiveris={val})"
                # Skip plain ASCII no-sharp labels — those are in the main dataset already
                if context is None:
                    continue
                fname = f"{safe_src}_{sd.replace('#','')}_{x}_{y}.png"
                if _crop(bin_png, x, y, w, h, os.path.join(crops_dir, fname)):
                    rows.append({
                        "filename": fname, "source": src,
                        "audiveris_guess": val, "context": context,
                        "correct_label": "",
                    })

            # 2) MARCATO/ACCENT articulations sitting in chord-row territory
            for el in root.iter("articulation"):
                shape = el.get("shape")
                if shape not in ("MARCATO", "ACCENT"): continue
                b = el.find("bounds")
                if b is None: continue
                try:
                    x = int(float(b.get("x"))); y = int(float(b.get("y")))
                    w = int(float(b.get("w"))); h = int(float(b.get("h")))
                except (TypeError, ValueError):
                    continue
                # In chord-row band (20-120 px above the nearest staff
                # below). We don't filter to vocal-only staves because
                # Audiveris's word-staff mapping is unreliable for
                # piano-vocal scores — a chord glyph can sit above a
                # staff that has no <word> elements attached.
                ns, nd = None, -1.0
                for s, top in tops.items():
                    da = top - y
                    if da < 0: continue
                    if ns is None or da < nd:
                        ns, nd = s, da
                if ns is None or not (20 <= nd <= 120):
                    continue
                fname = f"{safe_src}_{sd.replace('#','')}_art_{x}_{y}.png"
                if _crop(bin_png, x, y, w, h, os.path.join(crops_dir, fname)):
                    rows.append({
                        "filename": fname, "source": src,
                        "audiveris_guess": "",
                        "context": f"{shape} above staff {ns} ({int(nd)}px)",
                        "correct_label": "",
                    })


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: dataset_extract_unlabeled.py <omr-dir> <out-dir>", file=sys.stderr)
        sys.exit(2)
    omr_dir, out_dir = sys.argv[1], sys.argv[2]
    crops_dir = os.path.join(out_dir, "crops")
    os.makedirs(crops_dir, exist_ok=True)
    rows: list[dict] = []
    omr_files = sorted(os.path.join(omr_dir, f) for f in os.listdir(omr_dir) if f.endswith(".omr"))
    for omr in omr_files:
        print(f"  {os.path.basename(omr)}")
        process_omr(omr, crops_dir, rows)

    csv_path = os.path.join(out_dir, "labels.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename","source","audiveris_guess","context","correct_label"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nExtracted {len(rows)} crops → {crops_dir}")
    print(f"Label sheet:    {csv_path}")
    print(f"Next: open the folder, view crops, fill `correct_label` column.")
    print(f"Then: dataset_import_corrections.py {csv_path} {crops_dir} <dataset-dir>")


if __name__ == "__main__":
    main()
