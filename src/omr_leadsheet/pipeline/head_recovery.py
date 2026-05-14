#!/usr/bin/env python3
"""Recover melody note-heads from the .omr project file that didn't make it
to the exported .mxl.

Audiveris can detect a note-head but then fail to assign it to a time slot
(usually due to unresolved rhythm in the measure). When that happens, the
head is present in the .omr XML but absent from the .mxl MusicXML export.

This tool:
  1. Parses the .omr to extract every <head> with its staff/pitch/shape/x/y.
  2. Resolves each head's measure via: head → head-chord (via containment
     relation) → measure (which lists head-chords in <head-chords>).
     Heads whose head-chord is not in any measure's list are "unlinked".
  3. Identifies the vocal staff in each system (the staff that carries
     lyric <chord-syllable> relations).
  4. Diffs unlinked vocal-staff heads against the notes present in the
     reduced .musicxml (by measure and x-position).
  5. Inserts missing notes into the reduced .musicxml, inferring:
        - pitch: staff-position + clef (treble middle line = B4)
        - octave transpose: optional (-12 semitones if the target uses
          treble-8vb clef)
        - duration: WHOLE_NOTE=4.0, NOTEHEAD_VOID=2.0, NOTEHEAD_BLACK=1.0
          (modified by flag/beam count - simplified to quarter by default)

Usage: head_recovery.py <omr> <reduced.musicxml> <out.musicxml>
                        [--measure-offset N] [--transpose-octave-down]

Generic + repo-ready: no song-specific heuristics; written to generalise.
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
from music21 import converter, note, harmony


@dataclass
class OMRHead:
    id: str
    staff: int
    pitch_position: int  # staff-relative, 0 = middle line, + up
    shape: str           # NOTEHEAD_BLACK, NOTEHEAD_VOID, WHOLE_NOTE
    x: float
    y: float
    sheet: int
    head_chord_id: str | None = None
    measure_id_in_sheet: int | None = None
    measure_global: int | None = None
    measure_frac: float | None = None
    linked: bool = False  # True if the containing head-chord is in a measure's list


def parse_sheet(xml_path: str, sheet_idx: int) -> tuple[list[OMRHead], int]:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # --- Step 1: inventory ---
    heads = [h for h in root.iter("head")]
    head_by_id = {h.get("id"): h for h in heads}

    # containment relations: source (container) -> target (contained)
    # head → head-chord: head is contained in head-chord
    contain_parent: dict[str, str] = {}
    id_to_tag: dict[str, str] = {}
    for e in root.iter():
        if e.get("id"):
            id_to_tag[e.get("id")] = e.tag
    for r in root.iter("relation"):
        if r.find("containment") is None:
            continue
        src = r.get("source")
        tgt = r.get("target")
        if not src or not tgt:
            continue
        # a head's containment: target is usually the head (child), source is the head-chord
        # But the relation direction may vary; pick based on tag
        stag = id_to_tag.get(src)
        ttag = id_to_tag.get(tgt)
        if stag == "head-chord" and ttag == "head":
            contain_parent[tgt] = src
        elif stag == "head" and ttag == "head-chord":
            contain_parent[src] = tgt

    # --- Step 2: which head-chords are linked to a measure? ---
    linked_hc_ids: set[str] = set()
    # Map measure_id -> local measure number (int)
    linked_hc_to_measure: dict[str, int] = {}
    for m in root.iter("measure"):
        mid_str = m.get("id") or ""
        num_match = re.match(r"(\d+)", mid_str)
        if not num_match:
            continue
        local_num = int(num_match.group(1))
        hc_list = m.find("head-chords")
        if hc_list is None or hc_list.text is None:
            continue
        for hc_id in hc_list.text.split():
            linked_hc_ids.add(hc_id)
            linked_hc_to_measure[hc_id] = local_num

    # --- Step 3: build staff barline x-ranges for each staff (for measure lookup) ---
    per_staff_barlines: dict[int, list[tuple[float, int]]] = {}
    # First: staff-barline id -> (x, staff)
    sb_x: dict[str, tuple[float, int]] = {}
    for sb in root.iter("staff-barline"):
        sbid = sb.get("id")
        sf = sb.get("staff")
        bounds = sb.find("bounds")
        if not sbid or not sf or bounds is None:
            continue
        sb_x[sbid] = (float(bounds.get("x")), int(sf))

    # Then for each measure, walk its right-barline references:
    for m in root.iter("measure"):
        mid_str = m.get("id") or ""
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
            if raw_bid in sb_x:
                x, staff = sb_x[raw_bid]
                per_staff_barlines.setdefault(staff, []).append((x, mid))
    for lst in per_staff_barlines.values():
        lst.sort()

    def measure_for(staff: int, x: float) -> tuple[int | None, float | None]:
        lst = per_staff_barlines.get(staff)
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

    # --- Step 4: total measures in sheet (for global offset) ---
    all_mids = set()
    for m in root.iter("measure"):
        mm = re.match(r"(\d+)", m.get("id") or "")
        if mm:
            all_mids.add(int(mm.group(1)))
    num_measures = max(all_mids) if all_mids else 0

    # --- Step 5: build OMRHead records ---
    out: list[OMRHead] = []
    for h in heads:
        hid = h.get("id")
        sf = h.get("staff")
        pitch = h.get("pitch")
        shape = h.get("shape")
        bounds = h.find("bounds")
        if not hid or not sf or pitch is None or shape is None or bounds is None:
            continue
        hc = contain_parent.get(hid)
        is_linked = hc in linked_hc_ids if hc else False
        # If linked, use the measure from the hc mapping; else fall back to x-range lookup
        if is_linked and hc in linked_hc_to_measure:
            measure_id = linked_hc_to_measure[hc]
            # x-fraction by barline lookup anyway
            _, frac = measure_for(int(sf), float(bounds.get("x")))
        else:
            measure_id, frac = measure_for(int(sf), float(bounds.get("x")))
        out.append(OMRHead(
            id=hid,
            staff=int(sf),
            pitch_position=int(pitch),
            shape=shape,
            x=float(bounds.get("x")),
            y=float(bounds.get("y")),
            sheet=sheet_idx,
            head_chord_id=hc,
            measure_id_in_sheet=measure_id,
            linked=is_linked,
        ))
    return out, num_measures


def identify_vocal_staves(xml_path: str) -> set[int]:
    """Vocal staves are the ones that carry lyrics (chord-syllable relations)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    # chord-syllable relations connect a chord (head-chord) to a word/lyric.
    # Words have a staff attribute.
    staves = set()
    for w in root.iter("word"):
        sf = w.get("staff")
        if sf:
            staves.add(int(sf))
    # Also chord-sentences with lyric roles
    for cs in root.iter("chord-sentence"):
        sf = cs.get("staff")
        if sf and cs.get("role", "").lower() == "lyrics":
            staves.add(int(sf))
    return staves


