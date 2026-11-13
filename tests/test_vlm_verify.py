"""Tests for VLM verification components."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vlm_verify
from vlm_verify import _parse_vlm_response, _normalize_lyrics, _lyrics_match


class TestParseVlmResponse:
    def test_clean_json(self):
        text = '{"note_count": 3, "lyrics": ["Shall", "we", "dance"]}'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 3
        assert result["lyrics"] == ["Shall", "we", "dance"]

    def test_json_in_code_fence(self):
        text = '```json\n{"note_count": 2, "lyrics": ["la", "dy"]}\n```'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 2
        assert result["lyrics"] == ["la", "dy"]

    def test_regex_fallback(self):
        text = 'I see note_count: 4 and lyrics: ["one", "two", "three", "four"]'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 4
        assert result["lyrics"] == ["one", "two", "three", "four"]

    def test_empty_lyrics(self):
        text = '{"note_count": 0, "lyrics": []}'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 0
        assert result["lyrics"] == []

    def test_garbage_returns_none(self):
        text = "I don't understand what you're asking"
        result = _parse_vlm_response(text)
        assert result is None


class TestNormalizeLyrics:
    def test_strips_punctuation(self):
        assert _normalize_lyrics(["Bess,", "you"]) == ["bess", "you"]

    def test_curly_apostrophe(self):
        assert _normalize_lyrics(["‘nin’"]) == ["'nin'"]

    def test_strips_hyphens(self):
        assert _normalize_lyrics(["-ing", "songs,"]) == ["ing", "songs"]

    def test_empty_after_strip(self):
        assert _normalize_lyrics(["", ",", "-"]) == []


class TestLyricsMatch:
    def test_exact_match(self):
        assert _lyrics_match(["Shall", "we"], ["Shall", "we"])

    def test_case_insensitive(self):
        assert _lyrics_match(["shall", "we"], ["Shall", "We"])

    def test_punctuation_ignored(self):
        assert _lyrics_match(["Bess,", "you"], ["Bess", "you"])

    def test_different_count_no_match(self):
        assert not _lyrics_match(["a", "b"], ["a", "b", "c"])

    def test_different_words_no_match(self):
        assert not _lyrics_match(["hello"], ["world"])


class TestIntroOffset:
    """Verify that intro_offset is computed as aud_count - mxml_max."""

    def test_offset_positive(self):
        # Simulates: Audiveris has 65 measures, MusicXML has 61
        aud_count = 65
        mxml_max = 61
        offset = max(0, aud_count - mxml_max)
        assert offset == 4

    def test_offset_zero_when_aligned(self):
        aud_count = 40
        mxml_max = 40
        offset = max(0, aud_count - mxml_max)
        assert offset == 0

    def test_mxml_lookup_with_offset(self):
        mxml_data = {1: {"note_count": 2}, 2: {"note_count": 5}}
        offset = 4
        aud_mn = 5
        mxml_mn = aud_mn - offset
        assert mxml_mn == 1
        assert mxml_data[mxml_mn]["note_count"] == 2

    def test_intro_measures_below_offset(self):
        offset = 6
        for aud_mn in [1, 2, 3, 4, 5, 6]:
            mxml_mn = aud_mn - offset
            assert mxml_mn <= 0, "intro measures should map to non-positive mxml numbers"


# --- B2: a failed VLM call must not become a permanent cached result ----------

def _run_args(tmp_path, resume=False):
    return argparse.Namespace(
        data_dir=str(tmp_path / "data"),
        work_dir=str(tmp_path / "work"),
        ollama_url="http://stub.invalid",
        model="stub-model",
        lead_dir=None,
        omr_dir=None,
        songs=None,
        resume=resume,
        log_file=None,
    )


@pytest.fixture
def stubbed_run(tmp_path, monkeypatch):
    """Patch every collaborator of run() so no Ollama, .omr or MusicXML is touched."""
    (tmp_path / "data").mkdir()
    song = {"slug": "S1", "mxl_path": Path("s1.mxl"), "omr_path": Path("s1.omr")}
    mxml = {
        1: {"note_count": 2, "lyrics": []},
        2: {"note_count": 3, "lyrics": []},
    }
    monkeypatch.setattr(vlm_verify, "_check_ollama", lambda *a, **k: True)
    monkeypatch.setattr(vlm_verify, "_find_songs", lambda *a, **k: [song])
    monkeypatch.setattr(
        vlm_verify, "measure_bounds_from_omr", lambda p: {1: "b1", 2: "b2"}
    )
    monkeypatch.setattr(vlm_verify, "crop_measure", lambda omr, mb: b"png")
    monkeypatch.setattr(vlm_verify, "_parse_musicxml", lambda p: mxml)
    return tmp_path / "work" / "results" / "S1"


def _fake_vlm(calls, failing=()):
    """Return a _query_vlm stand-in; measures are told apart by call order."""
    def query(base_url, model, image_bytes):
        calls.append(len(calls) + 1)
        if calls[-1] in failing:
            return None
        return {"note_count": 2, "lyrics": [], "raw": "{}"}
    return query


def test_failed_vlm_call_is_not_cached_and_run_is_incomplete(
    tmp_path, monkeypatch, stubbed_run
):
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls, failing={2}))

    rc = vlm_verify.run(_run_args(tmp_path))

    assert (stubbed_run / "m1.json").exists()
    assert not (stubbed_run / "m2.json").exists(), "an error must not be cached"
    assert rc == 1
    progress = json.loads((tmp_path / "work" / "progress.json").read_text())
    assert progress["status"] == "incomplete"
    assert progress["errors"] == 1


def test_resume_retries_measures_cached_as_vlm_error(
    tmp_path, monkeypatch, stubbed_run
):
    stubbed_run.mkdir(parents=True)
    good = {"measure": 1, "vlm_note_count": 2, "musicxml_note_count": 2,
            "note_count_match": True, "vlm_lyrics": [], "lyrics_match": True}
    (stubbed_run / "m1.json").write_text(json.dumps(good))
    (stubbed_run / "m2.json").write_text(
        json.dumps({"measure": 2, "vlm_error": True})
    )
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls))

    rc = vlm_verify.run(_run_args(tmp_path, resume=True))

    assert calls == [1], "only the errored measure is re-queried"
    assert json.loads((stubbed_run / "m1.json").read_text()) == good
    assert "vlm_error" not in json.loads((stubbed_run / "m2.json").read_text())
    assert rc == 0


def test_resume_retries_unreadable_cached_result(
    tmp_path, monkeypatch, stubbed_run
):
    stubbed_run.mkdir(parents=True)
    (stubbed_run / "m1.json").write_text("{not json")
    (stubbed_run / "m2.json").write_text(json.dumps({"measure": 2}))
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls))

    vlm_verify.run(_run_args(tmp_path, resume=True))

    assert calls == [1]


def test_clean_run_is_complete_and_returns_zero(
    tmp_path, monkeypatch, stubbed_run
):
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls))

    rc = vlm_verify.run(_run_args(tmp_path))

    assert rc == 0
    progress = json.loads((tmp_path / "work" / "progress.json").read_text())
    assert progress["status"] == "complete"
    assert progress["errors"] == 0


def _report_summary(tmp_path):
    report = json.loads((tmp_path / "work" / "discrepancy_report.json").read_text())
    return report["summary"]


def test_report_says_when_the_run_was_incomplete(
    tmp_path, monkeypatch, stubbed_run
):
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls, failing={2}))

    vlm_verify.run(_run_args(tmp_path))

    summary = _report_summary(tmp_path)
    assert summary["incomplete"] is True
    assert summary["measures_expected"] == 2
    assert summary["measures_missing"] == 1
    assert summary["run_errors"] == 1
    for key in ("total_measures", "note_mismatches", "lyric_mismatches", "vlm_errors"):
        assert key in summary, f"existing key {key} must stay"


def test_report_of_a_clean_run_is_not_incomplete(
    tmp_path, monkeypatch, stubbed_run
):
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls))

    vlm_verify.run(_run_args(tmp_path))

    summary = _report_summary(tmp_path)
    assert summary["incomplete"] is False
    assert summary["measures_expected"] == 2
    assert summary["measures_missing"] == 0
    assert summary["run_errors"] == 0


def test_report_counts_a_still_failing_earlier_error_as_missing(
    tmp_path, monkeypatch, stubbed_run
):
    stubbed_run.mkdir(parents=True)
    good = {"measure": 1, "vlm_note_count": 2, "musicxml_note_count": 2,
            "note_count_match": True, "vlm_lyrics": [], "lyrics_match": True}
    (stubbed_run / "m1.json").write_text(json.dumps(good))
    (stubbed_run / "m2.json").write_text(json.dumps({"measure": 2, "vlm_error": True}))
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls, failing={1}))

    vlm_verify.run(_run_args(tmp_path, resume=True))

    summary = _report_summary(tmp_path)
    assert summary["incomplete"] is True
    assert summary["measures_missing"] == 1
    assert summary["vlm_errors"] == 1


def test_subset_run_beside_another_songs_stale_errors_is_scoped(
    tmp_path, monkeypatch, stubbed_run
):
    other = tmp_path / "work" / "results" / "S2"
    other.mkdir(parents=True)
    for n in (1, 2, 3):
        (other / f"m{n}.json").write_text(json.dumps({"measure": n, "vlm_error": True}))
    calls = []
    monkeypatch.setattr(vlm_verify, "_query_vlm", _fake_vlm(calls))

    rc = vlm_verify.run(_run_args(tmp_path))

    summary = _report_summary(tmp_path)
    assert rc == 0
    assert summary["incomplete"] is False, "S1 finished cleanly"
    assert summary["songs_in_run"] == ["S1"]
    assert summary["vlm_errors"] == 3, "whole results directory, unchanged meaning"
    assert summary["vlm_errors_outside_run"] == 3
    assert summary["total_measures"] == 5
    assert summary["measures_expected"] == 2


def test_report_without_run_information_says_incomplete_is_unknown(tmp_path):
    results = tmp_path / "results"
    (results / "S1").mkdir(parents=True)
    (results / "S1" / "m1.json").write_text(json.dumps({"measure": 1, "vlm_error": True}))

    vlm_verify._generate_report(results, {}, tmp_path)

    summary = json.loads((tmp_path / "discrepancy_report.json").read_text())["summary"]
    assert summary["incomplete"] is None
    assert summary["songs_in_run"] is None
    assert summary["vlm_errors_outside_run"] is None
    assert summary["vlm_errors"] == 1


def test_resume_help_describes_the_retry_behaviour(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vlm_verify.py", "--help"])

    with pytest.raises(SystemExit):
        vlm_verify.main()

    help_text = " ".join(capsys.readouterr().out.split())
    assert "re-query measures whose result is missing, unreadable or an earlier error" in help_text


@pytest.mark.parametrize("run_result", [0, 1])
def test_main_exits_with_the_code_run_returns(monkeypatch, run_result):
    monkeypatch.setattr(vlm_verify, "run", lambda args: run_result)
    monkeypatch.setattr(
        sys, "argv", ["vlm_verify.py", "--data-dir", "d", "--work-dir", "w"]
    )

    with pytest.raises(SystemExit) as exc:
        vlm_verify.main()

    assert exc.value.code == run_result


# --- B4: relaunch must not kill a running job; --songs must be quoted ---------

SH = Path(__file__).resolve().parents[1] / "scripts" / "vlm_verify.sh"

_STUB = """#!/bin/bash
printf '%s\\n' "$(basename "$0") $*" >> "$STUB_LOG"
case "$*" in
  *"import requests"*) exit "${STUB_PREFLIGHT_RC:-0}" ;;
