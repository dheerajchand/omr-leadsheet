"""Root-letter case normalisation in row_ocr._case_fix_root (#27).

Multi-character-only variant. The unguarded version of this rule
(promoting bare lowercase 'a' to chord 'A') cross-tested to
20-43 spurious A recoveries per song on the #20 set, where the
chord-row strip sometimes coincides with the lyric row and lyric
articles get OCR'd as 'a'. The multi-character constraint keeps
the safe recoveries (e.g. 'g7' -> 'G7', 'dm7' -> 'Dm7') and rejects
the bare-letter shape entirely; that residue is tracked separately
on #27 pending a strip-locality or confidence guard.

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


def test_lowercase_root_with_suffix_uppercased() -> None:
    assert _case_fix_root("g7") == "G7"
    assert _case_fix_root("dm7") == "Dm7"
    assert _case_fix_root("bm") == "Bm"
    assert _case_fix_root("cmaj7") == "Cmaj7"
    for v in ("g7", "dm7", "bm", "cmaj7"):
        assert CHORD_REGEX.match(_case_fix_root(v))


def test_bare_single_letter_NOT_promoted() -> None:
    """The high-false-positive shape -- a lyric 'a' article in the
    chord-row strip would otherwise become chord 'A'. Cross-song probe
    on #20 set showed 20-43 spurious A recoveries per song. The
    multi-character constraint blocks the bare shape entirely."""
    for v in ("a", "g", "d", "f"):
        out = _case_fix_root(v)
        assert out == v, f"bare {v!r} must NOT be promoted (got {out!r})"


def test_lowercase_letter_outside_root_range_left_alone() -> None:
    for v in ("hello", "if", "the", "iz"):
        assert _case_fix_root(v) == v
        assert not CHORD_REGEX.match(_case_fix_root(v))


def test_lowercase_root_but_invalid_suffix_left_alone() -> None:
    """'au', 'ag', 'fe' start with a lowercase root letter but the
    uppercased version still doesn't match CHORD_REGEX because 'u'
    isn't a valid chord-suffix char. Helper returns the original
    verbatim so the caller's regex check rejects."""
    for v in ("au", "ag", "fe"):
        out = _case_fix_root(v)
        assert out == v, f"{v!r} -> {out!r}"
        assert not CHORD_REGEX.match(out)


def test_empty_string_safe() -> None:
    assert _case_fix_root("") == ""
