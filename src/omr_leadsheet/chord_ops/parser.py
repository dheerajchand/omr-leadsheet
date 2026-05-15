"""Decompose a chord-symbol string into structured fields.

Chord values from Audiveris (`Cmaj7`, `D9`, `A7(b5)`, `Bb6`, `F97`, `Em6`,
`C#dim7`, ...) are parsed into four independent axes:

  - root        : C, C#, D, ... A#, B  (12 classes)
  - quality     : major, minor, dim, aug, sus, dom7 (which we call "7"),
                  maj7, m7, m6, 6, half-dim          (11 classes)
  - extension   : none, 9, 11, 13, 9_over_7         (5 classes)
  - alteration  : none, b5, #5, b9, #9              (5 classes)

This decomposition is data-efficient: with ~1,300 labelled crops we get
~100 samples per axis-class, whereas a flat 116-way model has only 1-2
samples for many classes.

Output text is always emitted in MuseScore's ASCII chord-input grammar
(see https://handbook.musescore.org/text/chord-symbols and the project
``docs/chord-notation.md``). MuseScore's chord-style preset (jazz vs
standard) controls the *displayed* glyph at render time — we just feed
parseable tokens.

Round-trip: parse(label) → fields → format(fields, style) should equal
the canonical form of ``label`` under that style. For odd inputs we keep
the original string in a ``.raw`` attribute for debugging.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Literal


ROOTS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ROOTS_INDEX = {r: i for i, r in enumerate(ROOTS)}

# Alternate spellings (Audiveris and source notation use both flats and sharps)
FLAT_TO_SHARP = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}

QUALITIES = [
    "major", "minor", "7", "maj7", "m7", "dim", "dim7",
    "aug", "sus", "6", "m6", "half-dim",
]
EXTENSIONS = ["none", "9", "11", "13", "9_over_7"]
ALTERATIONS = ["none", "b5", "#5", "b9", "#9"]

ROOT_RE = re.compile(r"^([A-G][#b]?)")

# Unicode chord-quality glyphs we may receive from VLMs, hand-edits, or
# raw OCR. MuseScore refuses Unicode on input -- it expects ASCII tokens
# (handbook: "Critical: Do not input Unicode characters like U+266F (♯)
# or U+266D (♭) directly; MuseScore will not render them"). Normalize
# before parsing so the grammar below sees only ASCII.
UNICODE_TO_ASCII = {
    "♯": "#", "♭": "b",
    "°": "o",                # diminished
    "ø": "0", "⌀": "0",      # half-diminished
    "△": "t", "Δ": "t",      # major 7 (triangle)
    "ˆ": "t",                # Mac alt input for triangle
    "—": "-", "–": "-",  # em-dash / en-dash → minus
    "−": "-",           # math minus → ASCII minus
}


def normalize_for_musescore(text: str) -> str:
    """Strip Unicode chord glyphs to MuseScore-parseable ASCII tokens.

    Apply at any entry point that may receive non-ASCII chord text
    (VLM output, hand-edits round-tripped through external tools, etc.)
    before the text reaches MusicXML / `.mscx`.
    """
    out = text
    for u, a in UNICODE_TO_ASCII.items():
        out = out.replace(u, a)
    return out


@dataclass
class ChordFields:
    root: str          # one of ROOTS, sharps-normalised
    quality: str       # one of QUALITIES
    extension: str     # one of EXTENSIONS
    alteration: str    # one of ALTERATIONS
    raw: str = ""      # original label for debugging


def parse_chord(label: str) -> ChordFields | None:
    """Return ChordFields or None if the label doesn't look like a chord."""
    raw = label
    s = normalize_for_musescore(label).strip()
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

    # Half-diminished tokens (MS grammar: bare '0'; also accept m7b5 forms).
    if rest in ("0", "h", "ø"):
        quality = "half-dim"
        rest = ""
    elif rest in ("m7b5", "-7b5", "m7(b5)"):
        quality = "half-dim"
        rest = ""

    # Stacked 9-over-7 (the OCR'd `97` from G⁹⁷ etc.). MuseScore parses
    # `97` distinctly from `9` and voices them differently in playback,
    # so we preserve the literal stacking.
    elif rest.endswith("97"):
        quality = "7"
        extension = "9_over_7"
        rest = rest[:-2]
    elif rest in ("9", "11", "13"):
        quality = "major"  # bare extensions usually imply dominant
        extension = rest
        rest = ""
    elif rest == "":
        quality = "major"
    elif rest in ("m", "-", "mi", "min"):
        quality = "minor"
        rest = ""
    elif rest.startswith("maj7") or rest.startswith("t7") or rest.startswith("M7"):
        quality = "maj7"
        rest = rest[4:] if rest.startswith("maj7") else rest[2:]
    elif rest == "t" or rest == "M":
        # Bare triangle / M = major 7. MuseScore stores `t` alone as the
        # canonical suffix for major-7 (the triangle implies the 7th).
        quality = "maj7"
        rest = ""
    elif rest.startswith("m7") or rest.startswith("-7"):
        quality = "m7"
        rest = rest[2:]
    elif rest == "dim" or rest == "o":
        quality = "dim"
        rest = ""
    elif rest.startswith("dim7") or rest.startswith("o7"):
        quality = "dim7"
        rest = rest[4:] if rest.startswith("dim7") else rest[2:]
    elif rest.startswith("dim"):
        quality = "dim"
        rest = rest[3:]
    elif rest.startswith("aug") or rest == "+":
        quality = "aug"
        rest = rest[3:] if rest.startswith("aug") else ""
    elif rest.startswith("sus"):
        quality = "sus"
        rest = rest[3:]
    elif rest in ("m6", "-6"):
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


