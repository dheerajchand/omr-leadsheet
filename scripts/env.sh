#!/bin/bash
# Shared configuration for the pipeline scripts. Source this file or set
# the variables in your shell before running process_song.sh / batch_all.sh.
#
# Required:
#   BOOK_DIR        Root of the project. Must contain "Individual Songs/" with
#                   one PDF per song.
#   STYLE_FILE      Path to a MuseScore .mss style file (jazz lead-sheet style).
#
# Optional (auto-detected):
#   AUDIVERIS_BIN   Path to the Audiveris CLI binary.
#   MSCORE_BIN      Path to the MuseScore 4 CLI binary.
#   VENV_PY         Python with music21 + matplotlib (+ torch for classifier).
#                   Auto-detect order: $VENV_PY → pyenv → repo .venv → system.
#   OEMER_BIN       oemer CLI (optional second OMR backend). Auto-detected
#                   from the same dir as VENV_PY.
#   CODE_DIR        Path to the repo's pipeline/ directory. Auto-detected.

: "${BOOK_DIR:?BOOK_DIR must be set — e.g. ~/Desktop/MySongbook}"
: "${STYLE_FILE:=$HOME/Documents/MuseScore4/Styles/MyStyle.mss}"
: "${AUDIVERIS_BIN:=/Applications/Audiveris.app/Contents/MacOS/Audiveris}"
: "${MSCORE_BIN:=/Applications/MuseScore 4.app/Contents/MacOS/mscore}"

# Auto-detect code dir from this file's location
_THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${CODE_DIR:=$_THIS_DIR/../pipeline}"
CODE_DIR="$(cd "$CODE_DIR" && pwd)"

# Auto-detect Python in priority order:
#   1. $VENV_PY if already set
#   2. pyenv's currently-active interpreter (handles pyenv-virtualenv shims)
#   3. project-local .venv/ (fresh-clone default)
#   4. system python3 / python
if [[ -z "${VENV_PY:-}" ]]; then
    _pyenv_py=""
    if command -v pyenv >/dev/null 2>&1; then
        _pyenv_py="$(pyenv which python 2>/dev/null || true)"
    fi
    if [[ -n "$_pyenv_py" && -x "$_pyenv_py" ]]; then
        VENV_PY="$_pyenv_py"
    elif [[ -x "$CODE_DIR/../.venv/bin/python" ]]; then
        VENV_PY="$CODE_DIR/../.venv/bin/python"
    else
        VENV_PY="$(command -v python3 || command -v python || echo python3)"
    fi
fi

# oemer lives next to the python interpreter that has it installed
if [[ -z "${OEMER_BIN:-}" ]]; then
    _py_dir="$(dirname "$VENV_PY")"
    if [[ -x "$_py_dir/oemer" ]]; then
        OEMER_BIN="$_py_dir/oemer"
    else
        OEMER_BIN="$(command -v oemer || echo oemer)"
    fi
fi

export BOOK_DIR STYLE_FILE AUDIVERIS_BIN MSCORE_BIN VENV_PY OEMER_BIN CODE_DIR
