#!/usr/bin/env python3
"""VLM verification: cross-check Audiveris output against qwen2.5-vl.

For each measure in each song, crops the measure from the Audiveris
BINARY.png, sends it to a local Ollama instance running qwen2.5-vl,
and compares the VLM's note count and lyrics against the MusicXML
pipeline output.  Results are written per-measure for resumability.

Usage:
    python3 vlm_verify.py --data-dir /path/to/omr-leadsheet/data \
                          --work-dir ~/omr-vlm-verify \
                          [--ollama-url http://localhost:11434] \
                          [--model qwen2.5-vl] \
                          [--songs 01,02,15] \
                          [--resume]

Designed to run on cyberpower inside a tmux session via vlm_verify.sh.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from omr_leadsheet.barline import MeasureBounds, measure_bounds_from_omr, crop_measure

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
_log = logging.getLogger(__name__)

VLM_PROMPT = """\
Look at this cropped measure from a musical score. Report:
1. How many noteheads (filled or open) do you see? Count only noteheads, not rests.
2. What lyrics text appears below the staff? List each syllable separated by spaces. If no lyrics, return an empty list.
Reply ONLY as JSON: {"note_count": <int>, "lyrics": ["syl", "la", "ble"]}"""


def _check_ollama(base_url: str, model: str) -> bool:
    """Verify Ollama is reachable and the model is available."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        _log.error("Cannot reach Ollama at %s: %s", base_url, exc)
        return False
    models = [m.get("name", "") for m in resp.json().get("models", [])]
    # Model names may include :latest or version tags
    matched = any(model in m for m in models)
    if not matched:
        _log.error(
            "Model %r not found. Available: %s. Run: ollama pull %s",
            model, ", ".join(models) or "(none)", model,
        )
        return False
    _log.info("Ollama OK: %s with model %s", base_url, model)
    return True


