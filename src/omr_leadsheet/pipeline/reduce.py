#!/usr/bin/env python3
"""Reduce a piano-vocal MusicXML to a Real Book-style lead sheet.

Strategy:
  1. Parse the score with music21.
  2. Identify the vocal part (most notes-with-lyrics; tiebreaker: most chord symbols).
  3. Collect chord symbols from *all* parts, keyed by (measure_number, offset).
     Prefer ones already on the vocal part.
  4. Build a new Score with just the vocal Part; strip lyrics.
  5. Re-attach any chord symbols that were floating on other parts.
  6. Trim intro: drop leading measures containing only rests.
  7. Trim verse (optional, default on): drop measures before the first
     heavy-light / repeat-start barline, which marks the refrain.
  8. Renumber measures from 1.
  9. Insert rehearsal letters A, B, C, ... every `section_bars` bars (default 8).
 10. Add system breaks at each rehearsal letter so sections never split.
 11. Set treble-8vb clef on the output (Au Privave style).
 12. Write .musicxml.

Usage: reduce_to_lead.py <input.mxl> <output.musicxml>
                        [--keep-verse] [--section-bars N]
"""
import argparse
import sys
from copy import deepcopy
from music21 import converter, stream, harmony, clef, note, bar, expressions, layout, key, meter


# Storage-MIDI floor for the vocal part after the octave-down transpose.
# At MIDI 52 (E3 storage = E4 sounded under a treble-8vb clef) we are
# already below the practical bottom of every standard vocal range; any
# note that lands below this is almost certainly a piano-LH bleed-through
# captured by Audiveris when the staff-separation in the .omr was lossy.
# Replacing such notes with rests preserves the bar's metric integrity
# while removing the audible/visual garbage.
VOCAL_FLOOR_MIDI = 52


def _drop_subvocal_notes(part) -> int:
    """Replace every Note in ``part`` whose ``pitch.midi`` is below
    ``VOCAL_FLOOR_MIDI`` with a Rest of equal duration at the same
    offset. Returns the number of notes dropped.

    Operates in-place on the part. Iterates Measure containers (and any
    Voice sub-containers) explicitly so we don't trip over the
    activeSite-after-deepcopy gotcha that bit the dynamics purge below.
    """
    dropped = 0

    def _scan(container):
        nonlocal dropped
        for el in list(container):
            if isinstance(el, note.Note) and el.pitch.midi < VOCAL_FLOOR_MIDI:
                rest = note.Rest()
                rest.duration = el.duration
                offset = el.offset
                container.remove(el)
                container.insert(offset, rest)
                dropped += 1
            elif hasattr(el, "voices") and el.voices:
                for v in el.voices:
                    _scan(v)

    for m in part.getElementsByClass("Measure"):
        _scan(m)
    return dropped


def pick_vocal_part(score) -> int:
    """Return the index of the part most likely to be the melody.

    Priority:
      1. Part with most lyric-bearing notes (vocal in piano-vocal score).
      2. Part with most chord symbols (chord-melody arrangement).
      3. For piano-solo scores (no lyrics, no chords), the first part,
         which is conventionally the right-hand / top-staff melody.
    """
    best_lyrics = 0
    best_chords = 0
    for part in score.parts:
        notes = list(part.recurse().notes)
        best_lyrics = max(best_lyrics, sum(
            1 for n in notes if isinstance(n, note.Note) and n.lyrics
        ))
        best_chords = max(best_chords, len(
            list(part.recurse().getElementsByClass(harmony.ChordSymbol))
        ))

    # If there are lyrics or chord symbols anywhere, rank parts by those.
    if best_lyrics > 0 or best_chords > 0:
        scores = []
        for i, part in enumerate(score.parts):
            notes = list(part.recurse().notes)
            lyrics = sum(1 for n in notes if isinstance(n, note.Note) and n.lyrics)
            chords = len(list(part.recurse().getElementsByClass(harmony.ChordSymbol)))
            scores.append((lyrics, chords, -len(notes), i))
        scores.sort(reverse=True)
        return scores[0][3]
    # Piano-solo fallback: use part 0 (top staff).
    return 0


