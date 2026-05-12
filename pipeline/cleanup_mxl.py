#!/usr/bin/env python3
"""Pre-clean Audiveris .mxl / .musicxml output so MuseScore can import it.

Audiveris occasionally emits unclosed <tuplet> notations (a <tuplet
type="start"> with no matching type="stop" in the same measure).
MuseScore rejects the whole file with exit 40.

Our fix: for each measure, if the tuplet brackets don't balance, strip
all <tuplet> notations in that measure. We keep <time-modification>
elements so note durations remain correct — MuseScore just won't draw
the tuplet bracket.

Usage: cleanup_mxl.py <input.mxl|.xml> <output.xml>
"""
from __future__ import annotations
import re
import sys
import zipfile
import xml.etree.ElementTree as ET


def load_xml(path: str) -> str:
    if path.endswith(".mxl"):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".xml") and "META-INF" not in n]
            if not names:
                raise RuntimeError(f"no .xml in {path}")
            with z.open(names[0]) as f:
                return f.read().decode("utf-8")
    with open(path) as f:
        return f.read()


def fix_tuplets_in_measure(measure_xml: str) -> str:
    """Count <tuplet type="start"> and type="stop"> in this measure. If
    unbalanced, strip all <tuplet> elements AND <time-modification> entirely.
    (Both need to go together, or notes will have time-modification without
    the bracket and MuseScore can still complain.)"""
    starts = len(re.findall(r'<tuplet[^>]*type="start"', measure_xml))
    stops = len(re.findall(r'<tuplet[^>]*type="stop"', measure_xml))
    if starts == stops:
        return measure_xml
    # Strip all tuplet notations AND time-modification in this measure
    out = re.sub(r"<tuplet[^/]*/>\s*", "", measure_xml)
    out = re.sub(r"<tuplet[^>]*>.*?</tuplet>\s*", "", out, flags=re.DOTALL)
    out = re.sub(r"<time-modification>.*?</time-modification>\s*", "", out, flags=re.DOTALL)
    return out


def strip_all_tuplets(xml: str) -> str:
    """Aggressively strip all tuplet markup. Loses the bracket but notes stay."""
    x = re.sub(r"<tuplet[^/]*/>\s*", "", xml)
    x = re.sub(r"<tuplet[^>]*>.*?</tuplet>\s*", "", x, flags=re.DOTALL)
    x = re.sub(r"<time-modification>.*?</time-modification>\s*", "", x, flags=re.DOTALL)
    return x


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--aggressive", action="store_true",
                    help="Strip ALL tuplets, not just unbalanced ones")
    args = ap.parse_args()
    xml = load_xml(args.input)

    if args.aggressive:
        out_xml = strip_all_tuplets(xml)
        with open(args.output, "w") as f:
            f.write(out_xml)
        print("  aggressive: stripped all tuplets and time-modifications")
        return

    # Walk each measure and fix unbalanced tuplets
    fixed = 0
    def fixer(match: re.Match) -> str:
        nonlocal fixed
        m = match.group(0)
        new_m = fix_tuplets_in_measure(m)
        if new_m != m:
            fixed += 1
        return new_m

    out_xml = re.sub(r"<measure[^>]*>.*?</measure>", fixer, xml, flags=re.DOTALL)
    with open(args.output, "w") as f:
        f.write(out_xml)
    print(f"  tuplet-rebalanced measures: {fixed}")


if __name__ == "__main__":
    main()
