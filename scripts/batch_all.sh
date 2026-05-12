#!/bin/bash

# Load shared configuration
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# Run process_song.sh over every PDF in Individual Songs/.
# Usage: batch_all.sh [--force] [--only <glob>]

set -euo pipefail

BOOK="$BOOK_DIR"
CODE="$CODE_DIR"
IN_DIR="$BOOK_DIR/Individual Songs"
LOG="$BOOK_DIR/LeadSheets/_batch.log"

mkdir -p "$BOOK_DIR/LeadSheets"
: > "$LOG"

FORCE=""
WITH_OEMER=""
GLOB="*.pdf"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE="--force"; shift ;;
        --with-oemer) WITH_OEMER="--with-oemer"; shift ;;
        --only) GLOB="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

count=0
failed=0
echo "Starting batch at $(date)" | tee -a "$LOG"
# shellcheck disable=SC2206
FILES=("$IN_DIR"/$GLOB)
for pdf in "${FILES[@]}"; do
    [[ -f "$pdf" ]] || continue
    count=$((count + 1))
    echo "===== [$count] $(basename "$pdf") =====" | tee -a "$LOG"
    if "$CODE/process_song.sh" "$pdf" $FORCE $WITH_OEMER >>"$LOG" 2>&1; then
        echo "  ✓ ok" | tee -a "$LOG"
    else
        failed=$((failed + 1))
        echo "  ✗ FAILED (see log)" | tee -a "$LOG"
    fi
done
echo "Done at $(date): $count processed, $failed failed" | tee -a "$LOG"
