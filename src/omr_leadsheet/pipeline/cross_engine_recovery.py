"""Cross-engine note recovery via pitch-sequence alignment (#54 PR-A).

When Audiveris's notehead classifier misses a glyph entirely (the
glyph isn't tagged as a notehead in the .omr, so head_recovery
can't fall back to it), the only way to recover that note from
within the pipeline is to consult a second OMR engine. The
pipeline already runs oemer optionally via ``--with-oemer``; this
module exposes its output as a *flat pitch stream* and aligns it
against Audiveris's vocal-staff notes to surface the candidates
Audiveris missed.

Why a flat stream, not measure-by-measure
-----------------------------------------
Oemer's MusicXML output uses "measures" that don't respect
barlines. A single oemer "measure" can span a full PDF system or
phrase. Per-measure alignment by fingerprint (the existing
``pipeline/merge_omr.py`` approach) works for empty-measure
backfill but not for the partial-recovery case #54 needs.

This module treats both engines as a flat note list and pitch-
aligns them. The Audiveris stream carries measure-number metadata
so we can later route a recovered note to the correct destination
measure; the oemer stream is index-only.

PR-A scope (this file)
----------------------
Just the alignment plumbing -- returns a list of *insertion
candidates* without actually inserting them. PR-B will gate
insertion by lyric-count signal and perform the score mutation.

Pitch comparison rules
----------------------
- Exact match (same step+alter+octave): cost 0.0
- Same step+alter, octave off by 1: cost 0.3 (notation engines
  often disagree on octave by one)
- Otherwise: cost 1.0 (full substitution)
- Gap cost: 0.5 (lower than full mismatch so the aligner prefers
  insertion/deletion over wrong-pitch pairing)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from music21 import converter, note, harmony


@dataclass(frozen=True)
class AudiNote:
    """A pitched note from Audiveris's lead, plus the measure it's
    attached to. ``measure_number`` is the Audiveris measure ID
    (after intro-trim), matching the values in the lead.musicxml."""
    measure_number: int
    step: str          # 'A'..'G'
    alter: int         # -1, 0, 1
    octave: int        # MIDI octave (e.g. 4 for middle-C-area)
    duration: float    # in quarterLength


@dataclass(frozen=True)
class OemerNote:
    """A pitched note from oemer's output. No measure metadata --
    oemer's measures don't map to Audiveris's."""
    index: int         # position in oemer's flat stream
    step: str
    alter: int
    octave: int
    duration: float


@dataclass(frozen=True)
class RecoveryCandidate:
    """An oemer note that the alignment couldn't pair to any audi
    note. Identifies which audi measure(s) bracket this gap so
    PR-B can decide where to insert."""
    oemer: OemerNote
    prev_audi_measure: int | None     # last audi measure paired before this gap
    next_audi_measure: int | None     # first audi measure paired after this gap


def _vocal_part(score) -> "music21.stream.Part":
    """Pick the part with the most lyrics -- conventionally vocal.

    Mirrors the heuristic in spell_check.audiveris_tokens so the
    two modules agree on which part is the vocal melody.
    """
    best_idx, best = 0, -1
    for i, p in enumerate(score.parts):
        c = sum(1 for n in p.recurse().notes if isinstance(n, note.Note) and n.lyrics)
        if c > best:
            best_idx, best = i, c
    return score.parts[best_idx]


def build_audi_stream(lead_musicxml_path: str) -> list[AudiNote]:
    """Read the Audiveris-derived lead.musicxml and emit a flat
    list of vocal-staff pitched notes with measure-number metadata."""
    score = converter.parse(lead_musicxml_path)
    vocal = _vocal_part(score)
    out: list[AudiNote] = []
    for m in vocal.getElementsByClass("Measure"):
        mn = int(m.number) if m.number else 0
        for n in m.recurse().notes:
            if not isinstance(n, note.Note):
                continue
            p = n.pitch
            out.append(AudiNote(
                measure_number=mn,
                step=p.step,
                alter=int(p.accidental.alter) if p.accidental else 0,
                octave=p.octave if p.octave is not None else 4,
                duration=float(n.duration.quarterLength or 1.0),
            ))
    return out


