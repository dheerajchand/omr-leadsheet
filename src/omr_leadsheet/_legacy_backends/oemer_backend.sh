#!/bin/bash
# Run oemer over a PDF, producing one merged MusicXML.
#
# oemer has a hard assertion `track_nums == 2` that fails on 3-staff
# piano-vocal systems. To work around this we (optionally) paint the
# piano LH staff white on each page before feeding to oemer, using
# Audiveris's .omr as the source of staff positions.
#
# Usage: oemer_backend.sh <pdf> <out.musicxml> [--omr <path>]
#
# If --omr is given, staff-crop pre-processing is applied. Otherwise
# raw PNGs go to oemer (original behaviour).

set -euo pipefail

PDF="$1"
OUT="$2"
OMR=""
if [[ "${3:-}" == "--omr" ]]; then
    OMR="$4"
fi

BOOK="$BOOK_DIR"
OEMER="$OEMER_BIN"
PY="$VENV_PY"

WORK=$(mktemp -d)
trap "rm -rf '$WORK'" EXIT

# 1. Render pages to 400 DPI PNG
pdftoppm -r 400 -png "$PDF" "$WORK/p"

# 1b. Optional: paint piano-LH staves white so oemer doesn't hit its
# 2-track assertion on piano-vocal systems.
FEED_DIR="$WORK"
if [[ -n "$OMR" && -f "$OMR" ]]; then
    PREP_DIR="$WORK/prep"
    mkdir -p "$PREP_DIR"
    "$PY" "$CODE_DIR/backends/oemer_prep.py" "$OMR" "$WORK" "$PREP_DIR" \
        >>"$WORK/oemer.log" 2>&1 || echo "  (staff-prep failed, using raw PNGs)"
    if [[ -n "$(ls -A "$PREP_DIR" 2>/dev/null)" ]]; then
        FEED_DIR="$PREP_DIR"
    fi
fi

# 2. Run oemer on each prepared page (serial - onnxruntime eats a lot of RAM)
for png in "$FEED_DIR"/p-*.png; do
    pagenum=$(basename "$png" .png | sed 's/p-//')
    echo "  [oemer] page $pagenum"
    "$OEMER" -d "$png" -o "$WORK" >>"$WORK/oemer.log" 2>&1 || echo "    (page $pagenum failed, skipping)"
done

# 3. Concatenate the per-page MusicXMLs via music21
"$PY" "$CODE_DIR/backends/concat_oemer.py" "$WORK" "$OUT"
