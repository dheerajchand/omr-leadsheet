#!/usr/bin/env python3
"""Generate a human-in-the-loop review page per song.

For each measure flagged by suspicious_measures.py, the page shows:
  - a crop of the original source-PDF image for that measure
  - what the pipeline captured: notes, chord symbols, lyrics
  - a text box the user can type corrections into (saves to JSON)

The HTML is fully self-contained (base64-embedded images) so it travels
with the song folder. Corrections are saved to corrections.json in the
same folder; the pipeline can read that file on subsequent runs.

Usage: review_tool.py <song-folder>

The tool expects the folder to contain:
  - <base>.review.md              (from suspicious_measures.py)
  - <base> - lead.corrected.musicxml
  - the source .omr in /MusicXML/
"""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from music21 import converter, note, harmony


def parse_review_md(path: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            m = re.match(r"\|\s*(\d+)\s*\|\s*([a-z_]+)\s*\|\s*(.+?)\s*\|", line)
            if m:
                out.append((int(m.group(1)), m.group(2), m.group(3)))
    return out


def measure_bounds_from_omr(omr_path: str) -> dict[int, tuple[int, float, float, float]]:
    """Return {global_measure: (sheet, x_left, x_right, y_top)}.

    Uses the same measure-barline logic as chord_diff.py. Vocal staff top
    for y positioning. If multiple staves claim the same measure, average
    across them.
    """
    out: dict[int, tuple[int, float, float, float]] = {}
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
            # staff-barline x by id (with its staff)
            sb_x: dict[str, tuple[float, int]] = {}
            for sb in root.iter("staff-barline"):
                sbid = sb.get("id")
                sf = sb.get("staff")
                bounds = sb.find("bounds")
                if sbid is None or sf is None or bounds is None:
                    continue
                sb_x[sbid] = (float(bounds.get("x")), int(sf))

            # Staff y bounds per staff id
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

            # Identify vocal staves
            vocal_staves: set[int] = set()
            for w in root.iter("word"):
                if w.get("staff") is not None:
                    vocal_staves.add(int(w.get("staff")))

            # Measures: right-barline staff refs → (x, staff)
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

            # Sort barlines per staff to compute each measure's left x
            per_staff_bars: dict[int, list[tuple[float, int]]] = {}
            for mid, entries in m_x_by_id.items():
                for bx, staff in entries:
                    per_staff_bars.setdefault(staff, []).append((bx, mid))
            for v in per_staff_bars.values():
                v.sort()

            # For each measure, find x-range using the preferred staff:
            # first vocal staff if available, else any staff.
            seen: dict[int, tuple[int, float, float, float]] = {}
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
                    top, _ = staff_y.get(staff, (0.0, 0.0))
                    seen[mid] = (sheet_idx, prev_x, bx, top)
                    prev_x = bx
            for mid, val in seen.items():
                out[global_offset + mid] = val

            # Track sheet measure count using ALL measures seen
            all_mids_set = set()
            for lst in per_staff_bars.values():
                for _, mid in lst:
                    all_mids_set.add(mid)
            global_offset += max(all_mids_set) if all_mids_set else 0
    return out


def crop_to_base64(omr_path: str, sheet_idx: int, x_left: float, x_right: float, y_top: float) -> str | None:
    """Extract BINARY.png from .omr and crop a measure region, return base64."""
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        bin_png = os.path.join(td, f"sheet#{sheet_idx}", "BINARY.png")
        if not os.path.exists(bin_png):
            return None
        x0 = max(0, int(x_left - 15))
        width = int(x_right - x_left + 30)
        # Crop: 120px above staff top to 120px below (enough for chord row + staff)
        y0 = max(0, int(y_top - 90))
        height = 250
        crop_path = os.path.join(td, "crop.png")
        subprocess.run(
            ["magick", bin_png, "-crop", f"{width}x{height}+{x0}+{y0}",
             "+repage", crop_path],
            capture_output=True, check=False,
        )
        if not os.path.exists(crop_path):
            return None
        with open(crop_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")


def summarise_measure(m) -> str:
    notes = [n.nameWithOctave for n in m.recurse().notes if isinstance(n, note.Note)]
    chords = [cs.figure for cs in m.recurse().getElementsByClass(harmony.ChordSymbol)]
    lyrics = []
    for n in m.recurse().notes:
        if isinstance(n, note.Note):
            for lyr in n.lyrics:
                lyrics.append(lyr.text or "")
    parts = []
    if chords:
        parts.append("<b>Chords:</b> " + ", ".join(chords))
    if notes:
        parts.append("<b>Notes:</b> " + " ".join(notes))
    if lyrics:
        parts.append("<b>Lyrics:</b> " + " ".join(lyrics))
    if not parts:
        parts.append("<i>(empty)</i>")
    return "<br>".join(parts)


def main() -> None:
    folder = sys.argv[1]
    base = os.path.basename(folder.rstrip("/"))
    review_md = os.path.join(folder, f"{base}.review.md")
    corrected_xml = os.path.join(folder, f"{base} - lead.corrected.musicxml")
    # BOOK_DIR env var; falls back to the grandparent of the song folder.
    book = os.environ.get("BOOK_DIR") or os.path.dirname(os.path.dirname(folder.rstrip("/")))
    omr_path = os.path.join(book, "MusicXML", f"{base}.omr")
    out_html = os.path.join(folder, "review.html")

    findings = parse_review_md(review_md)
    if not findings:
        with open(out_html, "w") as f:
            f.write(f"<h1>{base}</h1><p>No suspicious measures.</p>")
        print(f"wrote {out_html} (no flags)")
        return

    # Determine reduced→raw offset by looking for intro-dropped count
    # (we stored it in the measure numbering; simpler: read from corrected
    # file and compare to raw). For now assume reducer's --keep-verse
    # with intro_dropped = first rest-only run.
    raw_score = None
    raw_path = os.path.join(book, "MusicXML", f"{base}.mxl")
    if os.path.exists(raw_path):
        try:
            raw_score = converter.parse(raw_path)
        except Exception:
            pass
    intro_dropped = 0
    if raw_score is not None:
        for m in raw_score.parts[0].getElementsByClass("Measure"):
            if not list(m.recurse().notes):
                intro_dropped += 1
            else:
                break

    bounds = measure_bounds_from_omr(omr_path) if os.path.exists(omr_path) else {}

    reduced = converter.parse(corrected_xml)
    reduced_part = reduced.parts[0]
    m_by_num = {m.number: m for m in reduced_part.getElementsByClass("Measure")}

    # Build the HTML
    rows_html: list[str] = []
    for reduced_mnum, reason, detail in findings:
        raw_mnum = reduced_mnum + intro_dropped
        b = bounds.get(raw_mnum)
        img_tag = "<i>(no source image)</i>"
        if b is not None:
            sheet, x_left, x_right, y_top = b
            b64 = crop_to_base64(omr_path, sheet, x_left, x_right, y_top)
            if b64:
                img_tag = (f'<img class="src" '
                           f'src="data:image/png;base64,{b64}" alt="m{raw_mnum}">')
        m = m_by_num.get(reduced_mnum)
        current = summarise_measure(m) if m is not None else "(no data)"
        reason_label = {
            "all_rests_with_chords": "Missing melody notes",
            "duration_mismatch": "Rhythm mismatch",
            "missing_lyrics": "Missing lyrics",
        }.get(reason, reason)
        rows_html.append(f"""
<tr id="m{reduced_mnum}">
  <td class="mnum">m{reduced_mnum}<br><span class="raw">raw m{raw_mnum}</span></td>
  <td class="reason">{reason_label}<br><span class="detail">{detail}</span></td>
  <td class="image">{img_tag}</td>
  <td class="current">{current}</td>
  <td class="correction">
    <textarea data-measure="{reduced_mnum}"
              placeholder="Your correction (will save locally)"
              rows="3"></textarea>
  </td>
</tr>""")

    with open(out_html, "w") as f:
        f.write(f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Review: {base}</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 2rem; color: #222; }}
h1 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; max-width: 1400px; }}
th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
th {{ background: #f4f4f4; }}
.mnum {{ font-weight: bold; text-align: center; min-width: 70px; }}
.raw {{ font-weight: normal; color: #888; font-size: 0.85em; }}
.detail {{ color: #666; font-size: 0.85em; }}
.image img.src {{ max-width: 480px; border: 1px solid #ddd; }}
.current {{ font-size: 0.92em; max-width: 280px; }}
.correction textarea {{ width: 280px; font-family: menlo, monospace; font-size: 0.9em; }}
.savebar {{ position: sticky; top: 0; background: white; padding: 8px 0; border-bottom: 1px solid #ddd; }}
button {{ font-size: 1rem; padding: 6px 14px; margin-right: 8px; }}
</style>
</head>
<body>
<h1>{base}</h1>
<div class="savebar">
  <button onclick="saveJSON()">Save corrections to file</button>
  <button onclick="loadJSON()">Load corrections</button>
  <span id="count" style="margin-left:1em; color:#666"></span>
</div>
<table>
  <thead>
    <tr>
      <th>Measure</th><th>Issue</th><th>Source</th>
      <th>What pipeline captured</th><th>Your correction</th>
    </tr>
  </thead>
  <tbody>
{''.join(rows_html)}
  </tbody>
</table>
<script>
const KEY = "corrections:{base}";
function collect() {{
  const data = {{}};
  document.querySelectorAll("textarea[data-measure]").forEach(t => {{
    const v = t.value.trim();
    if (v) data[t.dataset.measure] = v;
  }});
  return data;
}}
document.querySelectorAll("textarea").forEach(t => {{
  t.addEventListener("input", () => {{
    localStorage.setItem(KEY, JSON.stringify(collect()));
    document.getElementById("count").textContent =
      Object.keys(collect()).length + " correction(s)";
  }});
}});
(function restore() {{
  const d = JSON.parse(localStorage.getItem(KEY) || "{{}}");
  for (const k in d) {{
    const t = document.querySelector(`textarea[data-measure="${{k}}"]`);
    if (t) t.value = d[k];
  }}
  document.getElementById("count").textContent =
    Object.keys(d).length + " correction(s)";
}})();
function saveJSON() {{
  const data = collect();
  const blob = new Blob([JSON.stringify(data, null, 2)], {{type: "application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "corrections.json"; a.click();
}}
function loadJSON() {{
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = ".json";
  inp.onchange = e => {{
    const f = e.target.files[0];
    const r = new FileReader();
    r.onload = () => {{
      const d = JSON.parse(r.result);
      for (const k in d) {{
        const t = document.querySelector(`textarea[data-measure="${{k}}"]`);
        if (t) t.value = d[k];
      }}
      localStorage.setItem(KEY, JSON.stringify(d));
    }};
    r.readAsText(f);
  }};
  inp.click();
}}
</script>
</body>
</html>""")
    print(f"wrote {out_html} ({len(findings)} flagged measures)")


if __name__ == "__main__":
    main()
