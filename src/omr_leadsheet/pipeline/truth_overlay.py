"""Apply a per-measure published-score truth file as a final overlay
on the generated lead-sheet, correcting chord-attribution mismatches
that Audiveris's barline detection produced.

The truth file format is documented in data/song_truth/README.md.

Acts ONLY on measures listed in the truth file. Measures not in the
truth file are left untouched. This means a truth file can cover the
known-problem area of a single song (e.g. #13 LCWTO's chord-shifted
page-2 region) without affecting any other measure.

Per measure listed in the truth:
- All existing ChordSymbol elements are removed
- The truth's chord list is inserted, evenly spread across the measure

Lyric overlay is NOT applied here -- lyric-pipeline fixes already
cover the major cases. Chord-attribution is the remaining hard wall
that GT-overlay is uniquely suited to.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from music21 import converter, expressions, harmony, note as m21note, pitch as m21pitch, stream

_log = logging.getLogger(__name__)


def _infer_pitch(part, measure_number: int) -> m21pitch.Pitch:
    """Find the nearest Note pitch by walking backward then forward
    from *measure_number*.  Falls back to middle C."""
    measures = list(part.getElementsByClass("Measure"))
    by_num = {int(m.number): idx for idx, m in enumerate(measures) if m.number}
    start = by_num.get(measure_number, 0)
    # Walk backward
    for idx in range(start, -1, -1):
        for el in reversed(list(measures[idx].recurse().notes)):
            if isinstance(el, m21note.Note):
                return el.pitch
    # Walk forward
    for idx in range(start + 1, len(measures)):
        for el in measures[idx].recurse().notes:
            if isinstance(el, m21note.Note):
                return el.pitch
    return m21pitch.Pitch("C4")


def _inject_notes_from_rests(measure, deficit: int,
                             inject_pitch: m21pitch.Pitch) -> int:
    """Convert rests in *measure* into cue-size notes until *deficit*
    is satisfied.  Returns the number of notes actually injected."""
    injected = 0
    rests = sorted(
        [r for r in measure.recurse().getElementsByClass(m21note.Rest)],
        key=lambda r: float(r.offset),
    )
    for rest in rests:
        if injected >= deficit:
            break
        rest_offset = float(rest.offset)
        rest_ql = float(rest.duration.quarterLength)
        needed = min(deficit - injected, max(1, int(rest_ql / 0.25)))
        note_ql = rest_ql / needed
        site = rest.activeSite or measure
        site.remove(rest)
        for k in range(needed):
            n = m21note.Note(inject_pitch, quarterLength=note_ql)
            n.style.noteSize = "cue"
            site.insert(rest_offset + k * note_ql, n)
            injected += 1
            if injected >= deficit:
                break
    return injected


def _truth_path_for(song_title: str, truth_root: Path | None = None) -> Path:
    """Map a song title to its truth-file path. The mapping is
    permissive: lowercase + replace non-alphanumerics with underscores,
    then prepend the digits prefix if present in the title."""
    root = truth_root or (
        Path(__file__).resolve().parents[3] / "data" / "song_truth"
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", song_title).strip("_").lower()
    cand = root / f"{slug}.json"
    if cand.exists():
        return cand
    # Try without the digit prefix (e.g. "13_..." -> "lets_..." )
    no_digit = re.sub(r"^\d+_", "", slug)
    cand2 = root / f"{no_digit}.json"
    if cand2.exists():
        return cand2
    return cand  # may not exist; caller checks


def load_truth(song_title: str, truth_root: Path | None = None) -> dict | None:
    """Return the truth dict if a truth file exists for this song,
    else None."""
    path = _truth_path_for(song_title, truth_root)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _merge_measures(part, measures_to_merge: list[int]) -> None:
    """Merge consecutive measures in `part` into the lowest-numbered
    one. Notes, rests, and chord symbols from later measures are
    appended to the first measure preserving relative order. Later
    measures are removed from the part. Used to correct Audiveris's
    over-segmentation where one published measure was split into
    multiple Audiveris measures."""
    if len(measures_to_merge) < 2:
        return
    target_mn = min(measures_to_merge)
    by_number = {int(m.number): m for m in part.getElementsByClass("Measure")
                 if m.number is not None}
    target = by_number.get(target_mn)
    if target is None:
        return
    cursor = target.duration.quarterLength or 0.0
    for mn in sorted(measures_to_merge):
        if mn == target_mn:
            continue
        source = by_number.get(mn)
        if source is None:
            continue
        # Move all musical elements over, offset by cursor
        for el in list(source.elements):
            if isinstance(el, (m21note.Note, m21note.Rest, harmony.ChordSymbol,
                               expressions.TextExpression)):
                el_offset = float(el.offset)
                source.remove(el)
                target.insert(cursor + el_offset, el)
        cursor += source.duration.quarterLength or 0.0
        # Drop the now-empty source measure
        part.remove(source)
    # Reset the target's duration so it reflects the combined content.
    target.duration.quarterLength = cursor


def _strip_phantom_markers(score) -> int:
    """Remove TextExpression '?' marks (the head-recovery audit tags)
    so the final lead sheet doesn't carry agent-internal annotations."""
    removed = 0
    for m in score.recurse().getElementsByClass(stream.Measure):
        for te in list(m.recurse().getElementsByClass(expressions.TextExpression)):
            if (te.content or "").strip() == "?":
                if te.activeSite is not None:
                    te.activeSite.remove(te)
                removed += 1
    return removed


