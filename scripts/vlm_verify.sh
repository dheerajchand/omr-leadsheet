#!/usr/bin/env bash
# VLM verification job runner for cyberpower.
#
# Subcommands:
#   launch [--songs 01,02,15] [--resume]  Start verification on cyberpower
#   status                                 Check progress
#   results [--dest ./vlm_results]         Download results
#   attach                                 Attach to tmux session
#
# Requires SSH host alias "cyberpower" in ~/.ssh/config.
# Ticket: #106

set -euo pipefail

REMOTE_HOST="${VLM_REMOTE_HOST:-cyberpower}"
REMOTE_WORK_DIR="${VLM_REMOTE_WORK_DIR:-\$HOME/omr-vlm-verify}"
REMOTE_DATA_DIR="${VLM_REMOTE_DATA_DIR:-\$HOME/omr-vlm-verify/data}"
TMUX_SESSION="vlm_verify"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    cat <<EOF
Usage: $0 <command> [options]

Commands:
  launch [--songs 01,02,15] [--resume]  Sync data and start VLM verification
  status                                 Show progress.json from remote
  results [--dest DIR]                   Download results to local machine
  attach                                 Attach to tmux session on remote

Environment:
  VLM_REMOTE_HOST      SSH host (default: cyberpower)
  VLM_REMOTE_WORK_DIR  Remote work dir (default: ~/omr-vlm-verify)
  VLM_REMOTE_DATA_DIR  Remote data dir (default: ~/omr-vlm-verify/data)
EOF
    exit 1
}

cmd_launch() {
    local songs=""
    local resume=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --songs) songs="$2"; shift 2 ;;
            --resume) resume="--resume"; shift ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    echo "==> Syncing scripts to ${REMOTE_HOST}..."
    ssh "$REMOTE_HOST" "mkdir -p ${REMOTE_WORK_DIR} ${REMOTE_DATA_DIR}"
    scp "$SCRIPT_DIR/vlm_verify.py" "${REMOTE_HOST}:${REMOTE_WORK_DIR}/"
    # Sync the barline module
    ssh "$REMOTE_HOST" "mkdir -p ${REMOTE_WORK_DIR}/src/omr_leadsheet"
    scp "$REPO_ROOT/src/omr_leadsheet/barline.py" \
        "${REMOTE_HOST}:${REMOTE_WORK_DIR}/src/omr_leadsheet/"
    scp "$REPO_ROOT/src/omr_leadsheet/__init__.py" \
        "${REMOTE_HOST}:${REMOTE_WORK_DIR}/src/omr_leadsheet/" 2>/dev/null || \
        ssh "$REMOTE_HOST" "touch ${REMOTE_WORK_DIR}/src/omr_leadsheet/__init__.py"

    echo "==> Syncing data (MusicXML, LeadSheets, song_truth)..."
    rsync -avz --progress \
        "$REPO_ROOT/data/MusicXML/" "${REMOTE_HOST}:${REMOTE_DATA_DIR}/MusicXML/"
    rsync -avz --progress \
        "$REPO_ROOT/data/LeadSheets/" "${REMOTE_HOST}:${REMOTE_DATA_DIR}/LeadSheets/"
    rsync -avz --progress \
        "$REPO_ROOT/data/song_truth/" "${REMOTE_HOST}:${REMOTE_DATA_DIR}/song_truth/"

    # Build the python command
    local py_cmd="cd ${REMOTE_WORK_DIR} && python3 vlm_verify.py"
    py_cmd+=" --data-dir ${REMOTE_DATA_DIR}"
    py_cmd+=" --work-dir ${REMOTE_WORK_DIR}"
    if [[ -n "$songs" ]]; then
        py_cmd+=" --songs ${songs}"
    fi
    if [[ -n "$resume" ]]; then
        py_cmd+=" --resume"
    fi

    echo "==> Pre-flight: checking Ollama and dependencies..."
    ssh "$REMOTE_HOST" "python3 -c 'import requests, PIL; print(\"deps OK\")'" || {
        echo "ERROR: Missing Python dependencies on ${REMOTE_HOST}."
        echo "Run:  ssh ${REMOTE_HOST} 'pip3 install requests Pillow'"
        exit 1
    }

    echo "==> Launching in tmux session '${TMUX_SESSION}'..."
    # Kill existing session if any
    ssh "$REMOTE_HOST" "tmux kill-session -t ${TMUX_SESSION} 2>/dev/null || true"
    ssh "$REMOTE_HOST" "tmux new-session -d -s ${TMUX_SESSION} '${py_cmd}; echo; echo \"=== DONE ===\"; read'"

    echo "==> Job launched on ${REMOTE_HOST} in tmux session '${TMUX_SESSION}'"
    echo "    Check progress:  $0 status"
    echo "    Attach:          $0 attach"
    echo "    Get results:     $0 results"
}

cmd_status() {
    echo "==> Fetching progress from ${REMOTE_HOST}..."
    local progress
    progress=$(ssh "$REMOTE_HOST" "cat ${REMOTE_WORK_DIR}/progress.json 2>/dev/null" || echo "")

    if [[ -z "$progress" ]]; then
        echo "No progress.json found. Job may not have started yet."
        # Check if tmux session exists
        if ssh "$REMOTE_HOST" "tmux has-session -t ${TMUX_SESSION} 2>/dev/null"; then
            echo "tmux session '${TMUX_SESSION}' exists (job may be initializing)."
        else
            echo "No tmux session found."
        fi
        return
    fi

    echo "$progress" | python3 -c "
import json, sys
p = json.load(sys.stdin)
print(f\"Status:     {p['status']}\")
print(f\"Song:       {p.get('current_song', 'N/A')} (m{p.get('current_measure', '?')})\")
print(f\"Progress:   {p.get('songs_completed', 0)}/{p.get('songs_total', '?')} songs, {p.get('measures_completed', 0)}/{p.get('measures_total', '?')} measures\")
print(f\"Errors:     {p.get('errors', 0)}\")
print(f\"Started:    {p.get('started', 'N/A')}\")
print(f\"Updated:    {p.get('last_update', 'N/A')}\")
pct = 100 * p.get('measures_completed', 0) / max(p.get('measures_total', 1), 1)
print(f\"Completion: {pct:.1f}%\")
"
}

cmd_results() {
    local dest="./vlm_results"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dest) dest="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    echo "==> Downloading results to ${dest}..."
    mkdir -p "$dest"
    rsync -avz --progress \
        "${REMOTE_HOST}:${REMOTE_WORK_DIR}/results/" "${dest}/results/"
    scp "${REMOTE_HOST}:${REMOTE_WORK_DIR}/progress.json" "${dest}/" 2>/dev/null || true
    scp "${REMOTE_HOST}:${REMOTE_WORK_DIR}/discrepancy_report.json" "${dest}/" 2>/dev/null || true
    scp "${REMOTE_HOST}:${REMOTE_WORK_DIR}/vlm_verify.log" "${dest}/" 2>/dev/null || true
    echo "==> Results downloaded to ${dest}"
}

cmd_attach() {
    echo "==> Attaching to tmux session '${TMUX_SESSION}' on ${REMOTE_HOST}..."
    ssh -t "$REMOTE_HOST" "tmux attach -t ${TMUX_SESSION}"
}

# Main dispatch
if [[ $# -lt 1 ]]; then
    usage
fi

command="$1"
shift

case "$command" in
    launch)  cmd_launch "$@" ;;
    status)  cmd_status "$@" ;;
    results) cmd_results "$@" ;;
    attach)  cmd_attach "$@" ;;
    *)       echo "Unknown command: $command"; usage ;;
esac
