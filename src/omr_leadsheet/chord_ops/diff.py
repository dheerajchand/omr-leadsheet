#!/usr/bin/env python3
"""Diff Audiveris's recognized chord symbols against what got exported.

Audiveris keeps every recognized `chord-name` glyph in the .omr project file,
including ones whose beat-anchor failed (these get dropped from the .mxl export
but the text is still readable).

This tool:
  1. Unzips the .omr and parses each sheet XML.
  2. Extracts all <chord-name> glyphs with their text value, staff, and bounds.
  3. Computes measure x-ranges from barline positions and maps each chord-name
     to a (global-measure, value) pair.
  4. Parses the exported .mxl with music21 and collects its chord symbols.
  5. Prints a diff: which chord-names Audiveris recognized but didn't link.

Usage: chord_diff.py <path-to-.omr> <path-to-.mxl> [--insert-into <out.musicxml>]

With --insert-into, reads the reduced (or raw) MusicXML and inserts any
Audiveris-recognized-but-missing chord symbols at the start of their target
measure, then writes a new MusicXML.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from music21 import converter, harmony, stream


@dataclass
class OMRChord:
    sheet: int
    staff: int
    value: str
    x: float
    y: float
    measure_local: int | None = None
    measure_global: int | None = None
    # Fractional position within the measure (0.0 = start, 1.0 = end), computed
    # from the measure's x-range.
    measure_frac: float | None = None


def parse_sheet(xml_path: str, sheet_idx: int) -> tuple[list[OMRChord], int]:
    """Return (chord_list, num_measures_in_sheet)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Measure <right-barline> refers to <staff-barline> ids (not <barline>).
    # Each staff-barline has its own bounds and staff attribute.
    barline_box: dict[str, tuple[float, float, float, float]] = {}
    barline_staff: dict[str, int] = {}
    for b in root.iter("staff-barline"):
        bid = b.get("id")
        sf = b.get("staff")
        bounds = b.find("bounds")
        if bid is None or sf is None or bounds is None:
            continue
        barline_box[bid] = (
            float(bounds.get("x")), float(bounds.get("y")),
            float(bounds.get("w", 0)), float(bounds.get("h", 0)),
        )
        barline_staff[bid] = int(sf)

    # Build a per-staff sorted list of (x, measure_id)
    per_staff: dict[int, list[tuple[float, int]]] = {}
    for m in root.iter("measure"):
        mid_str = m.get("id") or ""
        # Measure IDs are usually integer but can be like "10C" for continuation
        num_match = re.match(r"(\d+)", mid_str)
        if not num_match:
            continue
        mid = int(num_match.group(1))
        rb = m.find("right-barline")
        if rb is None:
            continue
        sb = rb.find("staff-barlines")
        if sb is None or sb.text is None:
            continue
        for raw_bid in sb.text.split():
            box = barline_box.get(raw_bid)
            sf = barline_staff.get(raw_bid)
            if box is None or sf is None:
                continue
            per_staff.setdefault(sf, []).append((box[0], mid))

    for lst in per_staff.values():
        lst.sort()

    def measure_for(staff: int, x: float) -> tuple[int | None, float | None]:
        """Return (measure_id, fraction_within_measure [0..1])."""
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
        # Beyond the last barline in this staff — put it on the last measure
        return lst[-1][1], 0.99

    # Now collect chord-names
    chords: list[OMRChord] = []
    for c in root.iter("chord-name"):
        val = c.get("value")
        sf = c.get("staff")
        bounds = c.find("bounds")
        if val is None or sf is None or bounds is None:
            continue
        x = float(bounds.get("x"))
        y = float(bounds.get("y"))
        staff = int(sf)
        mid, frac = measure_for(staff, x)
        chords.append(OMRChord(
            sheet=sheet_idx, staff=staff, value=val, x=x, y=y,
            measure_local=mid, measure_frac=frac,
        ))

    # Count measures in this sheet: the max measure id across all measure elements.
    # Measure ids are numeric from 1..N within a sheet (sometimes with suffix like 10C).
    all_mids = set()
    for m in root.iter("measure"):
        mm = re.match(r"(\d+)", m.get("id") or "")
        if mm:
            all_mids.add(int(mm.group(1)))
    num_measures = max(all_mids) if all_mids else 0
    return chords, num_measures


