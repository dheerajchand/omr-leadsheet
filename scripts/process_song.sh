#!/bin/bash

# Load shared configuration
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# Process one piano-vocal PDF through the full pipeline:
#   1. Audiveris OMR → .omr + .mxl (cached; skip if .mxl exists)
#   2. Tesseract lyric extraction → Lyrics/NN.txt (cached)
#   3. Reducer (music21) → LeadSheets/NN - lead.musicxml
#   4. Chord-diff insert (from .omr) → LeadSheets/NN - lead.chords.musicxml
#   5. Head recovery (from .omr) → LeadSheets/NN - lead.heads.musicxml
#   6. NW spell-check lyrics → LeadSheets/NN - lead.corrected.musicxml
#   7. MuseScore style + export → LeadSheets/NN.mscz
#   8. Suspicious-measure report → LeadSheets/NN.review.md
#
# Usage: process_song.sh <path-to-song.pdf> [--force]

set -euo pipefail

# Alias env-exported names to the script's older variable conventions so
# the bulk of the script can stay as-is.
BOOK="$BOOK_DIR"
CODE="$CODE_DIR"
PY="$VENV_PY"
AUDIVERIS="$AUDIVERIS_BIN"
MSCORE="$MSCORE_BIN"
STYLE="$STYLE_FILE"

FORCE=0
WITH_OEMER=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --with-oemer) WITH_OEMER=1 ;;
        *) ARGS+=("$arg") ;;
    esac
done
set -- "${ARGS[@]}"

PDF="$1"
if [[ ! -f "$PDF" ]]; then
    echo "ERROR: not a file: $PDF" >&2
    exit 1
fi

BASE="$(basename "$PDF" .pdf)"
MXL_DIR="$BOOK_DIR/MusicXML"
LYR_DIR="$BOOK_DIR/Lyrics"
# Per-song output folder keeps the tree tidy (30+ songs × 6+ files each).
OUT_DIR="$BOOK_DIR/LeadSheets/$BASE"
mkdir -p "$MXL_DIR" "$LYR_DIR" "$OUT_DIR"

OMR="$MXL_DIR/$BASE.omr"
MXL="$MXL_DIR/$BASE.mxl"
TXT="$LYR_DIR/$BASE.txt"
LEAD="$OUT_DIR/$BASE - lead.musicxml"
LEAD_CHORDS="$OUT_DIR/$BASE - lead.chords.musicxml"
LEAD_HEADS="$OUT_DIR/$BASE - lead.heads.musicxml"
LEAD_CORR="$OUT_DIR/$BASE - lead.corrected.musicxml"
MSCZ="$OUT_DIR/$BASE.mscz"
REVIEW="$OUT_DIR/$BASE.review.md"
PIPELINE_LOG="$OUT_DIR/_pipeline.log"

# Tee all output to a per-song log (so the per-song folder is self-contained)
exec > >(tee -a "$PIPELINE_LOG") 2>&1
echo "--- $(date -u +%FT%TZ) pipeline run: $BASE ---"

step() { echo "  [$BASE] $1"; }

# 1. OMR (cached; fall back to 400 DPI re-render if initial OMR fails)
if [[ $FORCE -eq 1 || ! -f "$MXL" ]]; then
    step "running Audiveris OMR"
    "$AUDIVERIS" -batch -export -output "$MXL_DIR" "$PDF" >/dev/null 2>&1 || true
    if [[ ! -f "$MXL" ]]; then
        step "OMR at 200 DPI failed, retrying at 400 DPI"
        TMPDIR=$(mktemp -d)
        pdftoppm -r 400 -png "$PDF" "$TMPDIR/page" >/dev/null 2>&1
        if command -v magick >/dev/null 2>&1; then
            magick "$TMPDIR"/page-*.png "$TMPDIR/hi.pdf" >/dev/null 2>&1
            "$AUDIVERIS" -batch -export -output "$MXL_DIR" "$TMPDIR/hi.pdf" >/dev/null 2>&1 || true
            [[ -f "$MXL_DIR/hi.mxl" ]] && mv "$MXL_DIR/hi.mxl" "$MXL"
            [[ -f "$MXL_DIR/hi.omr" ]] && mv "$MXL_DIR/hi.omr" "$OMR"
        fi
        rm -rf "$TMPDIR"
    fi
    if [[ ! -f "$MXL" ]]; then
        echo "  [!] OMR failed at both 200 and 400 DPI — skipping" >&2
        exit 1
    fi
else
    step "OMR cached"
fi

# 1b. Clean up tuplets & other import blockers in the raw .mxl
MXL_CLEAN="$MXL_DIR/$BASE.clean.xml"
if [[ $FORCE -eq 1 || ! -f "$MXL_CLEAN" ]]; then
    step "cleaning raw MusicXML (tuplet balance, etc.)"
    "$PY" "$CODE/cleanup_mxl.py" "$MXL" "$MXL_CLEAN" >/dev/null
fi

# 2. Tesseract lyrics (cached)
if [[ $FORCE -eq 1 || ! -f "$TXT" ]]; then
    step "extracting lyrics via tesseract"
    "$CODE/extract_lyrics.sh" "$PDF" "$TXT"
else
    step "lyrics cached"
fi

