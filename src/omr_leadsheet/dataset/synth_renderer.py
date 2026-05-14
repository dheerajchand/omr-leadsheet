#!/usr/bin/env python3
"""Render synthetic chord-symbol crops in the style of the source PDFs.

Empirical font analysis (see scripts/font_match.py) showed that the
chord symbols in the source PDFs are drawn in MuseScore's default text
font, Edwin-Roman, at ~32-36 px. Accidentals (#/b) and stacked
extensions (9/7) need separate handling because they are positioned
manually in MuseScore — not as inline ligatures.

A synthetic crop is built up like this:

  +--------------------+
  | A#               9 |   ← root (Edwin-Roman) + accidental (Bravura)
  |                  7 |     + extension (small Edwin-Roman)
  +--------------------+

For every chord string, we render variants:
  * small / medium / large size (matches 200 / 300 / 400 DPI scans)
  * with / without subtle gaussian-blur (mimics scanner artifacts)
  * with / without slight rotation (±2°)
  * with / without random salt-and-pepper noise (1% pixels)

This produces ~8 visually-different training examples per chord string.
Combined with ~5000 unique chord strings, we get ~40,000 synthetic
samples — enough to bias the model heavily toward correct readings
even for sharp-key + stacked-extension chords that are rare in real
data.

Usage:
  synth_chord_renderer.py <out-dir>
"""
from __future__ import annotations
import os
import random
import re
import sys
from itertools import product
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# Font paths — Edwin-Roman for text, Bravura for music symbols (sharps/flats)
TEXT_FONT = "/Applications/MuseScore 4.app/Contents/Resources/fonts/Edwin-Roman.otf"
TEXT_FONT_ITALIC = "/Applications/MuseScore 4.app/Contents/Resources/fonts/Edwin-Italic.otf"
MUSIC_FONT = "/Applications/MuseScore 4.app/Contents/Resources/fonts/BravuraText.otf"

# SMuFL code points
SHARP = ""   # accidentalSharp
FLAT  = ""   # accidentalFlat
NAT   = ""   # accidentalNatural

ROOTS = ["C", "D", "E", "F", "G", "A", "B"]
ACCIDENTALS = ["", "#", "b"]
QUALITIES = ["", "m", "dim", "+"]
EXTENSIONS = ["", "6", "7", "9", "11", "13", "maj7", "97", "65", "sus4"]


def chord_strings() -> list[str]:
    """All chord-string combinations we want to learn."""
    out: list[str] = []
    for r, a, q, e in product(ROOTS, ACCIDENTALS, QUALITIES, EXTENSIONS):
        # Some combos don't make musical sense — skip those
        if q == "+" and e in ("maj7", "11", "13"): continue
        if q == "dim" and e in ("9", "11", "13", "maj7"): continue
        if q == "M" and e == "": continue  # plain "M" is weird, "Maj7" is meaningful
        s = f"{r}{a}{q}{e}"
        out.append(s)
    # Also add some specific paren-style alterations seen in real data
    for r, a in product(ROOTS, ACCIDENTALS):
        for ext in ("7(b5)", "7(b9)", "7(6)", "9(6)", "7sus4"):
            out.append(f"{r}{a}{ext}")
    # Dedup
    return sorted(set(out))


