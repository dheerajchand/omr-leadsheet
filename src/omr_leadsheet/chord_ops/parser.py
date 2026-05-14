"""Decompose a chord-symbol string into structured fields.

Chord values from Audiveris (`Cmaj7`, `D9`, `A7(b5)`, `Bb6`, `F97`, `Em6`,
`C#dim7`, ...) are parsed into four independent axes:

  - root        : C, C#, D, ... A#, B  (12 classes)
  - quality     : major, minor, dim, aug, sus, dom7 (which we call "7"),
                  maj7, m7, m6, 6                  (10 classes)
  - extension   : none, 9, 11, 13, 9_over_7        (5 classes)
  - alteration  : none, b5, #5, b9, #9             (5 classes)

This decomposition is data-efficient: with ~1,300 labelled crops we get
~100 samples per axis-class, whereas a flat 116-way model has only 1-2
samples for many classes.

Round-trip: parse(label) → fields → format(fields) should equal `label`
for well-formed chords. For odd inputs we keep the original string in a
.raw attribute for debugging.
"""
from __future__ import annotations
import re
from dataclasses import dataclass


ROOTS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROOTS_INDEX = {r: i for i, r in enumerate(ROOTS)}

# Alternate spellings (Audiveris and source notation use both flats and sharps)
FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}

QUALITIES = ["major", "minor", "7", "maj7", "m7", "dim", "dim7", "aug", "sus", "6", "m6"]
EXTENSIONS = ["none", "9", "11", "13", "9_over_7"]
ALTERATIONS = ["none", "b5", "#5", "b9", "#9"]

ROOT_RE = re.compile(r"^([A-G][#b]?)")


@dataclass
class ChordFields:
    root: str          # one of ROOTS, sharps-normalised
    quality: str       # one of QUALITIES
    extension: str     # one of EXTENSIONS
    alteration: str    # one of ALTERATIONS
    raw: str = ""      # original label for debugging


def parse_chord(label: str) -> ChordFields | None:
    """Return ChordFields or None if the label doesn't look like a chord."""
    s = label.strip()
    raw = s
    m = ROOT_RE.match(s)
    if not m:
        return None
    root = m.group(1)
    # Normalise flats to sharps
    root = FLAT_TO_SHARP.get(root, root)
    if root not in ROOTS_INDEX:
        return None
    rest = s[len(m.group(1)):]

    # Alteration in parentheses, e.g. "(b5)", "(b9)"
    alteration = "none"
    alt_match = re.search(r"\(([b#]?\d)\)", rest)
    if alt_match:
        alt_tok = alt_match.group(1)
        if alt_tok in ("b5", "#5", "b9", "#9"):
            alteration = alt_tok
        rest = rest[: alt_match.start()] + rest[alt_match.end():]

    # Quality + extension. Try recognised suffixes longest-first.
    quality = "major"
    extension = "none"

    # Stacked 9-over-7 (the OCR'd `97` from G⁹⁷ etc.)
    if rest.endswith("97"):
        quality = "7"
        extension = "9_over_7"
        rest = rest[:-2]
    elif rest in ("9", "11", "13"):
        quality = "major"  # Cmaj9 is rare; '9' on its own usually = dominant
        extension = rest
        rest = ""
    elif rest == "":
        quality = "major"
    elif rest == "m":
        quality = "minor"
    elif rest.startswith("maj7"):
        quality = "maj7"
        rest = rest[4:]
    elif rest.startswith("m7"):
        quality = "m7"
        rest = rest[2:]
    elif rest == "dim":
        quality = "dim"
        rest = ""
    elif rest.startswith("dim7"):
        quality = "dim7"
        rest = rest[4:]
    elif rest.startswith("dim"):
        quality = "dim"
        rest = rest[3:]
    elif rest.startswith("aug") or rest == "+":
        quality = "aug"
        rest = rest[3:] if rest.startswith("aug") else ""
    elif rest.startswith("sus"):
        quality = "sus"
        rest = rest[3:]
    elif rest == "m6":
        quality = "m6"
        rest = ""
    elif rest == "6":
        quality = "6"
        rest = ""
    elif rest == "7":
        quality = "7"
        rest = ""
    elif rest.startswith("7"):
        quality = "7"
        rest = rest[1:]
    elif rest == "9":
        quality = "major"
        extension = "9"
        rest = ""

    # Remaining digits → extension (covers cases like "Cmaj7" + "9" → maj9,
    # treated as quality=maj7 + extension=9 here)
    if rest in ("9", "11", "13"):
        extension = rest
        rest = ""
    elif rest == "+":
        # Trailing augmented marker we may have missed
        rest = ""

    return ChordFields(
        root=root, quality=quality,
        extension=extension, alteration=alteration,
        raw=raw,
    )


def format_chord(f: ChordFields) -> str:
    """Reconstruct a chord-symbol string from fields. Used for inference output."""
    q_map = {
        "major": "", "minor": "m", "7": "7", "maj7": "maj7", "m7": "m7",
        "dim": "dim", "dim7": "dim7", "aug": "+", "sus": "sus",
        "6": "6", "m6": "m6",
    }
    s = f.root + q_map.get(f.quality, "")
    if f.extension == "9_over_7":
        # Round-trip back to the OCR'd form
        s = f.root + "9/7"
    elif f.extension != "none":
        s = s + f.extension
    if f.alteration != "none":
        s = s + f"({f.alteration})"
    return s


__all__ = [
    "ROOTS", "QUALITIES", "EXTENSIONS", "ALTERATIONS",
    "ChordFields", "parse_chord", "format_chord",
]