def apply_truth_overlay(score, truth: dict) -> dict:
    """Apply per-measure published-score corrections:
      1. Measure merges declared via top-level `merge_measures`
         (a list of {target: int, measures: [int,...]} entries).
      2. Per-measure chord-list override (existing #80a/b behaviour).
      3. Per-measure v1 lyric-list override (#93). Lyrics are
         distributed one syllable per Note in order.  When a measure
         has more truth syllables than notes, rests are converted to
         cue-size notes to carry the extra lyrics (#103).
      4. Strip phantom-marker "?" TextExpressions.
    Returns stats. Mutates the score in place."""
    stats = {
        "measures_merged": 0,
        "measures_corrected": 0,
        "chords_replaced": 0,
        "chords_inserted": 0,
        "lyrics_overridden": 0,
        "notes_injected": 0,
        "phantom_markers_stripped": 0,
    }
    part = score.parts[0]

    # 1. Apply measure merges FIRST so subsequent passes see the merged
    # structure. Each entry is {"measures": [m, m+1, ...]}.
    for spec in truth.get("merge_measures", []):
        mns = spec.get("measures") or []
        if len(mns) >= 2:
            _merge_measures(part, mns)
            stats["measures_merged"] += 1

    # 2 + 3. Per-measure chord and lyric overlay.
    truth_measures = truth.get("measures", {})
    for m in part.getElementsByClass("Measure"):
        mn = int(m.number) if m.number else 0
        spec = truth_measures.get(str(mn))
        if not spec:
            continue
        # Chord override
        if "chords" in spec:
            existing = list(m.recurse().getElementsByClass(harmony.ChordSymbol))
            for cs in existing:
                stats["chords_replaced"] += 1
                cs.activeSite.remove(cs)
            new_chords = spec["chords"] or []
            n = len(new_chords)
            if n > 0:
                measure_ql = m.duration.quarterLength or 4.0
                step = measure_ql / n
                for i, figure in enumerate(new_chords):
                    try:
                        cs = harmony.ChordSymbol(figure)
                    except Exception:
                        continue
                    m.insert(i * step, cs)
                    stats["chords_inserted"] += 1
            stats["measures_corrected"] += 1
        # Lyric override
        if "lyrics_v1" in spec:
            new_lyrics = spec["lyrics_v1"] or []
            notes_in_m = [
                n for n in m.recurse().notes
                if isinstance(n, m21note.Note)
            ]
            # Note injection: convert rests to notes when lyrics exceed notes
            deficit = len(new_lyrics) - len(notes_in_m)
            if deficit > 0:
                raw = spec.get("inject_pitch")
                if raw:
                    try:
                        ip = m21pitch.Pitch(raw)
                    except Exception:
                        ip = _infer_pitch(part, mn)
                else:
                    ip = _infer_pitch(part, mn)
                count = _inject_notes_from_rests(m, deficit, ip)
                stats["notes_injected"] += count
                if count < deficit:
                    _log.warning(
                        "m%d: injected %d/%d needed notes (not enough rests)",
                        mn, count, deficit,
                    )
                notes_in_m = [
                    n for n in m.recurse().notes
                    if isinstance(n, m21note.Note)
                ]
            for i, n in enumerate(notes_in_m):
                # Remove existing v1 lyrics
                n.lyrics = [lyr for lyr in n.lyrics if (lyr.number or 1) != 1]
                if i < len(new_lyrics):
                    n.addLyric(new_lyrics[i], lyricNumber=1)
            stats["lyrics_overridden"] += 1

    # 4. Strip "?" phantom markers from the whole score.
    stats["phantom_markers_stripped"] = _strip_phantom_markers(score)
    return stats


def process_file(in_path: str, out_path: str, song_title: str) -> dict:
    truth = load_truth(song_title)
    if truth is None:
        score = converter.parse(in_path)
        score.write("musicxml", fp=out_path, makeNotation=False)
        return {"truth_applied": False}
    score = converter.parse(in_path)
    stats = apply_truth_overlay(score, truth)
    score.write("musicxml", fp=out_path, makeNotation=False)
    stats["truth_applied"] = True
    return stats


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("song_title", help="e.g. \"13 - Let's Call The Whole Thing Off\"")
    args = ap.parse_args()
    stats = process_file(args.input, args.output, args.song_title)
    print(f"  truth overlay: {stats}")


if __name__ == "__main__":
    main()