def render_chord(
    chord: str, *, base_size: int = 32, italic: bool = False,
) -> Image.Image:
    """Render a chord string to a PIL Image at base_size px."""
    # Parse: root letter, accidental, rest
    m = re.match(r"^([A-G])([#b]?)(.*)$", chord)
    if not m:
        return None
    root, acc, rest = m.group(1), m.group(2), m.group(3)

    # Detect stacked extension (digit pair at end, e.g. 97, 65)
    stack = None
    rest_main = rest
    stack_match = re.search(r"(\d)(\d)$", rest)
    # Treat double-digit extensions as stacked only for known pairs
    if stack_match and stack_match.group(0) in ("97", "65", "13", "11"):
        # "97" and "65" are clearly stacked; "13", "11" are inline two-digit
        if stack_match.group(0) in ("97", "65"):
            stack = (stack_match.group(1), stack_match.group(2))
            rest_main = rest[:stack_match.start()]

    text_font = ImageFont.truetype(TEXT_FONT_ITALIC if italic else TEXT_FONT, base_size)
    music_font = ImageFont.truetype(MUSIC_FONT, int(base_size * 0.7))
    ext_font = ImageFont.truetype(TEXT_FONT_ITALIC if italic else TEXT_FONT, int(base_size * 0.7))

    # Measure pieces to size the canvas
    parts: list[tuple[str, ImageFont.ImageFont, str]] = []
    # (text, font, role) where role is "root"|"acc"|"ext"|"stack-top"|"stack-bot"
    parts.append((root, text_font, "root"))
    if acc == "#":
        parts.append((SHARP, music_font, "acc"))
    elif acc == "b":
        parts.append((FLAT, music_font, "acc"))
    if rest_main:
        parts.append((rest_main, ext_font, "ext"))
    if stack:
        parts.append((stack[0], ext_font, "stack-top"))
        parts.append((stack[1], ext_font, "stack-bot"))

    # Layout: lay parts left-to-right, with accidentals raised slightly
    canvas_w = int(base_size * (1.5 + 0.5 * len(parts)))
    # Stacked extensions need more vertical room above + below baseline
    canvas_h = int(base_size * 2.4) if stack else int(base_size * 1.8)
    img = Image.new("L", (canvas_w, canvas_h), 255)
    d = ImageDraw.Draw(img)

    baseline_y = int(canvas_h * 0.6)
    x = int(base_size * 0.25)
    last_main_right = x
    for text, font, role in parts:
        bbox = d.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if role == "root":
            y = baseline_y - h - bbox[1]
            d.text((x, y), text, font=font, fill=0)
            x += w + int(base_size * 0.05)
            last_main_right = x
        elif role == "acc":
            # Accidental raised, slightly smaller, just after root
            y = baseline_y - h - bbox[1] - int(base_size * 0.1)
            d.text((x, y), text, font=font, fill=0)
            x += w + int(base_size * 0.1)
            last_main_right = x
        elif role == "ext":
            y = baseline_y - h - bbox[1]
            d.text((x, y), text, font=font, fill=0)
            x += w + int(base_size * 0.05)
            last_main_right = x
        elif role == "stack-top":
            # Raised so it sits above where a normal-position digit would
            y = baseline_y - h - bbox[1] - int(base_size * 0.45)
            d.text((last_main_right, y), text, font=font, fill=0)
        elif role == "stack-bot":
            # Lowered, sits below normal baseline
            y = baseline_y - h - bbox[1] + int(base_size * 0.15)
            d.text((last_main_right, y), text, font=font, fill=0)

    # Tight-crop the result and pad
    bbox = img.getbbox()
    if bbox is None:
        return None
    img = img.crop(bbox)
    pad = int(base_size * 0.3)
    new = Image.new("L", (img.width + 2*pad, img.height + 2*pad), 255)
    new.paste(img, (pad, pad))
    return new


def augment(img: Image.Image, rng: random.Random) -> Image.Image:
    """Apply random scanner-style augmentations."""
    # Random scale (±20%)
    scale = rng.uniform(0.85, 1.2)
    if abs(scale - 1.0) > 0.01:
        new_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
    # Optional slight blur (mimics scanner softness)
    if rng.random() < 0.5:
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))
    # Slight rotation
    if rng.random() < 0.4:
        img = img.rotate(rng.uniform(-2, 2), fillcolor=255, resample=Image.BICUBIC)
    # Salt-and-pepper noise
    if rng.random() < 0.5:
        pixels = img.load()
        n_noise = int(img.width * img.height * rng.uniform(0.001, 0.01))
        for _ in range(n_noise):
            px = rng.randrange(img.width)
            py = rng.randrange(img.height)
            pixels[px, py] = rng.choice([0, 255])
    # Threshold-ish quantize (binary-like)
    if rng.random() < 0.6:
        img = img.point(lambda p: 0 if p < 160 else 255)
    return img


def safe_filename(value: str) -> str:
    return (
        value.replace("/", "_slash_")
        .replace("#", "sharp")
        .replace("+", "aug")
        .replace(" ", "")
        .replace(":", "")
        .replace("(", "_")
        .replace(")", "_")
    )


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: synth_chord_renderer.py <out-dir>", file=sys.stderr)
        sys.exit(2)
    out_dir = sys.argv[1]
    chords = chord_strings()
    print(f"Generating {len(chords)} unique chord strings × 8 augmentations each")
    rng = random.Random(42)
    total = 0
    failed = 0
    for chord in chords:
        cls = safe_filename(chord)
        cls_dir = os.path.join(out_dir, cls)
        os.makedirs(cls_dir, exist_ok=True)
        for i in range(8):
            size = rng.choice([26, 30, 34, 38, 42])
            italic = rng.random() < 0.15
            base = render_chord(chord, base_size=size, italic=italic)
            if base is None:
                failed += 1
                continue
            img = augment(base, rng)
            out = os.path.join(cls_dir, f"synth_{i}_{size}.png")
            img.save(out)
            total += 1
    print(f"Wrote {total} synthetic crops to {out_dir}  ({failed} failed)")
    print(f"Per-class avg: {total/len(chords):.1f}")


if __name__ == "__main__":
    main()
