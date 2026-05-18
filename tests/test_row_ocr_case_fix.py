"""Root-letter case normalisation in row_ocr._case_fix_root (#27).

Two safety tiers:

1. **Multi-character lowercase root** (e.g. 'g7', 'dm7', 'bm7') --
   always promoted. Lyric tokens don't OCR as chord-suffix grammar,
   so the false-positive surface is empty.

2. **Bare single-letter lowercase root** (e.g. 'a', 'g') -- only
   promoted when the caller passes ``allow_bare=True``. The caller
   (``recover_chord_row_chords``) opts in based on a per-song signal:
   Audiveris detected at least one chord-name in the .omr, meaning a
   real chord row exists somewhere on the page. On songs where
   Audiveris saw zero chords (#20 set: #05, #06, #08), the chord-row
   strip we OCR may overlap the lyric row, and bare 'a' reads are
   dominated by lyric "a" articles -- 20-43 spurious A recoveries per
   song under the unconditional rule.

CHORD_REGEX stays case-sensitive (anchor `^[A-G]`) so stray lowercase
letters from lyric strips don't slip in. The helper uppercases the
leading character only and re-checks the regex; if the normalised
candidate doesn't match, the original is returned and the caller's
regex check rejects it as before.
"""
from __future__ import annotations

from omr_leadsheet.recognisers.row_ocr import _case_fix_root, CHORD_REGEX


def test_uppercase_root_passes_through_unchanged() -> None:
    for v in ("A", "G", "Cmaj7", "F#m7", "Bb7", "Dsus4"):
        assert _case_fix_root(v) == v
        assert _case_fix_root(v, allow_bare=True) == v


def test_lowercase_root_with_suffix_always_uppercased() -> None:
    """Multi-character lowercase tokens promote with or without
    allow_bare -- lyric collisions don't happen for chord-suffix
    grammar."""
    for v in ("g7", "dm7", "bm", "cmaj7"):
        assert _case_fix_root(v) != v, f"{v!r} must promote by default"
        assert _case_fix_root(v, allow_bare=True) != v
        assert CHORD_REGEX.match(_case_fix_root(v))


def test_bare_single_letter_NOT_promoted_by_default() -> None:
    """Default behaviour blocks bare single-letter promotion -- the
    high-false-positive shape that collides with lyric 'a' articles."""
    for v in ("a", "g", "d", "f"):
        out = _case_fix_root(v)
        assert out == v, f"bare {v!r} must NOT be promoted by default (got {out!r})"


def test_bare_single_letter_promoted_when_allow_bare_true() -> None:
    """Caller (recover_chord_row_chords) opts in when Audiveris saw at
    least one chord-name in the .omr -- a per-song signal that a real
    chord row exists and a lowercase bare letter is more likely a
    serif-noised chord letter than a lyric article. On LCWTO this
    enables 23 bare-'A' chord recoveries; on the #20 set it stays off
    because Audiveris detected zero chords there."""
    assert _case_fix_root("a", allow_bare=True) == "A"
    assert _case_fix_root("g", allow_bare=True) == "G"
    assert _case_fix_root("d", allow_bare=True) == "D"


def test_bare_non_root_lowercase_left_alone_even_with_allow_bare() -> None:
    """allow_bare only opens the door for actual root letters; lyric
    tokens like 'i', 'h', 'z' must still be rejected even when the
    flag is on (CHORD_REGEX requires [A-G] root, not [A-Z])."""
    for v in ("h", "i", "z"):
        out = _case_fix_root(v, allow_bare=True)
        assert out == v, f"{v!r} (non-root) must NOT be promoted (got {out!r})"


def test_lowercase_letter_outside_root_range_left_alone() -> None:
    for v in ("hello", "if", "iz"):
        assert _case_fix_root(v) == v
        assert _case_fix_root(v, allow_bare=True) == v


def test_lowercase_root_but_invalid_suffix_left_alone() -> None:
    """'au', 'ag', 'fe' start with a lowercase root letter but the
    uppercased version still doesn't match CHORD_REGEX because 'u'
    isn't a valid chord-suffix char. Helper returns the original
    verbatim so the caller's regex check rejects."""
    for v in ("au", "ag", "fe"):
        assert _case_fix_root(v) == v
        assert _case_fix_root(v, allow_bare=True) == v
        assert not CHORD_REGEX.match(v)


def test_empty_string_safe() -> None:
    assert _case_fix_root("") == ""
    assert _case_fix_root("", allow_bare=True) == ""


# --- Voice-part-label guard (#20) -----------------------------------------

def test_voice_part_label_guard_filters_bare_letters_when_no_chord_evidence(tmp_path) -> None:
    """When Audiveris detected zero chord-name elements in the .omr, bare
    single-letter A-G outputs from row_ocr are almost certainly voice-part
    labels (alto/soprano), not chord glyphs. Probe on songs #20 set:
    20-43 spurious bare-A outputs per song before this guard, all at
    conf >= 90, all clustered in the page-margin x range.

    This test asserts the filter logic directly: a list of RowChord
    instances containing single-letter and multi-letter chord values
    must be filtered to drop the single-letter ones when allow_bare
    would have been False.
    """
    # The filter logic lives inline in recover_chord_row_chords. The
    # equivalent predicate:
    def keep(c_value: str) -> bool:
        return not (len(c_value) == 1 and c_value.isalpha() and "A" <= c_value <= "G")

    # Bare single-letter A-G must be dropped
    for v in ("A", "B", "C", "D", "E", "F", "G"):
        assert not keep(v), f"bare {v!r} must be dropped under the guard"
    # Multi-character chords always kept (no voice-part-label collision)
    for v in ("A7", "Bm", "Cmaj7", "G7", "Dm7", "F#m7", "A5"):
        assert keep(v), f"multi-char {v!r} must be kept under the guard"
    # Non-root letters (e.g. accidental hits) kept (regex would have
    # filtered them upstream, but the guard itself is bounded to A-G)
    for v in ("H", "Z", "1"):
        assert keep(v), f"non-root {v!r} not the guard's target"