esac
[ "$(basename "$0")" = "${STUB_FAIL_CMD:-}" ] && exit 1
case "$*" in
  *has-session*)
    if [ -n "${STUB_HAS_SESSION_SEQ:-}" ]; then
      n=0
      [ -f "$STUB_COUNT" ] && n=$(<"$STUB_COUNT")
      n=$((n + 1))
      printf '%s' "$n" > "$STUB_COUNT"
      IFS=, read -r -a seq <<< "$STUB_HAS_SESSION_SEQ"
      i=$((n - 1))
      [ "$i" -ge "${#seq[@]}" ] && i=$((${#seq[@]} - 1))
      exit "${seq[$i]}"
    fi
    [ "${STUB_TMUX_RUNNING:-0}" = "1" ] && exit 0 || exit 1 ;;
esac
exit 0
"""


@pytest.fixture
def launch(tmp_path):
    """Run `vlm_verify.sh launch` with stub ssh/scp/rsync; nothing leaves the machine.

    PATH holds only the stub directory and symlinks to the few tools the script
    needs, so a missing stub fails the run instead of reaching a real ssh.
    """
    if shutil.which("bash") is None:
        pytest.skip("bash not available; install bash to run the vlm_verify.sh tests")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("ssh", "scp", "rsync"):
        stub = stubs / name
        stub.write_text(_STUB)
        stub.chmod(0o755)
    for name in ("dirname", "basename", "cat", "mkdir"):
        real = shutil.which(name)
        if real is None:
            pytest.skip(f"{name} not found; cannot build the stub PATH")
        (stubs / name).symlink_to(real)
    log = tmp_path / "stub.log"
    log.write_text("")

    def run_launch(*args, running=False, has_session=None,
                   preflight_rc=None, fail_cmd=None):
        """Run launch against the stubs.

        ``has_session``: comma-separated exit codes for successive has-session calls.
        ``preflight_rc``: exit code of the dependency pre-flight ssh call.
        ``fail_cmd``: name of a stub (e.g. ``scp``) that always fails.
        """
        env = {
            "PATH": str(stubs),
            "HOME": str(tmp_path),
            "STUB_LOG": str(log),
            "STUB_COUNT": str(tmp_path / "has-session.count"),
            "STUB_TMUX_RUNNING": "1" if running else "0",
            "VLM_REMOTE_HOST": "stub-host.invalid",
        }
        if has_session is not None:
            env["STUB_HAS_SESSION_SEQ"] = has_session
        if preflight_rc is not None:
            env["STUB_PREFLIGHT_RC"] = str(preflight_rc)
        if fail_cmd is not None:
            env["STUB_FAIL_CMD"] = fail_cmd
        proc = subprocess.run(
            [shutil.which("bash"), str(SH), "launch", *args],
            env=env, capture_output=True, text=True, timeout=30,
        )
        return proc, log.read_text().splitlines()

    return run_launch


def test_script_passes_bash_syntax_check():
    if shutil.which("bash") is None:
        pytest.skip("bash not available; install bash to run the vlm_verify.sh tests")
    proc = subprocess.run(
        [shutil.which("bash"), "-n", str(SH)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_launch_refuses_to_replace_a_running_job(launch):
    proc, calls = launch(running=True)

    assert proc.returncode != 0
    assert "--force-restart" in proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" not in joined
    assert "new-session" not in joined
    assert not any(c.startswith(("scp", "rsync")) for c in calls), (
        "nothing may be copied over a running job"
    )


def test_launch_replaces_a_running_job_only_with_force_restart(launch):
    # Running at the first check, gone after the kill.
    proc, calls = launch("--force-restart", has_session="0,1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" in joined
    assert "new-session" in joined


def test_force_restart_kills_the_job_before_anything_is_copied(launch):
    proc, calls = launch("--force-restart", has_session="0,1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    kills = [i for i, c in enumerate(calls) if "kill-session" in c]
    copies = [i for i, c in enumerate(calls) if c.startswith(("scp", "rsync"))]
    assert len(kills) == 1
    assert copies, "the sync should still run after the kill"
    assert kills[0] < copies[0], "a live job's files must not be overwritten"


def test_failing_preflight_makes_no_kill_even_with_force_restart(launch):
    proc, calls = launch("--force-restart", has_session="0,1", preflight_rc=1)

    assert proc.returncode != 0
    assert "Missing Python dependencies" in proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" not in joined, "the old job must survive a failed pre-flight"
    assert "new-session" not in joined
    assert not any(c.startswith(("scp", "rsync")) for c in calls)
    assert "was killed" not in proc.stdout + proc.stderr


def test_force_restart_aborts_before_copying_when_the_session_survives_the_kill(launch):
    # Still alive at the re-check after the kill (rc 0 both times).
    proc, calls = launch("--force-restart", has_session="0,0")

    assert proc.returncode != 0
    assert "still running" in proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert joined.count("kill-session") == 1
    assert "new-session" not in joined
    assert not any(c.startswith(("scp", "rsync")) for c in calls), (
        "a surviving job's files must not be overwritten"
    )
    assert "was killed" not in proc.stdout + proc.stderr


def test_force_restart_aborts_when_the_kill_cannot_be_confirmed(launch):
    proc, calls = launch("--force-restart", has_session="0,255")

    assert proc.returncode != 0
    assert "could not confirm the kill" in proc.stdout + proc.stderr
    assert not any(c.startswith(("scp", "rsync")) for c in calls)
    assert not any("new-session" in c for c in calls)


def test_sync_failure_after_a_forced_kill_says_nothing_is_running(launch):
    proc, calls = launch("--force-restart", has_session="0,1", fail_cmd="scp")

    assert proc.returncode != 0
    output = proc.stdout + proc.stderr
    assert "was killed and no new job was started" in output
    assert "nothing is running" in output
    assert any("kill-session" in c for c in calls)
    assert not any("new-session" in c for c in calls)


def test_a_successful_forced_launch_prints_no_killed_note(launch):
    proc, calls = launch("--force-restart", has_session="0,1")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "was killed and no new job was started" not in proc.stdout + proc.stderr


def test_launch_aborts_without_killing_when_a_job_appears_during_the_sync(launch):
    # First check: no session (rc 1). Re-check before new-session: one exists (rc 0).
    proc, calls = launch(has_session="1,0")

    assert proc.returncode != 0
    assert "appeared" in proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" not in joined
    assert "new-session" not in joined
    assert any(c.startswith("scp") for c in calls), "the first check passed, so the sync ran"


def test_launch_aborts_when_the_recheck_cannot_reach_tmux(launch):
    proc, calls = launch(has_session="1,255")

    assert proc.returncode != 0
    assert "could not re-check" in proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" not in joined
    assert "new-session" not in joined


def test_launch_starts_normally_when_no_job_is_running(launch):
    proc, calls = launch("--resume")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert any("new-session" in c and "--resume" in c for c in calls)


@pytest.mark.parametrize(
    "songs",
    ["01;touch /tmp/pwned", "$(id)", "`id`", "a'b", "a b|c", "x&y", "a\nb"],
)
def test_launch_rejects_shell_metacharacters_in_songs(launch, songs):
    proc, calls = launch("--songs", songs)

    assert proc.returncode != 0
    assert "--songs may contain only" in proc.stdout + proc.stderr
    assert not any("new-session" in c for c in calls)
    assert not any(c.startswith(("scp", "rsync")) for c in calls)


def test_launch_requires_a_value_for_songs(launch):
    proc, calls = launch("--songs")

    assert proc.returncode != 0
    assert "requires a value" in proc.stdout + proc.stderr
    assert calls == []


def test_launch_quotes_songs_for_the_remote_shell(launch):
    songs = "Shall We,01"
    proc, calls = launch("--songs", songs)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    started = [c for c in calls if "new-session" in c]
    assert len(started) == 1
    # printf %q output differs between bash versions, so ask the same bash.
    quoted = subprocess.run(
        [shutil.which("bash"), "-c", 'printf %q "$1"', "_", songs],
        capture_output=True, text=True, check=True,
    ).stdout
    assert quoted != songs, "the value must actually be escaped"
    assert f"--songs {quoted}" in started[0]
