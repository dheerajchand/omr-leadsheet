"""Regression: verse-aware lyric extraction & alignment (#55, #56).

Two components tested here:

1. ``tesseract_verse_streams`` pair-detection: when consecutive lines
   share most of their first 5 tokens AND are similar in length,
   they're treated as a v1 / v2 pair. Otherwise both lines go to
   both verses.

2. (the extract_lyrics.sh lowercase-continuation merger is a shell
   script's inline Python; verified end-to-end by the dogfood, not
   by unit test here.)
"""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.pipeline.spell_check import tesseract_verse_streams


def test_pajamas_vs_oysters_pair(tmp_path: Path) -> None:
    """The #13 LCWTO refrain has two verses that start with "So if
    you ..." and diverge mid-phrase. The new first-N pair detection
    should catch them."""
    p = tmp_path / "lyrics.txt"
    p.write_text(
        "So, if you like pa-ja-mas And I like pa-jah-mas\n"
        "So, if you go for oyst-ers And I go for erst-ers\n",
        encoding="utf-8",
    )
    v1, v2 = tesseract_verse_streams(str(p))
    # v1 should be the pa-ja-mas line; v2 the oyst-ers line.
    assert "pa" in v1
    assert "oyst" in v2 or "oyst-ers" in v2 or "ers" in v2
    # Crucially, v1 must NOT contain the oyst tokens, and v2 must
    # not contain the pa-ja tokens (those are the verse-mixing
    # symptoms #55/#56 report).
    assert not any("oyst" in t for t in v1)
    assert not any("jah" in t for t in v2)


def test_unrelated_consecutive_lines_dont_pair(tmp_path: Path) -> None:
    """Two unrelated lines (different opening phrases) should NOT
    pair, even if they share a single common word."""
    p = tmp_path / "lyrics.txt"
    p.write_text(
        "Things have come to a pret-ty pass\n"
        "you like this and the oth-er\n",
        encoding="utf-8",
    )
    v1, v2 = tesseract_verse_streams(str(p))
    # Unpaired -> both lines go to BOTH streams
    assert "Things" in v1
    assert "Things" in v2
    assert "like" in v1
    assert "like" in v2


def test_length_mismatch_blocks_pair(tmp_path: Path) -> None:
    """Two lines that share opening tokens but are very different in
    length should not pair (one might be a fragment, the other a full
    line). The length guard prevents the false pair."""
    p = tmp_path / "lyrics.txt"
    # Line A is just two tokens; line B is much longer but starts
    # with the same words.
    p.write_text(
        "So if\n"
        "So if you go for oyst-ers And I go for erst-ers\n",
        encoding="utf-8",
    )
    v1, v2 = tesseract_verse_streams(str(p))
    # The very-short line A doesn't have enough tokens for the
    # first-N overlap to register; treated as unpaired -> both
    # lines go to BOTH verses.
    assert "oyst" in v1 or "oyst-ers" in v1
    assert "oyst" in v2 or "oyst-ers" in v2


def test_paired_lines_split_to_separate_verses(tmp_path: Path) -> None:
    """When two lines clearly pair, the second goes only to v2."""
    p = tmp_path / "lyrics.txt"
    p.write_text(
        "You say ee ther And I say eye ther\n"
        "You say laugh ter And I say lawf ter\n",
        encoding="utf-8",
    )
    v1, v2 = tesseract_verse_streams(str(p))
    # ee appears only in v1's line, laugh only in v2's.
    assert any("ee" == t.lower() for t in v1)
    assert any("laugh" == t.lower() for t in v2)
    assert not any("laugh" == t.lower() for t in v1)
    assert not any("ee" == t.lower() for t in v2)