def _query_vlm(
    base_url: str, model: str, image_bytes: bytes,
) -> dict | None:
    """Send a measure crop to the VLM, return parsed response."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": VLM_PROMPT,
                "images": [b64],
            }
        ],
        "stream": False,
    }
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as exc:
        _log.warning("Ollama request failed: %s", exc)
        return None

    raw_text = resp.json().get("message", {}).get("content", "")
    return _parse_vlm_response(raw_text)


def _parse_vlm_response(text: str) -> dict | None:
    """Extract note_count and lyrics from VLM text response."""
    # Try direct JSON parse
    try:
        obj = json.loads(text)
        if "note_count" in obj:
            return {
                "note_count": int(obj["note_count"]),
                "lyrics": list(obj.get("lyrics", [])),
                "raw": text,
            }
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # Try extracting JSON from markdown code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if "note_count" in obj:
                return {
                    "note_count": int(obj["note_count"]),
                    "lyrics": list(obj.get("lyrics", [])),
                    "raw": text,
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Regex fallback: look for note_count number
    nc = re.search(r'"?note_count"?\s*[:=]\s*(\d+)', text)
    if nc:
        lyrics_m = re.search(r'"?lyrics"?\s*[:=]\s*\[([^\]]*)\]', text)
        lyrics = []
        if lyrics_m:
            lyrics = [
                s.strip().strip("\"'")
                for s in lyrics_m.group(1).split(",")
                if s.strip().strip("\"'")
            ]
        return {
            "note_count": int(nc.group(1)),
            "lyrics": lyrics,
            "raw": text,
        }

    _log.warning("Could not parse VLM response: %.200s", text)
    return None


def _extract_musicxml_info(mxl_path: Path, measure_number: int) -> dict:
    """Get note count and lyrics from a MusicXML file for one measure."""
    from music21 import converter, note as m21note
    score = converter.parse(str(mxl_path))
    part = score.parts[0]
    for m in part.getElementsByClass("Measure"):
        if int(m.number) == measure_number:
            notes = [
                n for n in m.recurse().notes
                if isinstance(n, m21note.Note)
            ]
            lyrics = []
            for n in notes:
                for lyr in n.lyrics:
                    if (lyr.number or 1) == 1 and lyr.text:
                        lyrics.append(lyr.text)
            return {
                "note_count": len(notes),
                "lyrics": lyrics,
            }
    return {"note_count": 0, "lyrics": []}


def _normalize_lyrics(lyrics: list[str]) -> list[str]:
    """Normalize lyrics for fuzzy comparison."""
    out = []
    for s in lyrics:
        s = s.lower().strip()
        s = s.replace("’", "'").replace("‘", "'")
        s = re.sub(r"[,;.!?\"]+$", "", s)
        s = s.strip("-")
        if s:
            out.append(s)
    return out


def _lyrics_match(vlm: list[str], mxml: list[str]) -> bool:
    """Fuzzy lyrics comparison."""
    a = _normalize_lyrics(vlm)
    b = _normalize_lyrics(mxml)
    if len(a) != len(b):
        return False
    return all(x == y for x, y in zip(a, b))


def _find_songs(data_dir: Path, filter_songs: list[str] | None) -> list[dict]:
    """Discover songs with both .omr and corrected MusicXML files."""
    songs = []
    lead_dir = data_dir / "LeadSheets"
    omr_dir = data_dir / "MusicXML"

    if not lead_dir.exists() or not omr_dir.exists():
        _log.error("Expected LeadSheets/ and MusicXML/ in %s", data_dir)
        return songs

    for song_dir in sorted(lead_dir.iterdir()):
        if not song_dir.is_dir():
            continue
        slug = song_dir.name
        if filter_songs and not any(f in slug for f in filter_songs):
            continue

        mxl_candidates = list(song_dir.glob("*lead.corrected.musicxml")) + \
                         list(song_dir.glob("*lead.final.musicxml"))
        if not mxl_candidates:
            continue
        mxl_path = mxl_candidates[0]

        omr_candidates = list(omr_dir.glob(f"{slug}*.omr")) + \
                         list(omr_dir.glob(f"{slug.split(' - ')[-1] if ' - ' in slug else slug}*.omr"))
        if not omr_candidates:
            # Try matching by prefix number
            prefix = slug.split(" ")[0] if " " in slug else slug
            omr_candidates = [
                p for p in omr_dir.glob("*.omr")
                if p.stem.startswith(prefix)
            ]
        if not omr_candidates:
            _log.warning("No .omr for %s, skipping", slug)
            continue

        songs.append({
            "slug": slug,
            "mxl_path": mxl_path,
            "omr_path": omr_candidates[0],
        })

    return songs


def _update_progress(
    work_dir: Path, status: str,
    current_song: str = "", current_measure: int = 0,
    songs_completed: int = 0, songs_total: int = 0,
    measures_completed: int = 0, measures_total: int = 0,
    errors: int = 0,
) -> None:
    progress = {
        "status": status,
        "current_song": current_song,
        "current_measure": current_measure,
        "songs_completed": songs_completed,
        "songs_total": songs_total,
        "measures_completed": measures_completed,
        "measures_total": measures_total,
        "started": "",
        "last_update": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }
    started_file = work_dir / ".started"
    if started_file.exists():
        progress["started"] = started_file.read_text().strip()
    else:
        progress["started"] = progress["last_update"]
        started_file.write_text(progress["started"])
    (work_dir / "progress.json").write_text(
        json.dumps(progress, indent=2) + "\n"
    )


def _load_truth_files(data_dir: Path) -> dict[str, dict]:
    """Load all truth files keyed by song slug."""
    truth_dir = data_dir / "song_truth"
    truth = {}
    if not truth_dir.exists():
        return truth
    for tf in truth_dir.glob("*.json"):
        try:
            data = json.loads(tf.read_text())
            truth[tf.stem] = data
        except Exception:
            continue
    return truth


def run(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir).resolve()
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    results_dir = work_dir / "results"
    results_dir.mkdir(exist_ok=True)

    if args.log_file:
        fh = logging.FileHandler(work_dir / args.log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(fh)

    if not _check_ollama(args.ollama_url, args.model):
        sys.exit(1)

    filter_songs = args.songs.split(",") if args.songs else None
    songs = _find_songs(data_dir, filter_songs)
    if not songs:
        _log.error("No songs found in %s", data_dir)
        sys.exit(1)
    _log.info("Found %d songs to verify", len(songs))

    truth_files = _load_truth_files(data_dir)

    total_measures = 0
    measures_completed = 0
    errors = 0

    # First pass: count measures
    song_bounds: list[tuple[dict, dict[int, MeasureBounds]]] = []
    for song in songs:
        bounds = measure_bounds_from_omr(song["omr_path"])
        song_bounds.append((song, bounds))
        total_measures += len(bounds)

    _log.info("Total measures to verify: %d", total_measures)
    _update_progress(work_dir, "running", songs_total=len(songs),
                     measures_total=total_measures)

    for song_idx, (song, bounds) in enumerate(song_bounds):
        slug = song["slug"]
        song_results_dir = results_dir / re.sub(r"[^A-Za-z0-9_-]", "_", slug)
        song_results_dir.mkdir(exist_ok=True)

        _log.info("Processing %s (%d measures)", slug, len(bounds))

        for mn, mb in sorted(bounds.items()):
            result_file = song_results_dir / f"m{mn}.json"

            if args.resume and result_file.exists():
                measures_completed += 1
                _update_progress(
                    work_dir, "running",
                    current_song=slug, current_measure=mn,
                    songs_completed=song_idx, songs_total=len(songs),
                    measures_completed=measures_completed,
                    measures_total=total_measures, errors=errors,
                )
                continue

            crop_bytes = crop_measure(song["omr_path"], mb, pad_below=200)
            if crop_bytes is None:
                _log.warning("m%d: crop failed for %s", mn, slug)
                errors += 1
                measures_completed += 1
                continue

            vlm_result = _query_vlm(args.ollama_url, args.model, crop_bytes)

            mxml_info = _extract_musicxml_info(song["mxl_path"], mn)

            if vlm_result is None:
                result = {
                    "song": slug,
                    "measure": mn,
                    "vlm_error": True,
                    "musicxml_note_count": mxml_info["note_count"],
                    "musicxml_lyrics": mxml_info["lyrics"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                errors += 1
            else:
                nc_match = vlm_result["note_count"] == mxml_info["note_count"]
                ly_match = _lyrics_match(
                    vlm_result["lyrics"], mxml_info["lyrics"]
                )
                result = {
                    "song": slug,
                    "measure": mn,
                    "vlm_note_count": vlm_result["note_count"],
                    "musicxml_note_count": mxml_info["note_count"],
                    "note_count_match": nc_match,
                    "vlm_lyrics": vlm_result["lyrics"],
                    "musicxml_lyrics": mxml_info["lyrics"],
                    "lyrics_match": ly_match,
                    "vlm_raw": vlm_result.get("raw", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

            result_file.write_text(json.dumps(result, indent=2) + "\n")
            measures_completed += 1

            _update_progress(
                work_dir, "running",
                current_song=slug, current_measure=mn,
                songs_completed=song_idx, songs_total=len(songs),
                measures_completed=measures_completed,
                measures_total=total_measures, errors=errors,
            )

        _log.info("Completed %s", slug)

    # Final: generate discrepancy report
    _log.info("Generating discrepancy report...")
    _generate_report(results_dir, truth_files, work_dir)
    _update_progress(work_dir, "complete",
                     songs_completed=len(songs), songs_total=len(songs),
                     measures_completed=measures_completed,
                     measures_total=total_measures, errors=errors)
    _log.info("Done. Results in %s", work_dir)


def _generate_report(
    results_dir: Path, truth_files: dict[str, dict], work_dir: Path,
) -> None:
    """Build discrepancy_report.json from per-measure result files."""
    note_mismatches = 0
    lyric_mismatches = 0
    vlm_errors = 0
    total = 0
    discrepancies: list[dict] = []

    # Build truth lookup: {song_slug: {measure_str: ...}}
    truth_measures: dict[str, set[int]] = {}
    for slug, data in truth_files.items():
        measures = data.get("measures", {})
        truth_measures[slug] = {int(k) for k in measures.keys()}

    true_positives = 0
    false_negatives = 0
    false_positives = 0

    for song_dir in sorted(results_dir.iterdir()):
        if not song_dir.is_dir():
            continue
        for rf in sorted(song_dir.glob("m*.json")):
            try:
                r = json.loads(rf.read_text())
            except Exception:
                continue
            total += 1

            if r.get("vlm_error"):
                vlm_errors += 1
                continue

            is_note_mismatch = not r.get("note_count_match", True)
            is_lyric_mismatch = not r.get("lyrics_match", True)

            if is_note_mismatch:
                note_mismatches += 1
            if is_lyric_mismatch:
                lyric_mismatches += 1

            flagged = is_note_mismatch or is_lyric_mismatch

            if flagged:
                discrepancies.append({
                    "song": r.get("song", ""),
                    "measure": r.get("measure", 0),
                    "note_mismatch": is_note_mismatch,
                    "lyric_mismatch": is_lyric_mismatch,
                    "vlm_notes": r.get("vlm_note_count"),
                    "mxml_notes": r.get("musicxml_note_count"),
                    "vlm_lyrics": r.get("vlm_lyrics", []),
                    "mxml_lyrics": r.get("musicxml_lyrics", []),
                })

            # Check against truth files for accuracy
            mn = r.get("measure", 0)
            song_slug = _result_to_truth_slug(r.get("song", ""))
            in_truth = song_slug in truth_measures and mn in truth_measures[song_slug]

            if flagged and in_truth:
                true_positives += 1
            elif flagged and not in_truth:
                false_positives += 1
            elif not flagged and in_truth:
                false_negatives += 1

    total_truth = sum(len(v) for v in truth_measures.values())
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0.0
    recall = true_positives / total_truth if total_truth > 0 else 0.0

    report = {
        "summary": {
            "total_measures": total,
            "note_mismatches": note_mismatches,
            "lyric_mismatches": lyric_mismatches,
            "vlm_errors": vlm_errors,
        },
        "accuracy_vs_truth": {
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "false_positives": false_positives,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "total_truth_corrections": total_truth,
        },
        "discrepancies": discrepancies,
    }

    (work_dir / "discrepancy_report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    _log.info(
        "Report: %d measures, %d note mismatches, %d lyric mismatches, "
        "%d VLM errors. Precision=%.2f Recall=%.2f",
        total, note_mismatches, lyric_mismatches, vlm_errors,
        precision, recall,
    )


def _result_to_truth_slug(song_name: str) -> str:
    """Map a song name to a truth file slug."""
    return re.sub(r"[^A-Za-z0-9]+", "_", song_name).strip("_").lower()


def main() -> None:
    ap = argparse.ArgumentParser(description="VLM verification of OMR pipeline output")
    ap.add_argument("--data-dir", required=True, help="Path to omr-leadsheet/data")
    ap.add_argument("--work-dir", required=True, help="Working directory for results")
    ap.add_argument("--ollama-url", default="http://localhost:11434")
    ap.add_argument("--model", default="qwen2.5-vl")
    ap.add_argument("--songs", default=None, help="Comma-separated song prefixes to filter")
    ap.add_argument("--resume", action="store_true", help="Skip measures with existing results")
    ap.add_argument("--log-file", default="vlm_verify.log")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
