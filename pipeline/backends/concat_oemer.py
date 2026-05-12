#!/usr/bin/env python3
"""Concatenate oemer's per-page MusicXMLs into one multi-page score.

oemer emits <stem>.musicxml per input image. We load them in page order,
concatenate their parts' measures, and renumber measures 1..N globally.

Usage: concat_oemer.py <work-dir> <out.musicxml>
"""
from __future__ import annotations
import os
import re
import sys
from copy import deepcopy
from music21 import converter, stream


def main() -> None:
    work = sys.argv[1]
    out_path = sys.argv[2]

    page_xmls = sorted(
        os.path.join(work, f)
        for f in os.listdir(work)
        if re.fullmatch(r"p-\d+\.musicxml", f)
    )
    if not page_xmls:
        raise SystemExit(f"no oemer output in {work}")

    combined = stream.Score()
    combined_parts: list[stream.Part] = []
    measure_counter = 0

    for idx, path in enumerate(page_xmls):
        page_score = converter.parse(path)
        for pi, p in enumerate(page_score.parts):
            if len(combined_parts) <= pi:
                combined_parts.append(stream.Part())
                combined_parts[pi].partName = f"oemer-{pi}"
            for m in p.getElementsByClass("Measure"):
                new_m = deepcopy(m)
                new_m.number = measure_counter + (m.number or 0)
                combined_parts[pi].append(new_m)
        if page_score.parts:
            measure_counter = max(
                (m.number or 0) for m in combined_parts[0].getElementsByClass("Measure")
            )

    for p in combined_parts:
        combined.insert(0, p)
    combined.write("musicxml", fp=out_path, makeNotation=False)
    print(f"wrote {out_path} ({len(combined_parts)} parts, {measure_counter} measures)")


if __name__ == "__main__":
    main()
