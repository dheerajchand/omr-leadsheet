"""Tests for #93 truth-overlay extensions: measure merging, lyric
override, and phantom-marker stripping."""
from __future__ import annotations

from music21 import stream, note as m21note, harmony, expressions

from omr_leadsheet.pipeline.truth_overlay import apply_truth_overlay


def _two_measure_score() -> stream.Score:
    sc = stream.Score()
    p = stream.Part()
    m1 = stream.Measure(number=1)
    for step, syll in zip(["A", "B", "C", "D"], ["Some", "thing", "must", "be"]):
        n = m21note.Note(step + "4", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m1.append(n)
    m2 = stream.Measure(number=2)
    for step, syll in zip(["E", "F", "G", "A"], ["done.", "Oh,", "I", "wait"]):
        n = m21note.Note(step + "4", quarterLength=1.0)
        n.addLyric(syll, lyricNumber=1)
        m2.append(n)
    p.append(m1)
    p.append(m2)
    sc.append(p)
    return sc


def test_merge_measures_combines_notes() -> None:
    sc = _two_measure_score()
    truth = {"merge_measures": [{"measures": [1, 2]}], "measures": {}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["measures_merged"] == 1
    measures = list(sc.parts[0].getElementsByClass("Measure"))
    assert len(measures) == 1, "two measures should merge to one"
    notes = list(measures[0].recurse().notes)
    assert len(notes) == 8
    pitches = [n.pitch.nameWithOctave for n in notes]
    assert pitches == ["A4", "B4", "C4", "D4", "E4", "F4", "G4", "A4"]


def test_lyric_override_replaces_v1_only() -> None:
    sc = _two_measure_score()
    # Add a v2 lyric to confirm it survives the override
    notes_m1 = list(
        list(sc.parts[0].getElementsByClass("Measure"))[0].recurse().notes
    )
    notes_m1[0].addLyric("survives", lyricNumber=2)
    truth = {"measures": {"1": {"lyrics_v1": ["X", "Y", "Z", "W"]}}}
    apply_truth_overlay(sc, truth)
    notes = list(
        list(sc.parts[0].getElementsByClass("Measure"))[0].recurse().notes
    )
    v1s = [
        [lyr.text for lyr in n.lyrics if (lyr.number or 1) == 1]
        for n in notes
    ]
    assert v1s == [["X"], ["Y"], ["Z"], ["W"]]
    v2_first = [lyr.text for lyr in notes[0].lyrics if (lyr.number or 1) == 2]
    assert v2_first == ["survives"]


def test_phantom_marker_stripped() -> None:
    sc = _two_measure_score()
    m1 = list(sc.parts[0].getElementsByClass("Measure"))[0]
    marker = expressions.TextExpression("?")
    m1.insert(0, marker)
    truth = {"measures": {}}
    stats = apply_truth_overlay(sc, truth)
    assert stats["phantom_markers_stripped"] == 1
    remaining = list(
        sc.parts[0].recurse().getElementsByClass(expressions.TextExpression)
    )
    assert remaining == []


def test_non_phantom_text_expression_preserved() -> None:
    """A legitimate text expression like 'mp' or 'Brightly' must not
    be stripped -- only literal '?' markers."""
    sc = _two_measure_score()
    m1 = list(sc.parts[0].getElementsByClass("Measure"))[0]
    m1.insert(0, expressions.TextExpression("Brightly"))
    truth = {"measures": {}}
    apply_truth_overlay(sc, truth)
    remaining = [
        te.content
        for te in sc.parts[0].recurse().getElementsByClass(expressions.TextExpression)
    ]
    assert "Brightly" in remaining


def test_combined_merge_chord_and_lyric() -> None:
    """Realistic LCWTO-shaped case: merge m1+m2 and then override the
    chord and lyric list on the merged result."""
    sc = _two_measure_score()
    # Pre-existing chord symbols that should get replaced
    list(sc.parts[0].getElementsByClass("Measure"))[0].insert(
        0, harmony.ChordSymbol("F")
    )
    list(sc.parts[0].getElementsByClass("Measure"))[1].insert(
        0, harmony.ChordSymbol("G")
    )
    truth = {
        "merge_measures": [{"measures": [1, 2]}],
        "measures": {
            "1": {
                "chords": ["D", "B7", "Em", "D"],
                "lyrics_v1": ["Good", "ness", "knows", "what",
                              "the", "end", "will", "be"],
            }
        },
    }
    apply_truth_overlay(sc, truth)
    measures = list(sc.parts[0].getElementsByClass("Measure"))
    assert len(measures) == 1
    chords = [
        str(c.figure)
        for c in measures[0].recurse().getElementsByClass(harmony.ChordSymbol)
    ]
    assert chords == ["D", "B7", "Em", "D"]
    notes = [
        n for n in measures[0].recurse().notes
        if isinstance(n, m21note.Note)
    ]
    v1s = [
        next(
            (lyr.text for lyr in n.lyrics if (lyr.number or 1) == 1),
            None,
        )
        for n in notes
    ]
    assert v1s == ["Good", "ness", "knows", "what",
                   "the", "end", "will", "be"]
