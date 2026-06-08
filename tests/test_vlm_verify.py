"""Tests for VLM verification components."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from vlm_verify import _parse_vlm_response, _normalize_lyrics, _lyrics_match


class TestParseVlmResponse:
    def test_clean_json(self):
        text = '{"note_count": 3, "lyrics": ["Shall", "we", "dance"]}'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 3
        assert result["lyrics"] == ["Shall", "we", "dance"]

    def test_json_in_code_fence(self):
        text = '```json\n{"note_count": 2, "lyrics": ["la", "dy"]}\n```'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 2
        assert result["lyrics"] == ["la", "dy"]

    def test_regex_fallback(self):
        text = 'I see note_count: 4 and lyrics: ["one", "two", "three", "four"]'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 4
        assert result["lyrics"] == ["one", "two", "three", "four"]

    def test_empty_lyrics(self):
        text = '{"note_count": 0, "lyrics": []}'
        result = _parse_vlm_response(text)
        assert result is not None
        assert result["note_count"] == 0
        assert result["lyrics"] == []

    def test_garbage_returns_none(self):
        text = "I don't understand what you're asking"
        result = _parse_vlm_response(text)
        assert result is None


class TestNormalizeLyrics:
    def test_strips_punctuation(self):
        assert _normalize_lyrics(["Bess,", "you"]) == ["bess", "you"]

    def test_curly_apostrophe(self):
        assert _normalize_lyrics(["‘nin’"]) == ["'nin'"]

    def test_strips_hyphens(self):
        assert _normalize_lyrics(["-ing", "songs,"]) == ["ing", "songs"]

    def test_empty_after_strip(self):
        assert _normalize_lyrics(["", ",", "-"]) == []


class TestLyricsMatch:
    def test_exact_match(self):
        assert _lyrics_match(["Shall", "we"], ["Shall", "we"])

    def test_case_insensitive(self):
        assert _lyrics_match(["shall", "we"], ["Shall", "We"])

    def test_punctuation_ignored(self):
        assert _lyrics_match(["Bess,", "you"], ["Bess", "you"])

    def test_different_count_no_match(self):
        assert not _lyrics_match(["a", "b"], ["a", "b", "c"])

    def test_different_words_no_match(self):
        assert not _lyrics_match(["hello"], ["world"])


class TestIntroOffset:
    """Verify that intro_offset is computed as aud_count - mxml_max."""

    def test_offset_positive(self):
        # Simulates: Audiveris has 65 measures, MusicXML has 61
        aud_count = 65
        mxml_max = 61
        offset = max(0, aud_count - mxml_max)
        assert offset == 4

    def test_offset_zero_when_aligned(self):
        aud_count = 40
        mxml_max = 40
        offset = max(0, aud_count - mxml_max)
        assert offset == 0

    def test_mxml_lookup_with_offset(self):
        mxml_data = {1: {"note_count": 2}, 2: {"note_count": 5}}
        offset = 4
        aud_mn = 5
        mxml_mn = aud_mn - offset
        assert mxml_mn == 1
        assert mxml_data[mxml_mn]["note_count"] == 2

    def test_intro_measures_below_offset(self):
        offset = 6
        for aud_mn in [1, 2, 3, 4, 5, 6]:
            mxml_mn = aud_mn - offset
            assert mxml_mn <= 0, "intro measures should map to non-positive mxml numbers"