def collect_chord_symbols(score):
    """Return a list of (measure_number, offset_in_measure, ChordSymbol) from all parts."""
    out = []
    for part in score.parts:
        for m in part.getElementsByClass("Measure"):
            for cs in m.getElementsByClass(harmony.ChordSymbol):
                out.append((m.number, float(cs.offset), cs))
            # also recurse into voices
            for v in m.getElementsByClass("Voice"):
                for cs in v.getElementsByClass(harmony.ChordSymbol):
                    out.append((m.number, float(cs.offset), cs))
    return out


def measure_is_rest_only(m) -> bool:
    """True if the measure has no pitched notes (rests / empty only)."""
    for n in m.recurse().notes:
        return False
    return True


def find_refrain_start(part) -> int | None:
    """Return the measure number where the refrain begins, or None.

    Heuristic: first measure with a left barline of type 'heavy-light'
    (MusicXML repeat-start) - this is what 'Refrain' sections typically use
    in these piano-vocal arrangements.
    """
    for m in part.getElementsByClass("Measure"):
        lb = m.leftBarline
        if lb is not None and lb.type in ("heavy-light",):
            return m.number
        # Fallback: a Repeat barline with direction='start'
        if isinstance(lb, bar.Repeat) and lb.direction == "start":
            return m.number
    return None