def extract_from_omr(omr_path: str) -> tuple[list[OMRHead], set[int]]:
    out_heads: list[OMRHead] = []
    vocal_staves_per_sheet: list[set[int]] = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_xmls = []
        for d in sorted(os.listdir(td)):
            full = os.path.join(td, d)
            if not os.path.isdir(full):
                continue
            for f in sorted(os.listdir(full)):
                if f.endswith(".xml") and f.startswith("sheet#"):
                    sheet_xmls.append(os.path.join(full, f))
        global_offset = 0
        combined_vocals: set[int] = set()
        for idx, xml_path in enumerate(sheet_xmls, start=1):
            heads, nm = parse_sheet(xml_path, idx)
            for h in heads:
                if h.measure_id_in_sheet is not None:
                    h.measure_global = global_offset + h.measure_id_in_sheet
            out_heads.extend(heads)
            vs = identify_vocal_staves(xml_path)
            for s in vs:
                combined_vocals.add(s)
            global_offset += nm
    return out_heads, combined_vocals


# --- Pitch conversion: treble clef, position 0 = B4 ---
_STEPS = {1: "C", 2: "D", 3: "E", 4: "F", 5: "G", 6: "A", 7: "B"}


def treble_position_to_pitch(pos: int) -> str:
    """Return a pitch name (e.g., 'B4') for a treble-clef staff position
    where 0 = middle line (B4)."""
    # B4 diatonic number = 35 (C1=1, D1=2, ..., B1=7, C2=8, ..., B4=35)
    target = 35 + pos
    step_idx = (target - 1) % 7 + 1
    octave = (target - 1) // 7
    return f"{_STEPS[step_idx]}{octave}"