def extract_omr_chords(omr_path: str) -> list[OMRChord]:
    """Unzip, parse every sheet, assign global measure numbers.

    Merges two sources:
      1. Audiveris's `<chord-name value=...>` entries (its own parsed chords).
      2. Chord-row tesseract OCR (`chord_row_ocr.py`) — catches chords
         Audiveris missed entirely (e.g. A7 on a weak glyph, the "7" of a
         stacked G9/7 symbol).
    """
    out: list[OMRChord] = []
    # Pass 1: Audiveris
    per_sheet_nmeas: list[int] = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_xmls: list[str] = []
        for d in sorted(os.listdir(td)):
            full = os.path.join(td, d)
            if not os.path.isdir(full):
                continue
            for f in sorted(os.listdir(full)):
                if f.endswith(".xml") and f.startswith("sheet#"):
                    sheet_xmls.append(os.path.join(full, f))
        global_offset = 0
        for idx, xml_path in enumerate(sheet_xmls, start=1):
            chords, nmeas = parse_sheet(xml_path, idx)
            for c in chords:
                if c.measure_local is not None:
                    c.measure_global = global_offset + c.measure_local
            out.extend(chords)
            per_sheet_nmeas.append(nmeas)
            global_offset += nmeas

    # Pass 2: chord-row OCR
    try:
        from omr_leadsheet.recognisers.row_ocr import recover_chord_row_chords
        row = recover_chord_row_chords(omr_path)
    except Exception:
        row = []

    # Build global-measure offsets per sheet for OCR'd chords
    sheet_offsets: dict[int, int] = {}
    off = 0
    for i, nm in enumerate(per_sheet_nmeas, start=1):
        sheet_offsets[i] = off
        off += nm

    # Convert OCR'd rows to OMRChord, skipping ones that overlap an existing
    # Audiveris chord at the same (measure, approx-fraction).
    def already_covered(gmeas: int, frac: float) -> bool:
        for c in out:
            if c.measure_global != gmeas:
                continue
            if c.measure_frac is not None and abs(c.measure_frac - frac) < 0.15:
                return True
        return False

    for rc in row:
        if rc.measure is None:
            continue
        gmeas = sheet_offsets.get(rc.sheet, 0) + rc.measure
        frac = rc.measure_frac or 0.0
        if already_covered(gmeas, frac):
            continue
        out.append(OMRChord(
            sheet=rc.sheet, staff=rc.staff, value=rc.value,
            x=rc.x, y=rc.y,
            measure_local=rc.measure, measure_global=gmeas,
            measure_frac=frac,
        ))
    return out


def extract_mxl_chords(mxl_path: str) -> list[tuple[int, str]]:
    """Return [(measure_number, chord_figure)] from the exported .mxl."""
    score = converter.parse(mxl_path)
    out: list[tuple[int, str]] = []
    for p in score.parts:
        for m in p.getElementsByClass("Measure"):
            for cs in m.recurse().getElementsByClass(harmony.ChordSymbol):
                out.append((m.number, cs.figure))
    return out