def build_oemer_stream(
    oemer_musicxml_path: str,
    *,
    min_octave: int = 3,
    max_octave: int = 6,
) -> list[OemerNote]:
    """Read oemer's MusicXML and emit a flat list of pitched notes,
    filtered to a plausible vocal range.

    Oemer typically blends staves; restricting to the vocal range
    drops most piano-line content. A4 is middle-C+9; vocals span
    roughly A3-A5 plus a small margin -- default range 3-6 catches
    the practical melody envelope without over-trimming.
    """
    score = converter.parse(oemer_musicxml_path)
    # Use part 0 as the heuristic default for the melody/vocal-equivalent
    # stream; oemer often emits the staff order top-to-bottom and the
    # vocal line is on top. PR-C may add smarter part selection.
    if not score.parts:
        return []
    part = score.parts[0]
    out: list[OemerNote] = []
    idx = 0
    for n in part.recurse().notes:
        if not isinstance(n, note.Note):
            continue
        p = n.pitch
        octv = p.octave if p.octave is not None else 4
        if not (min_octave <= octv <= max_octave):
            continue
        out.append(OemerNote(
            index=idx,
            step=p.step,
            alter=int(p.accidental.alter) if p.accidental else 0,
            octave=octv,
            duration=float(n.duration.quarterLength or 1.0),
        ))
        idx += 1
    return out


def _pitch_cost(a: AudiNote, o: OemerNote) -> float:
    """Cost of pairing an audi note with an oemer note. Lower = better.

    - 0.0: exact step+alter+octave match
    - 0.3: same pitch-class (step+alter), octave off by 1
    - 1.0: otherwise (full substitution)
    """
    if a.step == o.step and a.alter == o.alter:
        if a.octave == o.octave:
            return 0.0
        if abs(a.octave - o.octave) == 1:
            return 0.3
    return 1.0


def align_pitch_streams(
    audi: list[AudiNote],
    oemer: list[OemerNote],
    *,
    gap: float = 0.5,
) -> list[tuple[int | None, int | None]]:
    """Needleman-Wunsch alignment of two flat pitch streams.

    Returns list of (audi_index, oemer_index); None on either side
    means a gap.

    Same algorithm as ``spell_check.nw_align`` but parameterised on
    the pitch-cost function instead of string similarity.
    """
    n, m = len(audi), len(oemer)
    C = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        C[i][0] = C[i - 1][0] + gap
    for j in range(1, m + 1):
        C[0][j] = C[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = C[i - 1][j - 1] + _pitch_cost(audi[i - 1], oemer[j - 1])
            del_ = C[i - 1][j] + gap
            ins_ = C[i][j - 1] + gap
            C[i][j] = min(sub, del_, ins_)
    i, j = n, m
    out: list[tuple[int | None, int | None]] = []
    while i > 0 or j > 0:
        if (
            i > 0 and j > 0
            and C[i][j] == C[i - 1][j - 1] + _pitch_cost(audi[i - 1], oemer[j - 1])
        ):
            out.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and C[i][j] == C[i - 1][j] + gap:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    out.reverse()
    return out


def find_recovery_candidates(
    audi: list[AudiNote],
    oemer: list[OemerNote],
    alignment: list[tuple[int | None, int | None]] | None = None,
) -> list[RecoveryCandidate]:
    """Walk the alignment and surface the oemer-only positions
    (``(None, j)`` gaps) as candidates. For each, record the
    audi-side measure bracket so PR-B can route the insertion.

    If ``alignment`` isn't supplied, computes it via
    ``align_pitch_streams`` with defaults.
    """
    if alignment is None:
        alignment = align_pitch_streams(audi, oemer)
    candidates: list[RecoveryCandidate] = []
    for idx, (ai, oj) in enumerate(alignment):
        if ai is not None or oj is None:
            continue
        # Look backward for the previous paired audi anchor.
        prev_measure: int | None = None
        for k in range(idx - 1, -1, -1):
            pa, po = alignment[k]
            if pa is not None and po is not None:
                prev_measure = audi[pa].measure_number
                break
        # Look forward for the next paired audi anchor.
        next_measure: int | None = None
        for k in range(idx + 1, len(alignment)):
            pa, po = alignment[k]
            if pa is not None and po is not None:
                next_measure = audi[pa].measure_number
                break
        candidates.append(RecoveryCandidate(
            oemer=oemer[oj],
            prev_audi_measure=prev_measure,
            next_audi_measure=next_measure,
        ))
    return candidates


__all__ = [
    "AudiNote", "OemerNote", "RecoveryCandidate",
    "build_audi_stream", "build_oemer_stream",
    "align_pitch_streams", "find_recovery_candidates",
]
