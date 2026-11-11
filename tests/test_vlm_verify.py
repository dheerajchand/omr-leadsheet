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
  *has-session*) [ "${STUB_TMUX_RUNNING:-0}" = "1" ] && exit 0 || exit 1 ;;
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

    def run_launch(*args, running=False):
        env = {
            "PATH": str(stubs),
            "HOME": str(tmp_path),
            "STUB_LOG": str(log),
            "STUB_TMUX_RUNNING": "1" if running else "0",
            "VLM_REMOTE_HOST": "stub-host.invalid",
        }
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
    proc, calls = launch("--force-restart", running=True)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    joined = "\n".join(calls)
    assert "kill-session" in joined
    assert "new-session" in joined


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
    assert not any("new-session" in c for c in calls)
    assert not any(c.startswith(("scp", "rsync")) for c in calls)


def test_launch_requires_a_value_for_songs(launch):
    proc, calls = launch("--songs")

    assert proc.returncode != 0
    assert "requires a value" in proc.stdout + proc.stderr
    assert calls == []


def test_launch_quotes_songs_for_the_remote_shell(launch):
    proc, calls = launch("--songs", "Shall We,01")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    started = [c for c in calls if "new-session" in c]
    assert len(started) == 1
    assert "--songs Shall\\ We\\,01" in started[0]
