"""Regression: pass 2's PICKUP_TOLERANCE was allowed to reach back 2
notes from verse_range[0] regardless of measure boundaries. When v2's
first audi token sat several measures after a v1-only section, the
tolerance landed truth tokens onto v1-only measure notes (#82).

Symptom on #13 LCWTO m16: v2's first audi token is at m19 (idx 63).
PICKUP_TOLERANCE=2 let pass 2 target idx 61, 62 (m16's last two
notes). The truth tokens "have" and "come" from the song's opening
line ("Things have come to a pretty pass") aligned as truth-gaps in
v2's NW alignment and got inserted onto those m16 notes as v2 lyrics.

The fix: PICKUP_FLOOR caps the lower-side tolerance to notes in the
same measure as verse_range[0] OR the immediately previous measure.
Pickup notes further back are not pickups -- they belong to a
preceding verse-only passage."""
from __future__ import annotations

from music21 import stream, note as m21note

from omr_leadsheet.pipeline.spell_check import (
    apply_alignment, audiveris_tokens,
)


def test_v2_truth_gap_does_not_land_on_v1_only_measure() -> None:
    """Build a score where v1 spans m1-m3 (8 notes) and v2 starts at
    m4. The v2 truth has 4 leading tokens ("Things have come to") that
    have no v2 audi anchor. Pre-fix, those would land on m3's last
    two notes via PICKUP_TOLERANCE=2. Post-fix, m3's notes stay
    v2-clean and the 4 truth-gaps simply don't get inserted (no
    pickup-territory naked notes available)."""
    sc = stream.Score()
    p = stream.Part()
    # m1: 3 notes, v1 only
    m1 = stream.Measure(number=1)
    for step, syll in zip(["A", "G", "F"], ["Some", "thing", "must"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m1.append(n)
    p.append(m1)
    # m2: 3 notes, v1 only
    m2 = stream.Measure(number=2)
    for step, syll in zip(["E", "D", "C"], ["be", "done", "now"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m2.append(n)
    p.append(m2)
    # m3: 4 notes, v1 only - matches the real LCWTO m16 shape. Pickup
    # tolerance must NOT reach into this measure: it's too long to be a
    # plausible anacrusis, it's a regular v1-only measure.
    m3 = stream.Measure(number=3)
    for step, syll in zip(["B", "A", "G", "F"], ["Some", "thing", "must", "be"]):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m3.append(n)
    p.append(m3)
    # m4: 4 notes, v1 + v2 stacked - v2 starts here
    m4 = stream.Measure(number=4)
    for step, syll1, syll2 in zip(
        ["G", "F", "E", "D"],
        ["You", "say", "ee", "ther"],
        ["You", "say", "laugh", "ter"],
    ):
        n = m21note.Note(step + "3", quarterLength=1.0)
        n.addLyric(syll1, lyricNumber=1)
        n.addLyric(syll2, lyricNumber=2)
        m4.append(n)
    p.append(m4)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    # v2 truth contains 4 leading tokens from the song's earlier v1
    # section. They should NOT be inserted onto m3 notes.
    v2_truth = ["Things", "have", "come", "to", "You", "say", "laugh", "ter"]
    apply_alignment(by_verse[2], v2_truth, all_notes, verse_num=2)

    # m3 must remain v2-clean.
    for n in all_notes[6:10]:  # m3's four notes
        v2_lyrs = [lyr.text for lyr in n.lyrics if (lyr.number or 1) == 2]
        assert v2_lyrs == [], (
            f"m3 note carrying v1 only must stay v2-clean; got v2={v2_lyrs}"
        )


def test_pickup_within_adjacent_measure_still_allowed() -> None:
    """An anacrusis (pickup syllable) ONE NOTE before v2's first audi
    token, in the SAME or ADJACENT measure, should still be insertable.
    This is the legitimate case PICKUP_TOLERANCE was designed for."""
    sc = stream.Score()
    p = stream.Part()
    # m1: 1 note with v1, no v2. This is the pickup measure.
    m1 = stream.Measure(number=1)
    n_pickup = m21note.Note("G3", quarterLength=1.0)
    n_pickup.addLyric("And", lyricNumber=1)
    m1.append(n_pickup)
    p.append(m1)
    # m2: 3 notes with stacked v1+v2. v2 audi starts here.
    m2 = stream.Measure(number=2)
    for step, s1, s2 in zip(["A", "B", "C"], ["I", "go", "now"], ["You", "stay", "back"]):
        n = m21note.Note(step + "4", quarterLength=1.0)
        n.addLyric(s1, lyricNumber=1)
        n.addLyric(s2, lyricNumber=2)
        m2.append(n)
    p.append(m2)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    # v2 truth has a leading pickup "Oh" before "You stay back".
    v2_truth = ["Oh", "You", "stay", "back"]
    apply_alignment(by_verse[2], v2_truth, all_notes, verse_num=2)

    # The pickup note (m1, idx 0) is in the measure immediately
    # before v2's first audi token (m2). Within PICKUP_TOLERANCE.
    # The "Oh" truth-gap may land on it.
    pickup_v2 = [lyr.text for lyr in all_notes[0].lyrics if (lyr.number or 1) == 2]
    assert pickup_v2 == ["Oh"], (
        f"in-adjacent-measure pickup should accept v2 truth; got {pickup_v2}"
    )
