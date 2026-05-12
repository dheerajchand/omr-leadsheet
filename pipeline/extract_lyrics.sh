#!/bin/bash
# Extract clean lyric text from a piano-vocal PDF.
# Usage: extract_lyrics.sh <input.pdf> <output.txt>
#
# Pipeline: pdftoppm at 400 DPI → tesseract PSM 6 → filter lines that look
# like prose (alpha-heavy) and drop music-notation noise.

set -eu

IN="$1"
OUT="$2"
TMP=$(mktemp -d)
trap "rm -rf '$TMP'" EXIT

pdftoppm -r 400 -png "$IN" "$TMP/page"

RAW="$TMP/raw.txt"
: > "$RAW"
for p in "$TMP"/page-*.png; do
    tesseract "$p" - --psm 6 2>/dev/null >> "$RAW"
    echo >> "$RAW"
done

# Keep lines that look like lyrics: at least 10 alpha chars AND more alpha
# chars than non-alpha chars. Drop duplicate consecutive lines too.
python3 - "$RAW" "$OUT" <<'PY'
import sys, re
raw_path, out_path = sys.argv[1], sys.argv[2]
with open(raw_path) as f:
    raw = f.read().splitlines()

WORD = re.compile(r"[A-Za-z]+")

# Load the system dictionary. Hyphenated lyric fragments ("ro-mance") get
# tested piecewise, so individual syllables work too.
with open("/usr/share/dict/words") as f:
    DICT = {w.strip().lower() for w in f if w.strip()}
# Add common lyric syllables that aren't English words on their own
DICT.update({
    "pa", "ja", "jah", "po", "tah", "ma", "mah", "to", "oh", "im", "id",
    "dont", "lets", "oyst", "ersters", "erst", "nil", "nel", "sas", "rel",
    "ril", "ee", "ny", "eye", "nee", "ther", "ty", "lawf", "awf", "ings",
    "nessknowswhat", "dontknowwhere",  # OCR-merged but recognizable
})

def real_words(line: str) -> int:
    """Count dictionary words of length >= 4 in the line."""
    count = 0
    for tok in WORD.findall(line.lower()):
        if len(tok) >= 4 and tok in DICT:
            count += 1
    return count

def looks_like_lyrics(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # Require at least 2 real English words of length >= 4.
    # Noise lines almost never meet this.
    if real_words(s) < 2:
        return False
    # Reject lines that are mostly non-letter characters
    alpha = sum(1 for c in s if c.isalpha())
    if alpha < len(s) * 0.4:
        return False
    # Lyrics are mostly lowercase; all-caps noise lines should be dropped
    # (but keep all-caps *short* lines like the title, handled separately).
    lower = sum(1 for c in s if c.islower())
    upper = sum(1 for c in s if c.isupper())
    if upper > lower and len(s) > 40:
        return False
    return True

kept = []
last = None
for line in raw:
    cleaned = line.strip()
    if looks_like_lyrics(cleaned) and cleaned != last:
        kept.append(cleaned)
        last = cleaned

with open(out_path, "w") as f:
    for k in kept:
        f.write(k + "\n")
PY
