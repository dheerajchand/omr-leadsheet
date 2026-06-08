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
