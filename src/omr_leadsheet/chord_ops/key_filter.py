#!/usr/bin/env python3
"""Key-aware flat-root filter for chord-symbols.

VLM-based chord-row recognition (qwen2.5vl in particular) systematically
misses the small flat (b) glyph that sits next to a chord-root letter.
Songs in flat keys (Eb, Ab, Bb, F major) end up with many chord-symbols
whose root letter is correct but whose root-alter is missing -- e.g.
``A`` instead of ``Ab`` in Eb major. Verified across the spot-check set
#11/#24/#27 (all Eb major): 50%+ of chord-symbols miss their flat.

The filter compares the score's key signature against a per-song
ground-truth JSON that records what the PDF actually contains, then
flattens root letters that:
  - are in the key's "expected flat letters" set, AND
  - lack any explicit root-alter element, AND
  - are NOT in the song's chromatic-root-letter set (chord-row chords
    that intentionally use a natural-sign override of the key signature)

The cross-reference is the load-bearing safety mechanism. Without it,
blindly flattening A->Ab in Eb major would corrupt the chromatic A7
that often appears as a secondary dominant. WITH it, the filter only
fires where both the key matches the GT AND the PDF doesn't list that
root as chromatic.

If the GT entry is absent for a song, the filter is a no-op for that
song. Songs are added incrementally as PDFs are read.

Usage:
    from omr_leadsheet.chord_ops.key_filter import apply_key_aware_flatten

    n_flattened = apply_key_aware_flatten(
        score, song_name="13 - Let's Call The Whole Thing Off",
        groundtruth_path=Path("data/songbook_groundtruth.json"),
    )
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Map fifths -> ordered list of letters that get flatted in that key.
# Standard order of flats: Bb, Eb, Ab, Db, Gb, Cb, Fb.
_FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
_SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]


def expected_flat_letters_for_fifths(fifths: int) -> set[str]:
    """Return the root letters that are flatted in the key signature.

    fifths=-3 (Eb major) -> {'B', 'E', 'A'}.
    fifths=0 or positive -> empty set.
    """
    if fifths is None or fifths >= 0:
        return set()
    n_flats = -fifths
    return set(_FLAT_ORDER[:n_flats])


def expected_sharp_letters_for_fifths(fifths: int) -> set[str]:
    """Mirror for sharp keys. Currently unused -- the qwen2.5vl bug only
    affects flat-glyph recognition -- but symmetric helper for future use."""
    if fifths is None or fifths <= 0:
        return set()
    return set(_SHARP_ORDER[:fifths])


def load_groundtruth(path: Path | str) -> dict[str, Any]:
    """Load the songbook ground-truth JSON. Returns the parsed dict or
    an empty stub if the file is missing or malformed."""
    p = Path(path)
    if not p.exists():
        return {"schema_version": 0, "songs": {}}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"schema_version": 0, "songs": {}}


def _score_fifths(score) -> int | None:
    """Read the score's primary key-signature fifths value, or None."""
    try:
        from music21 import key
        for k in score.recurse().getElementsByClass(key.KeySignature):
            return k.sharps
    except Exception:
        return None
    return None


def _flatten_chord_root_in_place(cs) -> bool:
    """Apply a flat (root-alter = -1) to the ChordSymbol's root if it has
    no explicit alter set. Returns True if the chord was modified.

    music21 stores the root via ``cs.root().name`` (e.g. 'A', 'A-' for Ab,
    'A#' for A#). We modify by setting a fresh ``music21.pitch.Pitch``
    that includes the flat.
    """
    try:
        from music21 import pitch
        cur = cs.root()
        if cur is None:
            return False
        # cur.accidental is None or pitch.Accidental('natural' / 'flat' / etc.)
        # We only flatten when there's no explicit accidental at all.
        if cur.accidental is not None:
            return False
        new = pitch.Pitch(cur.name + "-")  # music21 uses '-' for flat
        new.octave = cur.octave
        cs.root(new)
        return True
    except Exception:
        return False


def apply_key_aware_flatten(
    score,
    *,
    song_name: str,
    groundtruth_path: Path | str = "data/songbook_groundtruth.json",
) -> dict[str, Any]:
    """Apply the key-aware flat-root fix to every ChordSymbol in ``score``.

    Returns a stats dict::

        {
            "song": "13 - ...",
            "gt_present": True/False,
            "gt_key_fifths": -3 / None,
            "score_key_fifths": -3 / None,
            "key_match": True/False,  -- did GT and score agree?
            "chords_examined": int,
            "chords_flattened": int,
            "chromatic_skipped": int,
            "reason_skipped": "" | "no_gt" | "no_score_key" | "key_mismatch",
        }

    The filter is a no-op unless ALL of these hold:
      - GT entry exists for this song
      - GT key_fifths is set and matches the score's detected key
      - The chord root is in the GT's expected_flat_letters
      - The chord has no explicit root-alter
      - The chord root is NOT listed in GT's chromatic_root_notes

    The reason for not firing is reported in the stats so callers can
    log when expected fixes were skipped.
    """
    from music21 import harmony

    stats: dict[str, Any] = {
        "song": song_name,
        "gt_present": False,
        "gt_key_fifths": None,
        "score_key_fifths": None,
        "key_match": False,
        "chords_examined": 0,
        "chords_flattened": 0,
        "chromatic_skipped": 0,
        "reason_skipped": "",
    }

    gt = load_groundtruth(groundtruth_path)
    song_gt = gt.get("songs", {}).get(song_name)
    if song_gt is None:
        stats["reason_skipped"] = "no_gt"
        return stats
    stats["gt_present"] = True
    stats["gt_key_fifths"] = song_gt.get("key_fifths")

    score_fifths = _score_fifths(score)
    stats["score_key_fifths"] = score_fifths
    if score_fifths is None:
        stats["reason_skipped"] = "no_score_key"
        return stats

    if stats["gt_key_fifths"] != score_fifths:
        stats["reason_skipped"] = "key_mismatch"
        return stats
    stats["key_match"] = True

    expected = set(song_gt.get("expected_flat_letters", []))
    chromatic = set()
    # chromatic_root_notes may include letter forms ("A", "B") or
    # qualified forms ("Bb", "F#"). For the flat-letter check we only
    # care about the bare letter -- chromatic naturals.
    for ch in song_gt.get("chromatic_root_notes", []):
        if len(ch) == 1:
            chromatic.add(ch)
        elif len(ch) > 1 and ch[0] in "ABCDEFG":
            # 'Bb' or 'F#' -- the BARE letter is the chromatic one we
            # don't want to flatten further.
            if ch[1] not in ("b", "-"):  # Bb chord IS the flatted form already
                chromatic.add(ch[0])

    for cs in score.recurse().getElementsByClass(harmony.ChordSymbol):
        stats["chords_examined"] += 1
        try:
            root = cs.root()
        except Exception:
            continue
        if root is None:
            continue
        root_letter = root.name[0]  # bare letter
        if root_letter not in expected:
            continue
        if root_letter in chromatic:
            stats["chromatic_skipped"] += 1
            continue
        if root.accidental is not None:
            # Already has explicit accidental -- whether natural or sharp
            # or already flat -- leave it alone.
            continue
        if _flatten_chord_root_in_place(cs):
            stats["chords_flattened"] += 1

    return stats


__all__ = [
    "apply_key_aware_flatten",
    "load_groundtruth",
    "expected_flat_letters_for_fifths",
    "expected_sharp_letters_for_fifths",
]
