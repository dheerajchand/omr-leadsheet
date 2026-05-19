"""Key-aware flat-root filter (#20 / #27 followup).

The qwen2.5vl chord-row recogniser systematically misses the small flat
glyph beside a chord-root letter. Songs in flat keys (Eb, Ab, Bb, F)
end up with chord-symbols whose root letter is correct but whose
root-alter is missing -- e.g. 'A' instead of 'Ab' in Eb major.

The filter compares the score's key signature against a per-song
ground-truth JSON and flattens the appropriate root letters, while
explicitly skipping chord roots listed as chromatic exceptions
(secondary dominants, chromatic mediants, modal-mixture borrowings).

Cross-reference key match is the load-bearing safety mechanism --
without it, blindly flattening A->Ab in Eb major corrupts the
chromatic A7 secondary-dominant that often appears as V/D.
"""
from __future__ import annotations

import json
from pathlib import Path

from music21 import converter, harmony

from omr_leadsheet.chord_ops.key_filter import (
    apply_key_aware_flatten,
    expected_flat_letters_for_fifths,
    expected_sharp_letters_for_fifths,
    load_groundtruth,
)


# --- helper-table tests ---------------------------------------------------

def test_expected_flat_letters_progression() -> None:
    """Flats stack in the standard order Bb, Eb, Ab, Db, Gb, Cb, Fb."""
    assert expected_flat_letters_for_fifths(0) == set()
    assert expected_flat_letters_for_fifths(-1) == {"B"}
    assert expected_flat_letters_for_fifths(-2) == {"B", "E"}
    assert expected_flat_letters_for_fifths(-3) == {"B", "E", "A"}
    assert expected_flat_letters_for_fifths(-4) == {"B", "E", "A", "D"}


def test_expected_sharp_letters_progression() -> None:
    assert expected_sharp_letters_for_fifths(0) == set()
    assert expected_sharp_letters_for_fifths(1) == {"F"}
    assert expected_sharp_letters_for_fifths(2) == {"F", "C"}
    assert expected_sharp_letters_for_fifths(3) == {"F", "C", "G"}


def test_positive_fifths_has_no_expected_flats() -> None:
    """A sharp key shouldn't trigger any flat-side recovery."""
    for f in range(0, 8):
        assert expected_flat_letters_for_fifths(f) == set()


# --- helper to build a one-bar score with given chords -------------------

def _score_with_chords(
    fifths: int,
    chord_figures: list[str],
) -> object:
    parts = [
        '<?xml version="1.0"?>',
        '<score-partwise version="4.0">',
        '<part-list><score-part id="P1"><part-name/></score-part></part-list>',
        '<part id="P1"><measure number="1">',
        '<attributes>',
        '<divisions>1</divisions>',
        f'<key><fifths>{fifths}</fifths></key>',
        '<time><beats>4</beats><beat-type>4</beat-type></time>',
        '</attributes>',
    ]
    for fig in chord_figures:
        # Parse "A", "Ab", "A7" etc. into root + alter + kind hints.
        root = fig[0]
        rest = fig[1:]
        alter = 0
        if rest.startswith("b") or rest.startswith("-"):
            alter = -1; rest = rest[1:]
        elif rest.startswith("#"):
            alter = 1; rest = rest[1:]
        # Map kind suffix to MusicXML kind value.
        if rest == "":
            kind = "major"
        elif rest == "7":
            kind = "dominant"
        elif rest == "m":
            kind = "minor"
        elif rest == "m7":
            kind = "minor-seventh"
        elif rest == "maj7":
            kind = "major-seventh"
        else:
            kind = "major"
        parts.append('<harmony><root>')
        parts.append(f'<root-step>{root}</root-step>')
        if alter:
            parts.append(f'<root-alter>{alter}</root-alter>')
        parts.append(f'</root><kind>{kind}</kind></harmony>')
    parts.append('<note><rest/><duration>4</duration><type>whole</type></note>')
    parts.append('</measure></part></score-partwise>')
    return converter.parseData("\n".join(parts))


def _gt_path(tmp_path: Path, songs: dict) -> Path:
    p = tmp_path / "gt.json"
    p.write_text(json.dumps({"schema_version": 1, "songs": songs}))
    return p


# --- core safety tests ---------------------------------------------------

def test_missing_gt_entry_is_no_op(tmp_path: Path) -> None:
    """If the GT JSON has no entry for the song, the filter does nothing."""
    score = _score_with_chords(-3, ["A", "B", "E"])
    gt = _gt_path(tmp_path, {})  # no songs
    stats = apply_key_aware_flatten(
        score, song_name="unknown song", groundtruth_path=gt,
    )
    assert stats["gt_present"] is False
    assert stats["reason_skipped"] == "no_gt"
    assert stats["chords_flattened"] == 0


def test_score_key_missing_is_no_op(tmp_path: Path) -> None:
    """No <key> in the score -> filter can't verify; abort."""
    # Build a score without a key signature
    xml = (
        '<?xml version="1.0"?>\n'
        '<score-partwise version="4.0">'
        '<part-list><score-part id="P1"><part-name/></score-part></part-list>'
        '<part id="P1"><measure number="1">'
        '<attributes><divisions>1</divisions>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '</attributes>'
        '<harmony><root><root-step>A</root-step></root><kind>major</kind></harmony>'
        '<note><rest/><duration>4</duration><type>whole</type></note>'
        '</measure></part></score-partwise>'
    )
    score = converter.parseData(xml)
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -3, "expected_flat_letters": ["A"],
                   "chromatic_root_notes": []}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    assert stats["reason_skipped"] == "no_score_key"
    assert stats["chords_flattened"] == 0