def reduce_score(
    in_path: str,
    out_path: str,
    keep_verse: bool = False,
    section_bars: int = 8,
    strip_lyrics: bool = False,
) -> dict:
    score = converter.parse(in_path)
    vocal_idx = pick_vocal_part(score)
    vocal = score.parts[vocal_idx]

    all_chords = collect_chord_symbols(score)
    vocal_chord_keys = {
        (m.number, float(cs.offset))
        for m in vocal.getElementsByClass("Measure")
        for cs in m.getElementsByClass(harmony.ChordSymbol)
    }

    new_part = deepcopy(vocal)

    # Transpose the melody down one octave to match the treble-8vb clef we
    # install later. The source vocal part was written in plain treble clef,
    # so its absolute pitches belong one octave lower on an 8vb staff.
    for n in new_part.recurse().notes:
        if isinstance(n, note.Note):
            n.octave = (n.octave or 4) - 1

    # Drop sub-vocal-range ghost notes that survive into the "vocal" part
    # from Audiveris's lossy staff separation (piano LH bleed). See
    # VOCAL_FLOOR_MIDI for the threshold rationale.
    ghosts_dropped = _drop_subvocal_notes(new_part)

    # Strip piano dynamics / hairpins. The Audiveris export sometimes attaches
    # piano-staff dynamic marks (mf, p, cresc.) to the vocal part. A jazz lead
    # sheet shouldn't carry dynamics - those belong on the performer's part.
    # After deepcopy, the elements' activeSite chain isn't reliable, so walk
    # every container explicitly and remove direct children.
    from music21 import dynamics
    droppable_types: tuple = tuple(
        c for c in (
            getattr(dynamics, "Dynamic", None),
            getattr(dynamics, "Crescendo", None),
            getattr(dynamics, "Diminuendo", None),
            getattr(dynamics, "DynamicWedge", None),
        ) if c is not None
    )

    def _purge_stream(stream_obj) -> None:
        for el in list(stream_obj):
            if isinstance(el, droppable_types):
                stream_obj.remove(el)
            elif hasattr(el, "elements"):
                _purge_stream(el)
    _purge_stream(new_part)

    # Also strip articulations (accent, marcato, staccato, etc.) from every
    # note in the vocal part. Real Book lead sheets don't carry per-note
    # articulations - those are performer interpretation. Many "^" marks in
    # the rendered output are also OCR misclassifications: the jazz-font
    # capital A above a note can be misread as a marcato articulation on
    # the note itself. Either way, the visible noise should go.
    from music21 import articulations
    art_types = (articulations.Articulation,)
    for n in new_part.recurse().notes:
        if isinstance(n, note.Note) and getattr(n, "articulations", None):
            n.articulations = [
                a for a in n.articulations if not isinstance(a, art_types)
            ]

    # Capture key/time from the source vocal part BEFORE we trim measures,
    # so we can re-install them on the new first measure if trimming drops them.
    source_key = next(iter(new_part.recurse().getElementsByClass(key.KeySignature)), None)
    source_time = next(iter(new_part.recurse().getElementsByClass(meter.TimeSignature)), None)

    # Strip lyrics (opt-in; default keeps them)
    if strip_lyrics:
        for n in new_part.recurse().notes:
            if isinstance(n, note.Note) and n.lyrics:
                n.lyrics = []

    # Attach chord symbols that exist on *other* parts but not on the vocal
    added = 0
    m_by_num = {m.number: m for m in new_part.getElementsByClass("Measure")}
    for mnum, off, cs in all_chords:
        if (mnum, off) in vocal_chord_keys:
            continue
        target = m_by_num.get(mnum)
        if target is None:
            continue
        target.insert(off, deepcopy(cs))
        vocal_chord_keys.add((mnum, off))
        added += 1

    # --- Trim leading rest-only measures (intro) ---
    measures = list(new_part.getElementsByClass("Measure"))
    intro_dropped = 0
    while measures and measure_is_rest_only(measures[0]):
        new_part.remove(measures[0])
        measures.pop(0)
        intro_dropped += 1

    # Always detect refrain start, even when keeping the verse, so we can anchor
    # key changes and rehearsal letters to the verse/refrain boundary.
    refrain_start_source = find_refrain_start(new_part)

    # --- Trim verse (unless keeping) ---
    verse_dropped = 0
    if not keep_verse and refrain_start_source is not None:
        for m in list(new_part.getElementsByClass("Measure")):
            if m.number < refrain_start_source:
                new_part.remove(m)
                verse_dropped += 1

    # --- Renumber measures from 1 and remember which is the refrain start ---
    refrain_start_new = None
    for i, m in enumerate(new_part.getElementsByClass("Measure"), start=1):
        if refrain_start_source is not None and m.number == refrain_start_source:
            refrain_start_new = i
        m.number = i

    # Strip Audiveris-inherited layout/print elements BEFORE we insert our own
    # system breaks, so the strip doesn't wipe the ones we add.
    layout_classes_pre = (layout.SystemLayout, layout.PageLayout, layout.StaffLayout)
    for el in list(new_part.recurse().getElementsByClass(layout_classes_pre)):
        holder = el.getContextByClass(stream.Measure) or new_part
        try:
            holder.remove(el, recurse=True)
        except Exception:
            pass

    # --- Insert rehearsal letters, aligned to sections when applicable ---
    # When verse+refrain: A = verse m1, B = refrain start, then every 8 bars inside refrain.
    # When refrain-only (or no refrain detected): every 8 bars from m1.
    letters_added = []
    measures = list(new_part.getElementsByClass("Measure"))
    if keep_verse and refrain_start_new is not None:
        # Letter at m1
        letter_positions = [1]
        # Letter at refrain start
        letter_positions.append(refrain_start_new)
        # Every section_bars bars inside the refrain
        pos = refrain_start_new + section_bars
        while pos <= len(measures):
            letter_positions.append(pos)
            pos += section_bars
    else:
        letter_positions = list(range(1, len(measures) + 1, section_bars))

    for idx, pos in enumerate(letter_positions):
        letter = chr(ord("A") + idx)
        if ord(letter) > ord("Z"):
            break
        m = measures[pos - 1]
        m.insert(0, expressions.RehearsalMark(letter))
        # System break at each letter (except the first) - forces one section
        # per line for sight-reading. No page breaks: MuseScore flows pages.
        if idx > 0:
            sl = layout.SystemLayout()
            sl.isNew = True
            m.insert(0, sl)
        letters_added.append((letter, pos))

    # Collapse key signatures to one per section (majority vote). Audiveris
    # often misreads the key change at a refrain boundary - a few bars of the
    # wrong key, then "correction" to the right one. Majority within each
    # section is robust for single-key verses/refrains.
    from collections import Counter
    measures_list = list(new_part.getElementsByClass("Measure"))

    def majority_key(measures_slice):
        counts: Counter = Counter()
        for m in measures_slice:
            for k in m.getElementsByClass(key.KeySignature):
                counts[k.sharps] += 1
        return counts.most_common(1)[0][0] if counts else None

    if refrain_start_new is not None and refrain_start_new > 1:
        verse_slice = measures_list[: refrain_start_new - 1]
        refrain_slice = measures_list[refrain_start_new - 1 :]
        verse_sharps = majority_key(verse_slice)
        refrain_sharps = majority_key(refrain_slice)
    else:
        verse_slice = []
        refrain_slice = measures_list
        verse_sharps = None
        refrain_sharps = majority_key(refrain_slice)

    # Remove all existing key signatures
    for m in measures_list:
        for k in list(m.getElementsByClass(key.KeySignature)):
            m.remove(k)

    # First measure: ensure key, time, clef are present and correct.
    first_m = measures_list[0] if measures_list else None
    if first_m is not None:
        # Clef → treble-8vb
        for c in list(first_m.getElementsByClass(clef.Clef)):
            first_m.remove(c)
        first_m.insert(0, clef.Treble8vbClef())

        # Starting key signature (verse key if present, else refrain key)
        starting_sharps = verse_sharps if verse_sharps is not None else refrain_sharps
        if starting_sharps is not None:
            first_m.insert(0, key.KeySignature(starting_sharps))
        elif source_key is not None:
            first_m.insert(0, deepcopy(source_key))

        # Time signature - reinstall if trimmed away
        if not list(first_m.getElementsByClass(meter.TimeSignature)) and source_time is not None:
            first_m.insert(0, deepcopy(source_time))

        # Clear any leading repeat-start barline (was the refrain marker)
        lb = first_m.leftBarline
        if lb is not None and lb.type in ("heavy-light",):
            first_m.leftBarline = None

    # Re-install a key change at the refrain boundary if needed
    if (
        refrain_start_new is not None
        and refrain_start_new > 1
        and verse_sharps is not None
        and refrain_sharps is not None
        and verse_sharps != refrain_sharps
    ):
        refrain_first_m = measures_list[refrain_start_new - 1]
        refrain_first_m.insert(0, key.KeySignature(refrain_sharps))

    # Build new score
    lead = stream.Score()
    if score.metadata is not None:
        lead.insert(0, deepcopy(score.metadata))
    new_part.partName = "Melody"
    new_part.partAbbreviation = ""
    lead.insert(0, new_part)

    # Try writing with makeNotation=False first - music21's default makeNotation
    # pass can corrupt rhythm-troubled Audiveris output. If that fails, fall back.
    try:
        lead.write("musicxml", fp=out_path, makeNotation=False)
    except Exception:
        lead.write("musicxml", fp=out_path)

    final_measures = list(new_part.getElementsByClass("Measure"))
    return {
        "vocal_part_index": vocal_idx,
        "intro_measures_dropped": intro_dropped,
        "verse_measures_dropped": verse_dropped,
        "refrain_start_in_source": refrain_start_source,
        "final_measures": len(final_measures),
        "final_notes": len(list(new_part.recurse().notes)),
        "chord_symbols_total": len(vocal_chord_keys),
        "chord_symbols_added_from_other_parts": added,
        "rehearsal_letters": letters_added,
        "subvocal_ghost_notes_dropped": ghosts_dropped,
        "output": out_path,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--keep-verse", action="store_true", help="Keep the verse before the refrain")
    ap.add_argument("--section-bars", type=int, default=8, help="Bars between rehearsal letters")
    ap.add_argument("--strip-lyrics", action="store_true", help="Remove lyrics (default: keep them)")
    args = ap.parse_args()
    result = reduce_score(
        args.input, args.output,
        keep_verse=args.keep_verse,
        section_bars=args.section_bars,
        strip_lyrics=args.strip_lyrics,
    )
    for k, v in result.items():
        print(f"{k}: {v}")