def normalize_chord(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


def diff(omr: list[OMRChord], mxl: list[tuple[int, str]]) -> list[OMRChord]:
    """Return OMR chord-names that have no matching entry in mxl for the same measure.

    Coverage rule: a present chord covers the target only if it is at
    least as specific (≥ length). So existing "Am7" covers an OMR
    "Am" (less specific, skip), but existing "G7" does NOT cover an
    OMR "G9/7" (more specific, insert and let insert_missing replace
    the less-specific one).
    """
    by_meas: dict[int, list[str]] = {}
    for meas, fig in mxl:
        by_meas.setdefault(meas, []).append(normalize_chord(fig))
    missing: list[OMRChord] = []
    for c in omr:
        if c.measure_global is None:
            missing.append(c)
            continue
        present = by_meas.get(c.measure_global, [])
        target = normalize_chord(c.value)
        matched = any(
            target == p or (len(target) <= len(p) and target in p)
            for p in present
        )
        if not matched:
            missing.append(c)
    return missing


def insert_missing(musicxml_path: str, missing: list[OMRChord], out_path: str) -> int:
    score = converter.parse(musicxml_path)
    # Find the part with chord symbols (first with any)
    target_part = None
    for p in score.parts:
        if any(p.recurse().getElementsByClass(harmony.ChordSymbol)):
            target_part = p
            break
    if target_part is None:
        target_part = score.parts[0]
    m_by_num = {m.number: m for m in target_part.getElementsByClass("Measure")}
    inserted = 0
    for c in missing:
        mn = c.measure_global
        if mn is None or mn not in m_by_num:
            continue
        target_m = m_by_num[mn]
        dur = target_m.duration.quarterLength or 4.0
        frac = c.measure_frac if c.measure_frac is not None else 0.0
        offset = round(frac * dur * 4) / 4  # snap to quarter-beat
        # Final dedup before insertion: skip if the same chord value already
        # exists anywhere in this measure, or if any chord at a similar offset
        # exists. Prevents the "G7 appears twice" issue when Audiveris and
        # chord_row_ocr both detect the same chord at slightly different x.
        existing = list(target_m.recurse().getElementsByClass(harmony.ChordSymbol))
        norm_target = normalize_chord(c.value)
        duplicate = False
        # First pass: detect exact duplicates and skip
        for ex in existing:
            if normalize_chord(ex.figure) == norm_target:
                duplicate = True
                break
        if duplicate:
            continue
        # Second pass: nearby substring matches.
        #  - If target is contained in a present chord, present is more
        #    specific (or equal) — skip target.
        #  - If a present chord is contained in target, target is more
        #    specific — REMOVE the less-specific present, then insert.
        to_remove = []
        for ex in existing:
            if abs(float(ex.offset) - offset) >= 0.5:
                continue
            ex_norm = normalize_chord(ex.figure)
            if norm_target in ex_norm and len(norm_target) < len(ex_norm):
                duplicate = True
                break
            if ex_norm in norm_target and len(ex_norm) < len(norm_target):
                to_remove.append(ex)
        if duplicate:
            continue
        for ex in to_remove:
            site = ex.activeSite
            if site is not None:
                site.remove(ex)
        # Also remove any TextExpression in this measure whose text
        # normalises to the same chord — earlier pipeline steps may have
        # emitted "G 7" as a `<direction>` when music21 couldn't parse
        # the spaced figure as a ChordSymbol; once we have the real
        # ChordSymbol we don't want both.
        from music21 import expressions
        for te in list(target_m.recurse().getElementsByClass(expressions.TextExpression)):
            te_text = getattr(te, "content", "")
            if te_text and normalize_chord(te_text) == norm_target:
                site = te.activeSite
                if site is not None:
                    site.remove(te)
        # Many Audiveris chord-name values aren't music21-parseable
        # (e.g., "b", "7(6)", "m7sus4"). For stacked-extension chords
        # like "F#9/7" — where the "/7" is a stacked-7 numerator on
        # top of "9", not a slash-chord — we strip the suffix for
        # music21 parsing but force the visible figure to the full
        # original text. That gives a real ChordSymbol with full
        # rendering, not just a text overlay.
        figure = c.value
        cs = None
        # Detect stacked extension: digit slash digit at end (e.g., "9/7", "6/5").
        # Parse using the top digit only (music21 understands "F#9") and
        # override the chord-kind display text so MuseScore renders the
        # full "9/7" stack. Setting .figure re-triggers parsing and fails;
        # chordKindStr just overrides display.
        m_stack = re.search(r"(\d)/(\d)$", figure)
        if m_stack:
            base_for_parse = figure[:m_stack.start()] + m_stack.group(1)
            try:
                cs = harmony.ChordSymbol(base_for_parse)
                cs.chordKindStr = f"{m_stack.group(1)}/{m_stack.group(2)}"
            except (ValueError, KeyError, IndexError):
                cs = None
        if cs is None:
            try:
                cs = harmony.ChordSymbol(figure)
            except (ValueError, KeyError, IndexError):
                cs = None
        if cs is not None:
            target_m.insert(offset, cs)
        else:
            from music21 import expressions
            te = expressions.TextExpression(figure)
            te.style.fontStyle = "italic"
            target_m.insert(offset, te)
        inserted += 1
    score.write("musicxml", fp=out_path, makeNotation=False)
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("omr")
    ap.add_argument("mxl")
    ap.add_argument("--insert-into", help="Read this MusicXML and write corrected output here")
    ap.add_argument("--out", help="Output MusicXML path (required with --insert-into)")
    ap.add_argument(
        "--measure-offset", type=int, default=0,
        help="Shift OMR measures by this amount to map raw→reduced (e.g., -4 if 4 intro measures were dropped)",
    )
    args = ap.parse_args()

    omr = extract_omr_chords(args.omr)
    # Apply measure offset if the target has been shifted (e.g. reduced file)
    if args.measure_offset:
        for c in omr:
            if c.measure_global is not None:
                c.measure_global += args.measure_offset
    # When inserting, diff against the target so we don't re-insert existing chords
    diff_target = args.insert_into or args.mxl
    mxl = extract_mxl_chords(diff_target)
    missing = diff(omr, mxl)

    print(f"OMR chord-names:       {len(omr)}")
    print(f"Exported chord symbols: {len(mxl)}")
    print(f"Missing from export:   {len(missing)}")
    print()
    print("=== Missing (Audiveris recognized, export dropped) ===")
    for c in sorted(missing, key=lambda c: (c.measure_global or 0, c.x)):
        mnum = c.measure_global if c.measure_global is not None else "?"
        print(f"  m{mnum}: {c.value!r}  (sheet {c.sheet}, staff {c.staff})")

    if args.insert_into:
        if not args.out:
            print("--out is required with --insert-into", file=sys.stderr)
            sys.exit(2)
        n = insert_missing(args.insert_into, missing, args.out)
        print(f"\nInserted {n} chord symbols into {args.out}")


if __name__ == "__main__":
    main()
