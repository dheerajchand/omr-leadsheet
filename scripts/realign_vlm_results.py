#!/usr/bin/env python3
"""Post-process VLM results to fix intro-offset MusicXML alignment.

Re-reads the MusicXML for each song, computes the intro offset
(Audiveris measure count minus MusicXML measure count), and updates
each result file's musicxml_note_count and musicxml_lyrics to match
the correct measure.

Usage:
    python3 realign_vlm_results.py \
        --results-dir ~/omr-vlm-verify/results \
        --data-dir ~/omr-vlm-verify/data \
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from omr_leadsheet.barline import measure_bounds_from_omr


def _parse_musicxml(mxl_path: Path) -> dict[int, dict]:
    from music21 import converter, note as m21note
    score = converter.parse(str(mxl_path))
    part = score.parts[0]
    result: dict[int, dict] = {}
    for m in part.getElementsByClass("Measure"):
        mn = int(m.number) if m.number else 0
        notes = [
            n for n in m.recurse().notes
            if isinstance(n, m21note.Note)
        ]
        lyrics = []
        for n in notes:
            for lyr in n.lyrics:
                if (lyr.number or 1) == 1 and lyr.text:
                    lyrics.append(lyr.text)
        result[mn] = {"note_count": len(notes), "lyrics": lyrics}
    return result


def _normalize_lyrics(lyrics: list[str]) -> list[str]:
    out = []
    for s in lyrics:
        s = s.lower().strip().replace("’", "'").replace("‘", "'")
        s = re.sub(r"[,;.!?\"]+$", "", s).strip("-")
        if s:
            out.append(s)
    return out


def _lyrics_match(vlm: list[str], mxml: list[str]) -> bool:
    a = _normalize_lyrics(vlm)
    b = _normalize_lyrics(mxml)
    if len(a) != len(b):
        return False
    return all(x == y for x, y in zip(a, b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    results_dir = Path(args.results_dir)
    data_dir = Path(args.data_dir)
    lead_dir = data_dir / "lead_sheets"
    omr_dir = data_dir / "music_xml"

    for song_results_dir in sorted(results_dir.iterdir()):
        if not song_results_dir.is_dir():
            continue

        sample = next(song_results_dir.glob("m*.json"), None)
        if sample is None:
            continue
        r = json.loads(sample.read_text())
        song_name = r.get("song", "")
        if not song_name:
            continue

        song_lead = lead_dir / song_name
        if not song_lead.exists():
            print(f"SKIP {song_name}: no lead dir")
            continue

        mxl_files = [
            p for p in (
                list(song_lead.glob("*lead.corrected.musicxml"))
                + list(song_lead.glob("*lead.final.musicxml"))
            )
            if not p.name.startswith("._")
        ]
        if not mxl_files:
            print(f"SKIP {song_name}: no MusicXML")
            continue

        omr_files = list(omr_dir.glob(f"{song_name}*.omr"))
        if not omr_files:
            prefix = song_name.split(" ")[0]
            omr_files = [p for p in omr_dir.glob("*.omr") if p.stem.startswith(prefix)]
        if not omr_files:
            print(f"SKIP {song_name}: no .omr")
            continue

        mxml_data = _parse_musicxml(mxl_files[0])
        bounds = measure_bounds_from_omr(omr_files[0])
        aud_count = len(bounds)
        mxml_count = max(mxml_data.keys()) if mxml_data else 0
        offset = max(0, aud_count - mxml_count)

        print(f"\n{song_name}: offset={offset} (aud={aud_count}, mxml={mxml_count})")

        updated = 0
        for rf in sorted(song_results_dir.glob("m*.json")):
            r = json.loads(rf.read_text())
            if r.get("vlm_error"):
                continue

            mn = r["measure"]
            mxml_mn = mn - offset
            mxml_info = mxml_data.get(mxml_mn, {"note_count": 0, "lyrics": []})

            old_nc = r.get("musicxml_note_count")
            new_nc = mxml_info["note_count"]
            new_lyrics = mxml_info["lyrics"]

            r["mxml_measure"] = mxml_mn
            r["intro_offset"] = offset
            r["musicxml_note_count"] = new_nc
            r["musicxml_lyrics"] = new_lyrics
            r["note_count_match"] = r["vlm_note_count"] == new_nc
            r["lyrics_match"] = _lyrics_match(
                r.get("vlm_lyrics", []), new_lyrics
            )

            if old_nc != new_nc:
                updated += 1
                if args.dry_run:
                    print(f"  m{mn}→mxml_m{mxml_mn}: was mxml={old_nc}, now mxml={new_nc} (vlm={r['vlm_note_count']})")

            if not args.dry_run:
                rf.write_text(json.dumps(r, indent=2) + "\n")

        print(f"  Updated {updated} measures" + (" (dry-run)" if args.dry_run else ""))


if __name__ == "__main__":
    main()
