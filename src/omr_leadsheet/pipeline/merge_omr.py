#!/usr/bin/env python3
"""Reconcile two OMR backends' MusicXMLs via content-based measure alignment.

Strategy (generic, not song-specific):

  1. For each backend, compute a "fingerprint" per measure:
        - note count (pitched notes only)
        - total pitched duration
        - first pitch midi (or -1 if empty)
        - rhythm shape: short string like "q q h r" summarising durations
     These are robust to small differences between backends and don't
     require either backend to emit chord symbols or lyrics.
  2. Globally align the two fingerprint sequences with Needleman-Wunsch
     using a fingerprint-similarity score. Handles oemer dropping a page,
     adding a spurious page, or miscounting a few measures.
  3. Walk the alignment. For each (primary, secondary) pair where primary
     has no pitched notes but secondary does, fill secondary's notes in.
     Mark every filled measure with a `?` TextExpression above the staff,
     so the user can always see where the merger acted.

Primary = Audiveris output (has chords + lyrics). Secondary = a second
backend whose output is pitched-note-only (e.g. oemer). The merger never
touches primary's chord symbols, lyrics, clef, key, or time signatures.

Usage: merge_omr.py <primary.musicxml> <secondary.musicxml> <out.musicxml>
"""
from __future__ import annotations
import sys
from copy import deepcopy
from difflib import SequenceMatcher
from dataclasses import dataclass
from music21 import converter, note, expressions


GAP_COST = 1.2  # Higher than any substitution cost (which is 1 - similarity, so
               # max 1.0). This makes NW prefer to pair measures positionally
               # even when content differs - specifically so an empty primary
               # measure gets paired with its positional counterpart in
               # secondary, not with some other empty measure elsewhere.


@dataclass
class Fingerprint:
    notes: int
    duration: float
    first_midi: int  # -1 if empty
    shape: str       # like "q q h r"


def rhythm_shape(m) -> str:
    """Compact rhythm-type string for a measure: 'q q e e h' etc."""
    parts = []
    for el in m.recurse().notesAndRests:
        ql = float(getattr(el.duration, "quarterLength", 0.0))
        # Bucket into a short code
        if ql >= 4.0:
            parts.append("W")      # whole
        elif ql >= 2.0:
            parts.append("h")      # half
        elif ql >= 1.0:
            parts.append("q")      # quarter
        elif ql >= 0.5:
            parts.append("e")      # eighth
        elif ql > 0:
            parts.append("s")      # sixteenth or shorter
        # Rests tagged with 'r'
        if isinstance(el, note.Rest):
            parts[-1] = "r"
    return " ".join(parts)


def fingerprint(m) -> Fingerprint:
    notes = [n for n in m.recurse().notes if isinstance(n, note.Note)]
    first = notes[0].pitch.midi if notes else -1
    total_dur = sum(float(n.duration.quarterLength) for n in notes)
    return Fingerprint(
        notes=len(notes),
        duration=round(total_dur, 2),
        first_midi=first,
        shape=rhythm_shape(m),
    )


def fp_similarity(a: Fingerprint, b: Fingerprint) -> float:
    """0..1. A measure matches another if note count, duration, and
    rhythm shape are close. First-pitch adds a small bonus."""
    if a.notes == 0 and b.notes == 0:
        return 1.0
    # Note count: |a - b| / max(a, b)
    nc = 1 - abs(a.notes - b.notes) / max(a.notes, b.notes, 1)
    # Duration: relative diff capped at 1.0
    dd = max(0.0, 1 - abs(a.duration - b.duration) / max(a.duration, b.duration, 1))
    # Rhythm shape: string similarity
    rs = SequenceMatcher(None, a.shape, b.shape).ratio()
    # First-pitch bonus (within 7 semitones = a 5th)
    if a.first_midi >= 0 and b.first_midi >= 0:
        pb = max(0.0, 1 - abs(a.first_midi - b.first_midi) / 7.0)
    else:
        pb = 0.5
    # Weighted: rhythm shape dominates, note count next
    return 0.40 * rs + 0.25 * nc + 0.20 * dd + 0.15 * pb