# MuseScore-parseable suffix tokens for each (quality, style) pair.
# Both columns are valid MS input; the chord-style preset (jazz vs
# standard) decides how the *displayed* glyph looks. See the handbook
# table reproduced in docs/chord-notation.md.
_SUFFIX = {
    "symbolic": {
        # Bare `t` = major 7 (the triangle subsumes the 7); MuseScore
        # stores it as the canonical maj7 suffix.
        "major": "", "minor": "-", "7": "7", "maj7": "t", "m7": "-7",
        "dim": "o", "dim7": "o7", "aug": "+", "sus": "sus",
        "6": "6", "m6": "-6", "half-dim": "0",
    },
    "textual": {
        "major": "", "minor": "m", "7": "7", "maj7": "maj7", "m7": "m7",
        "dim": "dim", "dim7": "dim7", "aug": "aug", "sus": "sus",
        "6": "6", "m6": "m6", "half-dim": "m7b5",
    },
}


Style = Literal["symbolic", "textual"]


def format_chord(f: ChordFields, style: Style = "symbolic") -> str:
    """Reconstruct a chord-symbol string from fields in MS-input grammar.

    ``style`` picks the chord-quality token style. Both styles emit
    text MuseScore parses identically -- the visual difference is
    rendered by the chord-style preset (Jazz vs Standard), not by us.

    The stacked 9-over-7 (``9_over_7`` extension) is emitted as the
    literal ``97`` because MuseScore parses ``9`` and ``97`` as
    distinct chord descriptors with different playback voicings.
    """
    suffix = _SUFFIX[style].get(f.quality, "")
    s = f.root + suffix
    if f.extension == "9_over_7":
        # Preserve the literal 9-over-7 stacking. Quality is normally "7"
        # in this branch; for any other base quality we append "97" so the
        # extension marker isn't silently dropped.
        if f.quality == "7":
            s = f.root + "97"
        else:
            s = f.root + suffix + "97"
    elif f.extension != "none":
        s = s + f.extension
    if f.alteration != "none":
        s = s + f"({f.alteration})"
    return s


__all__ = [
    "ROOTS", "QUALITIES", "EXTENSIONS", "ALTERATIONS",
    "ChordFields", "Style",
    "parse_chord", "format_chord", "normalize_for_musescore",
]