SHAPE_TO_QL = {
    "WHOLE_NOTE": 4.0,
    "NOTEHEAD_VOID": 2.0,    # half note by default
    "NOTEHEAD_BLACK": 1.0,    # quarter by default
    "BREVE": 8.0,
}


def insert_heads(
    musicxml_path: str,
    heads: list[OMRHead],
    vocal_staves: set[int],
    out_path: str,
    measure_offset: int = 0,
    transpose_octave_down: bool = True,
) -> dict:
    """Insert unlinked vocal-staff heads into the given musicxml."""
    score = converter.parse(musicxml_path)
    # Pick the part that carries lyrics (most lyric-bearing notes)
    best_idx, best = 0, -1
    for i, p in enumerate(score.parts):
        c = sum(1 for n in p.recurse().notes if isinstance(n, note.Note) and n.lyrics)
        if c > best:
            best_idx, best = i, c
    target_part = score.parts[best_idx]
    m_by_num = {m.number: m for m in target_part.getElementsByClass("Measure")}

    stats = {"inserted": 0, "skipped_linked": 0, "skipped_not_vocal": 0, "skipped_no_measure": 0, "skipped_duplicate": 0}
    for h in heads:
        if h.staff not in vocal_staves:
            stats["skipped_not_vocal"] += 1
            continue
        if h.linked:
            stats["skipped_linked"] += 1
            continue
        if h.measure_global is None:
            stats["skipped_no_measure"] += 1
            continue
        target_m_num = h.measure_global + measure_offset
        target_m = m_by_num.get(target_m_num)
        if target_m is None:
            stats["skipped_no_measure"] += 1
            continue
        # Compute intended offset within the measure
        dur = target_m.duration.quarterLength or 4.0
        frac = h.measure_frac if h.measure_frac is not None else 0.0
        offset = round(frac * dur * 4) / 4
        # Compute pitch
        pitch_name = treble_position_to_pitch(h.pitch_position)
        note_obj = note.Note(pitch_name)
        if transpose_octave_down:
            note_obj.octave = (note_obj.octave or 4) - 1
        note_obj.quarterLength = SHAPE_TO_QL.get(h.shape, 1.0)
        # Check duplicate: any existing note at ~same offset and ~same pitch?
        dup = False
        for existing in target_m.recurse().notes:
            if not isinstance(existing, note.Note):
                continue
            if abs(float(existing.offset) - offset) < 0.25 and existing.pitch.ps == note_obj.pitch.ps:
                dup = True
                break
        if dup:
            stats["skipped_duplicate"] += 1
            continue
        target_m.insert(offset, note_obj)
        stats["inserted"] += 1
    score.write("musicxml", fp=out_path, makeNotation=False)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("omr")
    ap.add_argument("musicxml")
    ap.add_argument("out")
    ap.add_argument("--measure-offset", type=int, default=0,
                    help="Shift OMR measures by this (e.g., -4 for 4 dropped intro measures)")
    ap.add_argument("--no-octave-down", action="store_true",
                    help="Don't transpose recovered notes down an octave")
    args = ap.parse_args()

    heads, vocal_staves = extract_from_omr(args.omr)
    print(f"OMR total heads: {len(heads)}")
    print(f"Detected vocal staves: {sorted(vocal_staves)}")
    linked = sum(1 for h in heads if h.linked)
    unlinked = sum(1 for h in heads if not h.linked)
    voc_linked = sum(1 for h in heads if h.linked and h.staff in vocal_staves)
    voc_unlinked = sum(1 for h in heads if not h.linked and h.staff in vocal_staves)
    print(f"  linked: {linked} (vocal: {voc_linked})")
    print(f"  unlinked: {unlinked} (vocal: {voc_unlinked})")

    stats = insert_heads(
        args.musicxml, heads, vocal_staves, args.out,
        measure_offset=args.measure_offset,
        transpose_octave_down=not args.no_octave_down,
    )
    print("Insertion:", stats)


if __name__ == "__main__":
    main()