def nw_align_measures(
    a: list[Fingerprint], b: list[Fingerprint]
) -> list[tuple[int | None, int | None]]:
    n, m = len(a), len(b)
    C = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        C[i][0] = C[i - 1][0] + GAP_COST
    for j in range(1, m + 1):
        C[0][j] = C[0][j - 1] + GAP_COST
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub_cost = 1 - fp_similarity(a[i - 1], b[j - 1])
            sub = C[i - 1][j - 1] + sub_cost
            d = C[i - 1][j] + GAP_COST
            ins = C[i][j - 1] + GAP_COST
            C[i][j] = min(sub, d, ins)
    # Traceback
    i, j = n, m
    out: list[tuple[int | None, int | None]] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(C[i][j] - (C[i - 1][j - 1] + (1 - fp_similarity(a[i - 1], b[j - 1])))) < 1e-9:
            out.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and abs(C[i][j] - (C[i - 1][j] + GAP_COST)) < 1e-9:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    out.reverse()
    return out


def pick_melody_part(score) -> int:
    best_i, best_n = 0, -1
    for i, p in enumerate(score.parts):
        n = sum(1 for _ in p.recurse().notes)
        if n > best_n:
            best_i, best_n = i, n
    return best_i


def measure_has_notes(m) -> bool:
    return any(isinstance(n, note.Note) for n in m.recurse().notes)


def mark_filled(m, label: str = "?") -> None:
    te = expressions.TextExpression(label)
    te.style.fontSize = 14
    te.style.fontWeight = "bold"
    te.style.color = "#c0392b"
    m.insert(0.0, te)


def main() -> None:
    primary_path, secondary_path, out_path = sys.argv[1:4]
    primary = converter.parse(primary_path)
    secondary = converter.parse(secondary_path)

    p_part = primary.parts[0]
    s_part = secondary.parts[pick_melody_part(secondary)]

    p_measures = list(p_part.getElementsByClass("Measure"))
    s_measures = list(s_part.getElementsByClass("Measure"))

    p_fp = [fingerprint(m) for m in p_measures]
    s_fp = [fingerprint(m) for m in s_measures]

    alignment = nw_align_measures(p_fp, s_fp)

    stats = {
        "primary_measures": len(p_measures),
        "secondary_measures": len(s_measures),
        "aligned_pairs": sum(1 for a, b in alignment if a is not None and b is not None),
        "primary_gaps": sum(1 for a, b in alignment if a is None),
        "secondary_gaps": sum(1 for a, b in alignment if b is None),
        "filled_from_secondary": 0,
        "primary_already_had_notes": 0,
        "skipped_low_confidence": 0,
    }

    # Trust the global alignment. For the confidence check we ask a different
    # question: do the *neighbours* of this aligned pair also match well? If
    # the primary measure is empty, we can't compare fingerprints of the
    # measures themselves (the whole point is that they differ), so we use
    # the surrounding context as the signal.
    def neighbour_confidence(idx_in_alignment: int, radius: int = 3) -> float:
        scores: list[float] = []
        for d in range(-radius, radius + 1):
            if d == 0:
                continue
            j = idx_in_alignment + d
            if 0 <= j < len(alignment):
                pi2, si2 = alignment[j]
                if pi2 is not None and si2 is not None:
                    scores.append(fp_similarity(p_fp[pi2], s_fp[si2]))
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    MIN_NEIGHBOUR_SIM = 0.55

    for aidx, (p_i, s_i) in enumerate(alignment):
        if p_i is None or s_i is None:
            continue
        p_m = p_measures[p_i]
        if measure_has_notes(p_m):
            stats["primary_already_had_notes"] += 1
            continue
        s_m = s_measures[s_i]
        if not measure_has_notes(s_m):
            continue
        # Gate on neighbour similarity, not on the pair itself.
        if neighbour_confidence(aidx) < MIN_NEIGHBOUR_SIM:
            stats["skipped_low_confidence"] += 1
            continue
        for s_note in s_m.recurse().notes:
            if isinstance(s_note, note.Note):
                new_note = deepcopy(s_note)
                new_note.octave = (new_note.octave or 4) - 1
                p_m.insert(float(s_note.offset), new_note)
        for r in list(p_m.recurse().getElementsByClass("Rest")):
            try:
                p_m.remove(r, recurse=True)
            except Exception:
                pass
        mark_filled(p_m, "?")
        stats["filled_from_secondary"] += 1

    primary.write("musicxml", fp=out_path, makeNotation=False)
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