def test_key_mismatch_is_no_op(tmp_path: Path) -> None:
    """If GT key disagrees with score key, abort to be safe."""
    score = _score_with_chords(-2, ["A"])  # Bb major in score
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -3, "expected_flat_letters": ["A"],
                   "chromatic_root_notes": []}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    assert stats["score_key_fifths"] == -2
    assert stats["gt_key_fifths"] == -3
    assert stats["key_match"] is False
    assert stats["reason_skipped"] == "key_mismatch"
    assert stats["chords_flattened"] == 0


# --- happy-path tests ----------------------------------------------------

def test_flattens_expected_letter_in_eb_major(tmp_path: Path) -> None:
    """Eb major + ['B','E','A'] expected -- bare 'A' becomes 'Ab'."""
    score = _score_with_chords(-3, ["A", "Em", "B7", "C"])
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -3,
                   "expected_flat_letters": ["B", "E", "A"],
                   "chromatic_root_notes": []}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    assert stats["key_match"] is True
    assert stats["chords_flattened"] == 3  # A, E, B all flatten
    # Verify the chord roots are now flatted
    chords = list(score.recurse().getElementsByClass(harmony.ChordSymbol))
    root_names = [c.root().name for c in chords]
    assert "A-" in root_names  # Ab in music21 notation
    assert "E-" in root_names
    assert "B-" in root_names
    assert "C" in root_names  # C left alone (not in expected set)


def test_chromatic_letters_are_NOT_flattened(tmp_path: Path) -> None:
    """Chromatic exception list overrides the flatten rule. In Eb major
    with chromatic ['A'], the 'A' chord stays natural (A major = A,
    not Ab) -- it's a secondary dominant or chromatic mediant."""
    score = _score_with_chords(-3, ["A", "B", "E"])
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -3,
                   "expected_flat_letters": ["B", "E", "A"],
                   "chromatic_root_notes": ["A"]}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    assert stats["chromatic_skipped"] == 1  # A skipped
    assert stats["chords_flattened"] == 2  # only B, E flatten
    chords = list(score.recurse().getElementsByClass(harmony.ChordSymbol))
    root_names = [c.root().name for c in chords]
    assert "A" in root_names  # A stays natural
    assert "B-" in root_names  # Bb
    assert "E-" in root_names  # Eb


def test_existing_alter_is_not_re_flattened(tmp_path: Path) -> None:
    """If the chord already has root-alter (either flat or sharp or
    explicit natural), leave it alone."""
    # Build a chord with explicit alter = 0 (natural)
    xml = (
        '<?xml version="1.0"?>'
        '<score-partwise version="4.0">'
        '<part-list><score-part id="P1"><part-name/></score-part></part-list>'
        '<part id="P1"><measure number="1">'
        '<attributes><divisions>1</divisions>'
        '<key><fifths>-3</fifths></key>'
        '<time><beats>4</beats><beat-type>4</beat-type></time>'
        '</attributes>'
        '<harmony><root><root-step>A</root-step><root-alter>-1</root-alter></root>'
        '<kind>major</kind></harmony>'
        '<note><rest/><duration>4</duration><type>whole</type></note>'
        '</measure></part></score-partwise>'
    )
    score = converter.parseData(xml)
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -3, "expected_flat_letters": ["A"],
                   "chromatic_root_notes": []}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    # The Ab is already correctly flatted; the filter should examine it
    # and skip (no further modification).
    assert stats["chords_examined"] == 1
    assert stats["chords_flattened"] == 0
    # Confirm root stays Ab
    cs = next(iter(score.recurse().getElementsByClass(harmony.ChordSymbol)))
    assert cs.root().name == "A-"


def test_letters_outside_expected_set_untouched(tmp_path: Path) -> None:
    """In F major (one flat = B only), 'A' chord MUST NOT be flattened."""
    score = _score_with_chords(-1, ["A", "D", "G"])
    gt = _gt_path(tmp_path, {
        "song_a": {"key_fifths": -1, "expected_flat_letters": ["B"],
                   "chromatic_root_notes": []}
    })
    stats = apply_key_aware_flatten(
        score, song_name="song_a", groundtruth_path=gt,
    )
    assert stats["key_match"] is True
    assert stats["chords_flattened"] == 0  # none of A/D/G are in {B}
    chords = list(score.recurse().getElementsByClass(harmony.ChordSymbol))
    root_names = [c.root().name for c in chords]
    assert root_names == ["A", "D", "G"]


def test_load_groundtruth_missing_file_returns_empty_stub(tmp_path: Path) -> None:
    gt = load_groundtruth(tmp_path / "does-not-exist.json")
    assert gt == {"schema_version": 0, "songs": {}}


def test_load_groundtruth_malformed_json_returns_empty_stub(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    gt = load_groundtruth(p)
    assert gt == {"schema_version": 0, "songs": {}}