# 3. Reducer (feeds from the cleaned XML, not the raw .mxl)
step "reducing to lead sheet"
"$PY" "$CODE/reduce_to_lead.py" "$MXL_CLEAN" "$LEAD" --keep-verse >/dev/null

# Determine intro offset for chord-diff measure-offset
INTRO_DROPPED=$("$PY" - <<EOF
from music21 import converter
s = converter.parse("$MXL_CLEAN")
# Prefer the part with lyrics; fall back to the first part for piano solos
best = s.parts[0]
best_lyrics = -1
from music21 import note
for p in s.parts:
    c = sum(1 for n in p.recurse().notes if isinstance(n, note.Note) and n.lyrics)
    if c > best_lyrics:
        best_lyrics, best = c, p
intro = 0
for m in best.getElementsByClass('Measure'):
    if not list(m.recurse().notes):
        intro += 1
    else:
        break
print(intro)
EOF
)
OFFSET="-$INTRO_DROPPED"

# 4. Chord-diff insertion
step "recovering chord symbols from .omr (offset $OFFSET)"
"$PY" "$CODE/chord_diff.py" "$OMR" "$MXL" \
    --measure-offset "$OFFSET" \
    --insert-into "$LEAD" --out "$LEAD_CHORDS" >/dev/null

# 5. Head recovery (usually a no-op; included for completeness)
step "recovering note-heads from .omr"
"$PY" "$CODE/head_recovery.py" "$OMR" "$LEAD_CHORDS" "$LEAD_HEADS" \
    --measure-offset "$OFFSET" >/dev/null 2>&1 || cp "$LEAD_CHORDS" "$LEAD_HEADS"

# 6. NW spell-check lyrics
if [[ -f "$TXT" ]]; then
    step "NW-aligning lyrics against tesseract"
    "$PY" "$CODE/spell_check_lyrics.py" "$LEAD_HEADS" "$TXT" "$LEAD_CORR" >/dev/null
else
    cp "$LEAD_HEADS" "$LEAD_CORR"
fi

# 6a. Optional: second-OMR pass with oemer and content-based merge.
# Non-fatal on failure — oemer has a hard requirement of <=2 staves per
# system that piano-vocal scores routinely violate; we take what we get.
if [[ $WITH_OEMER -eq 1 ]]; then
    OEMER_MXL="$BOOK_DIR/MusicXML-oemer/$BASE.musicxml"
    mkdir -p "$BOOK_DIR/MusicXML-oemer"
    if [[ $FORCE -eq 1 || ! -f "$OEMER_MXL" ]]; then
        step "running oemer (second OMR backend, with LH-staff prep)"
        "$CODE/backends/oemer_backend.sh" "$PDF" "$OEMER_MXL" --omr "$OMR" \
            >>"$OUT_DIR/_oemer.log" 2>&1 \
            || echo "  (oemer failed or partial — see $OUT_DIR/_oemer.log)"
    else
        step "oemer cached"
    fi
    if [[ -f "$OEMER_MXL" ]]; then
        step "merging primary (Audiveris) + oemer by content alignment"
        MERGED="$OUT_DIR/$BASE - lead.merged.musicxml"
        "$PY" "$CODE/merge_omr.py" "$LEAD_CORR" "$OEMER_MXL" "$MERGED" \
            | tee -a "$OUT_DIR/_merge.log" || true
        [[ -f "$MERGED" ]] && LEAD_CORR="$MERGED"
    fi
fi

# 6b. Final MusicXML cleanup: strip tuplet issues music21 may have re-introduced
LEAD_CLEAN="$OUT_DIR/$BASE - lead.final.musicxml"
"$PY" "$CODE/cleanup_mxl.py" "$LEAD_CORR" "$LEAD_CLEAN" >/dev/null

# 7. Apply style and export .mscz. If MuseScore rejects the file, retry with
# tuplets aggressively stripped (music21 sometimes emits tuplet markup that
# MuseScore parses but silently refuses to import).
step "applying Dheeraj-Jazz style → .mscz"
rm -f "$MSCZ"
"$MSCORE" -S "$STYLE" -o "$MSCZ" "$LEAD_CLEAN" >/dev/null 2>&1 || true
if [[ ! -f "$MSCZ" ]]; then
    step "MuseScore rejected output, retrying with tuplets stripped"
    LEAD_NOTUP="$OUT_DIR/$BASE - lead.notuplets.musicxml"
    "$PY" "$CODE/cleanup_mxl.py" --aggressive "$LEAD_CORR" "$LEAD_NOTUP" >/dev/null
    "$MSCORE" -S "$STYLE" -o "$MSCZ" "$LEAD_NOTUP" >/dev/null 2>&1 || true
fi
if [[ ! -f "$MSCZ" ]]; then
    echo "  [!] MuseScore failed to produce .mscz even without tuplets" >&2
    exit 1
fi

# 8. Suspicious-measure report (markdown + interactive HTML)
step "writing review report"
{
    echo "# Review: $BASE"
    echo
    "$PY" "$CODE/suspicious_measures.py" --markdown "$LEAD_CORR"
} > "$REVIEW"
"$PY" "$CODE/review_tool.py" "$OUT_DIR" >/dev/null 2>&1 || true

echo "  [$BASE] done → $MSCZ"
