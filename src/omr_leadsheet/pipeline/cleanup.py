#!/usr/bin/env python3
"""Pre-clean Audiveris .mxl / .musicxml output so MuseScore can import it.

Audiveris occasionally emits unclosed ``<tuplet>`` notations (a
``<tuplet type="start">`` with no matching ``type="stop"`` in the same
measure). MuseScore rejects the whole file with exit 40.

The fix: for each measure, if tuplet brackets don't balance, strip
``<tuplet>`` notations in that measure. ``<time-modification>`` goes
with them so note durations stay correct; MuseScore just doesn't draw
the bracket.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

__all__ = ["cleanup", "load_xml", "strip_all_tuplets", "fix_tuplets_in_measure"]


def load_xml(path: str | Path) -> str:
    path = Path(path)
    if path.suffix == ".mxl":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".xml") and "META-INF" not in n]
            if not names:
                raise RuntimeError(f"no .xml in {path}")
            with z.open(names[0]) as f:
                return f.read().decode("utf-8")
    return path.read_text()


def cleanup(input_path: str | Path, output_path: str | Path, *, aggressive: bool = False) -> int:
    """Rebalance tuplets and write a clean MusicXML file.

    Parameters
    ----------
    input_path : str | Path
        Source ``.mxl`` or ``.musicxml`` file.
    output_path : str | Path
        Destination ``.xml`` file. Parent directories are created if missing.
    aggressive : bool
        If True, strip every tuplet (not just unbalanced ones).

    Returns
    -------
    int
        Number of measures rewritten (0 when aggressive=True, since the
        whole document is overwritten without per-measure counting).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml = load_xml(input_path)

    if aggressive:
        output_path.write_text(strip_all_tuplets(xml))
        return 0

    fixed = 0

    def fixer(match: re.Match) -> str:
        nonlocal fixed
        original = match.group(0)
        replaced = fix_tuplets_in_measure(original)
        if replaced != original:
            fixed += 1
        return replaced

    new_xml = re.sub(r"<measure[^>]*>.*?</measure>", fixer, xml, flags=re.DOTALL)
    output_path.write_text(new_xml)
    return fixed


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

    fixed = cleanup(args.input, args.output, aggressive=args.aggressive)
    if args.aggressive:
        print("  aggressive: stripped all tuplets and time-modifications")
    else:
        print(f"  tuplet-rebalanced measures: {fixed}")


if __name__ == "__main__":
    main()
