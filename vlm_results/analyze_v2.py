#!/usr/bin/env python3
"""Analyze VLM v2 results with tolerance-based metrics.

Supports intro-offset correction: when result files contain an
``intro_offset`` field, note/lyric comparisons already reflect the
corrected alignment.  For older results without this field, pass
``--offsets 01:4,07:6,15:4`` to manually specify per-song offsets.
"""
import argparse
import json
import os
from pathlib import Path
from collections import defaultdict

RESULTS_DIR = Path(__file__).parent / "results"
TRUTH_DIR = Path(__file__).parents[1] / "data" / "song_truth"

# Per-song intro offsets (audiveris measure - offset = musicxml measure).
# Populated via --offsets CLI or from result files.
_OFFSETS: dict[str, int] = {}


def load_results():
    results = []
    for song_dir in sorted(RESULTS_DIR.iterdir()):
        if not song_dir.is_dir():
            continue
        for rf in sorted(song_dir.glob("m*.json")):
            try:
                r = json.loads(rf.read_text())
                if not r.get("vlm_error"):
                    results.append(r)
            except Exception:
                continue
    return results


def load_truth():
    truth = {}
    if not TRUTH_DIR.exists():
        return truth
    for tf in TRUTH_DIR.glob("*.json"):
        if tf.stem.endswith(" 2"):
            continue
        data = json.loads(tf.read_text())
        truth[tf.stem] = {int(k): v for k, v in data.get("measures", {}).items()}
    return truth


def slug_to_truth_key(song_name):
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", song_name).strip("_").lower()


def _offset_for(song_name: str) -> int:
    """Return the intro offset for a song, or 0 if unknown."""
    for key, off in _OFFSETS.items():
        if key in song_name:
            return off
    return 0


def _note_diff(r: dict) -> int:
    """VLM note count minus MusicXML note count (offset-aware)."""
    return r["vlm_note_count"] - r["musicxml_note_count"]


def analyze(results, truth):
    # Filter out intro measures (audiveris measure <= offset)
    filtered = []
    for r in results:
        offset = r.get("intro_offset", _offset_for(r["song"]))
        if r["measure"] <= offset:
            continue
        filtered.append(r)

    skipped = len(results) - len(filtered)
    print(f"Total measures analyzed: {len(filtered)} (skipped {skipped} intro measures)\n")
    results = filtered

    # Note count accuracy at different tolerances
    print("=== NOTE COUNT ACCURACY ===")
    for tol in [0, 1, 2, 3]:
        within = sum(
            1 for r in results
            if abs(_note_diff(r)) <= tol
        )
        print(f"  Within ±{tol}: {within}/{len(results)} ({100*within/len(results):.0f}%)")

    # Direction of mismatch
    over = sum(1 for r in results if _note_diff(r) > 0)
    under = sum(1 for r in results if _note_diff(r) < 0)
    exact = sum(1 for r in results if _note_diff(r) == 0)
    print(f"\n  Exact match: {exact}")
    print(f"  VLM over:    {over} (avg +{sum(_note_diff(r) for r in results if _note_diff(r)>0)/max(over,1):.1f})")
    print(f"  VLM under:   {under} (avg -{sum(-_note_diff(r) for r in results if _note_diff(r)<0)/max(under,1):.1f})")

    # Per-song breakdown
    print("\n=== PER-SONG BREAKDOWN ===")
    songs = defaultdict(list)
    for r in results:
        songs[r["song"]].append(r)

    for song_name, song_results in sorted(songs.items()):
        exact_n = sum(1 for r in song_results if _note_diff(r) == 0)
        within1 = sum(1 for r in song_results if abs(_note_diff(r)) <= 1)
        within2 = sum(1 for r in song_results if abs(_note_diff(r)) <= 2)
        lyric_ok = sum(1 for r in song_results if r.get("lyrics_match", False))
        n = len(song_results)
        print(f"\n  {song_name} ({n} measures):")
        print(f"    Notes exact: {exact_n}/{n} ({100*exact_n/n:.0f}%)")
        print(f"    Notes ±1:    {within1}/{n} ({100*within1/n:.0f}%)")
        print(f"    Notes ±2:    {within2}/{n} ({100*within2/n:.0f}%)")
        print(f"    Lyrics match: {lyric_ok}/{n} ({100*lyric_ok/n:.0f}%)")

    # Big outliers (diff > 3)
    outliers = [(r["song"], r["measure"], r["vlm_note_count"], r["musicxml_note_count"])
                for r in results
                if abs(_note_diff(r)) > 3]
    print(f"\n=== OUTLIERS (diff > 3): {len(outliers)} measures ===")
    for song, mn, vlm, mxml in sorted(outliers, key=lambda x: abs(x[2]-x[3]), reverse=True)[:15]:
        print(f"  {song} m{mn}: vlm={vlm} mxml={mxml} diff={vlm-mxml:+d}")

    # Lyric presence detection (simpler metric: does VLM find lyrics when MusicXML has them?)
    print("\n=== LYRIC PRESENCE DETECTION ===")
    vlm_has_mxml_has = sum(1 for r in results if r["vlm_lyrics"] and r["musicxml_lyrics"])
    vlm_has_mxml_empty = sum(1 for r in results if r["vlm_lyrics"] and not r["musicxml_lyrics"])
    vlm_empty_mxml_has = sum(1 for r in results if not r["vlm_lyrics"] and r["musicxml_lyrics"])
    vlm_empty_mxml_empty = sum(1 for r in results if not r["vlm_lyrics"] and not r["musicxml_lyrics"])
    print(f"  Both have lyrics:    {vlm_has_mxml_has}")
    print(f"  VLM found, mxml empty: {vlm_has_mxml_empty} (potential GAP detection)")
    print(f"  VLM empty, mxml has:   {vlm_empty_mxml_has} (VLM missed lyrics)")
    print(f"  Both empty:            {vlm_empty_mxml_empty}")

    # Truth-based accuracy (using ±2 tolerance as the flag threshold)
    print("\n=== TRIAGE ACCURACY (flag threshold: diff > 2) ===")
    truth_lookup = {}
    for slug, measures in truth.items():
        truth_lookup[slug] = set(measures.keys())

    for threshold in [1, 2, 3]:
        tp = fp = fn = tn = 0
        for r in results:
            tkey = slug_to_truth_key(r["song"])
            mn = r["measure"]
            in_truth = tkey in truth_lookup and mn in truth_lookup[tkey]
            flagged = abs(_note_diff(r)) > threshold

            if flagged and in_truth:
                tp += 1
            elif flagged and not in_truth:
                fp += 1
            elif not flagged and in_truth:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        total_truth = sum(len(v) for v in truth_lookup.values())
        print(f"\n  Threshold > {threshold}:")
        print(f"    Flagged: {tp+fp}/{len(results)} ({100*(tp+fp)/len(results):.0f}%)")
        print(f"    TP={tp} FP={fp} FN={fn} TN={tn}")
        print(f"    Precision: {precision:.1%}")
        print(f"    Recall (of {total_truth} truth corrections): {tp}/{total_truth} = {100*tp/total_truth:.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--offsets", default="01:4,07:6,15:4",
        help="Comma-separated song_prefix:offset pairs (e.g. '01:4,07:6')",
    )
    args = ap.parse_args()
    for pair in args.offsets.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            _OFFSETS[k.strip()] = int(v.strip())
    results = load_results()
    truth = load_truth()
    analyze(results, truth)
