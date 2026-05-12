#!/bin/bash
# Shared configuration for the pipeline scripts. Source this file or set
# the variables in your shell before running process_song.sh / batch_all.sh.
#
# Required:
#   BOOK_DIR        Root of the project. Must contain "Individual Songs/" with
#                   one PDF per song.
#   STYLE_FILE      Path to a MuseScore .mss style file (jazz lead-sheet style).
#
# Optional (auto-detected on macOS):
#   AUDIVERIS_BIN   Path to the Audiveris CLI binary.
#   MSCORE_BIN      Path to the MuseScore 4 CLI binary.
#   VENV_PY         Python from a venv that has music21 + matplotlib installed.
#   OEMER_BIN       Path to the oemer CLI (optional second OMR backend).
#   CODE_DIR        Path to the repo's pipeline/ directory. Auto-detected
#                   from this file's location if unset.

: "${BOOK_DIR:?BOOK_DIR must be set — e.g. ~/Desktop/MySongbook}"
: "${STYLE_FILE:=$HOME/Documents/MuseScore4/Styles/MyStyle.mss}"
: "${AUDIVERIS_BIN:=/Applications/Audiveris.app/Contents/MacOS/Audiveris}"
: "${MSCORE_BIN:=/Applications/MuseScore 4.app/Contents/MacOS/mscore}"

# Auto-detect code dir from this file's location
_THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${CODE_DIR:=$_THIS_DIR/../pipeline}"
CODE_DIR="$(cd "$CODE_DIR" && pwd)"
: "${VENV_PY:=$CODE_DIR/../.venv/bin/python}"
: "${OEMER_BIN:=$CODE_DIR/../.venv/bin/oemer}"

export BOOK_DIR STYLE_FILE AUDIVERIS_BIN MSCORE_BIN VENV_PY OEMER_BIN CODE_DIR
