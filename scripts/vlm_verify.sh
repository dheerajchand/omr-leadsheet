#!/usr/bin/env bash
# VLM verification job runner for cyberpower.
#
# Subcommands:
#   launch [--songs 01,02,15] [--resume] [--force-restart]
#                                          Start verification on cyberpower; refuses
#                                          to replace a running job without
#                                          --force-restart
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
  launch [--songs 01,02,15] [--resume] [--force-restart]
                                         Sync data and start VLM verification
                                         (--force-restart kills a running job)
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
    local force_restart=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --songs)
                if [[ $# -lt 2 ]]; then
                    echo "ERROR: --songs requires a value (e.g. --songs 01,02,15)" >&2
                    usage
                fi
                songs="$2"; shift 2 ;;
            --resume) resume="--resume"; shift ;;
            --force-restart) force_restart="yes"; shift ;;
            *) echo "Unknown option: $1"; usage ;;
        esac
    done

    # --songs becomes part of a command line that a remote shell parses, so
    # accept only song-prefix characters and still shell-quote the value.
    if [[ -n "$songs" ]]; then
        local songs_re='^[A-Za-z0-9_., -]+$'
        if ! [[ "$songs" =~ $songs_re ]]; then
            echo "ERROR: --songs may contain only letters, digits, space and . , _ -" >&2
            exit 1
        fi
        songs="$(printf '%q' "$songs")"
    fi

    # Never replace a running job without being asked: check before any copy,
    # because the sync below overwrites the files the job is using.
    local session_rc=0
    ssh "$REMOTE_HOST" "tmux has-session -t ${TMUX_SESSION} 2>/dev/null" || session_rc=$?
    if [[ "$session_rc" -eq 0 ]]; then
        if [[ -z "$force_restart" ]]; then
            echo "ERROR: tmux session '${TMUX_SESSION}' is already running on ${REMOTE_HOST}." >&2
            echo "       Watch it with:  $0 attach   or   $0 status" >&2
            echo "       To kill it and start over, re-run with --force-restart." >&2
            exit 1
        fi
        echo "==> --force-restart: the running '${TMUX_SESSION}' session will be killed."
    elif [[ "$session_rc" -ne 1 ]]; then
        echo "ERROR: could not check for a running job on ${REMOTE_HOST} (exit ${session_rc})." >&2
        exit 1
    fi

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
    local py_cmd="cd ${REMOTE_WORK_DIR} && ${REMOTE_WORK_DIR}/venv/bin/python3 vlm_verify.py"
    py_cmd+=" --data-dir ${REMOTE_DATA_DIR}"
    py_cmd+=" --work-dir ${REMOTE_WORK_DIR}"
    if [[ -n "$songs" ]]; then
        py_cmd+=" --songs ${songs}"
    fi
    if [[ -n "$resume" ]]; then
        py_cmd+=" --resume"
    fi

    echo "==> Pre-flight: checking Ollama and dependencies..."
    ssh "$REMOTE_HOST" "${REMOTE_WORK_DIR}/venv/bin/python3 -c 'import requests, PIL, music21; print(\"deps OK\")'" || {
        echo "ERROR: Missing Python dependencies on ${REMOTE_HOST}."
        echo "Run:  ssh ${REMOTE_HOST} '${REMOTE_WORK_DIR}/venv/bin/pip install requests Pillow music21'"
        exit 1
    }

    echo "==> Launching in tmux session '${TMUX_SESSION}'..."
    # Reached with a live session only when --force-restart was passed.
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
