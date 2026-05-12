#!/usr/bin/env python3
"""Inspect an .mxl/.musicxml and print what music21 sees.

Usage: inspect_mxl.py <path-to-mxl>
"""
import sys
from collections import Counter
from music21 import converter, note, chord, harmony, expressions, bar, spanner


def main(path: str) -> None:
    score = converter.parse(path)
    print(f"=== {path} ===")
    print(f"parts: {len(score.parts)}")

    for i, part in enumerate(score.parts):
        inst = part.getInstrument(returnDefault=False)
        inst_name = inst.partName or inst.instrumentName if inst else None
        measures = list(part.getElementsByClass("Measure"))
        notes = list(part.recurse().notes)
        lyrics = sum(1 for n in notes if isinstance(n, note.Note) and n.lyrics)
        harmonies = list(part.recurse().getElementsByClass(harmony.ChordSymbol))
        staves = part.getElementsByClass("Staff")
        voices = list(part.recurse().getElementsByClass("Voice"))
        rehearsal = list(part.recurse().getElementsByClass(expressions.RehearsalMark))
        text_expr = list(part.recurse().getElementsByClass(expressions.TextExpression))
        repeats = [
            m for m in measures
            if any(isinstance(b, bar.Repeat) for b in m.recurse().getElementsByClass(bar.Repeat))
        ]
        try:
            ts = part.recurse().getElementsByClass("TimeSignature")[0].ratioString
        except IndexError:
            ts = "?"
        try:
            ks = str(part.recurse().getElementsByClass("KeySignature")[0])
        except IndexError:
            ks = "?"

        print(f"\n-- part[{i}] --")
        print(f"  id/name        : {part.id!r} / {part.partName!r}")
        print(f"  instrument     : {inst_name!r}")
        print(f"  measures       : {len(measures)}")
        print(f"  notes          : {len(notes)}")
        print(f"  notes w/ lyric : {lyrics}")
        print(f"  chord symbols  : {len(harmonies)}")
        print(f"  voices         : {len(voices)}")
        print(f"  time sig       : {ts}")
        print(f"  key sig        : {ks}")
        print(f"  rehearsal marks: {len(rehearsal)}")
        print(f"  text express   : {len(text_expr)}")
        print(f"  repeat measures: {len(repeats)}")
        if harmonies[:5]:
            sample = ", ".join(h.figure for h in harmonies[:8])
            print(f"  first chords   : {sample}")

    print("\n-- score-level --")
    top_harm = list(score.recurse().getElementsByClass(harmony.ChordSymbol))
    print(f"  total chord symbols across score: {len(top_harm)}")
    # Spanners (slurs, ties, hairpins)
    spanners = list(score.recurse().getElementsByClass(spanner.Spanner))
    kinds = Counter(type(s).__name__ for s in spanners)
    print(f"  spanners       : {dict(kinds)}")


if __name__ == "__main__":
    main(sys.argv[1])
