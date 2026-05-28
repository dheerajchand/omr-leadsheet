"""Regression: NW alignment prefers Gershwin-syllable truth token over
generic-English-word audi token when similarity is high (#70).

Symptom on #13 LCWTO m46 v1: Audiveris OCR'd the syllable as ``jab``
(a real English word). The lyric.txt has ``jah`` (correct Gershwin
syllable for ``pa-jah-mas``). Pre-fix, NW alignment's pass-1
``is_real_word(audi)`` early-out kept ``jab``; the truth ``jah``
never got a chance.

The fix narrows the early-out: when audi is a generic dict word but
truth is a Gershwin syllable with high similarity, prefer truth.
"""
from __future__ import annotations

from omr_leadsheet.pipeline.spell_check import GERSHWIN_SYLLABLES, sim


def test_gershwin_syllables_separated_from_modern_english() -> None:
    """The two sets stay distinct so the lyric-prefer rule can
    distinguish jazz syllables from regular modern words."""
    assert "jah" in GERSHWIN_SYLLABLES
    assert "pa" in GERSHWIN_SYLLABLES
    assert "ee" in GERSHWIN_SYLLABLES
    # Modern English isn't in the Gershwin set.
    assert "knows" not in GERSHWIN_SYLLABLES
    assert "goes" not in GERSHWIN_SYLLABLES
    assert "I'll".lower() not in GERSHWIN_SYLLABLES


def test_jab_jah_similarity_above_threshold() -> None:
    """The lyric-prefer rule's sim >=0.6 threshold catches jab/jah."""
    assert sim("jab", "jah") >= 0.6


def test_unrelated_tokens_below_threshold() -> None:
    """Distantly-similar tokens don't accidentally trigger the rule."""
    # "say" vs "lawf": one shared char, ratio ~0.29
    assert sim("say", "lawf") < 0.6
    # "see" vs "ee": shared 'ee', ratio 0.8 -- this DOES exceed the
    # threshold. That's actually the intent: in Gershwin lyric
    # context, "see" mis-OCR of "ee-ther" should be replaced.
    assert sim("see", "ee") >= 0.6


def test_apply_alignment_replaces_jab_with_jah(tmp_path) -> None:
    """End-to-end: an audi token 'jab' aligned to truth 'jah' is
    replaced with 'jah' after spell_check runs."""
    from music21 import stream, note as m21note
    from omr_leadsheet.pipeline.spell_check import (
        apply_alignment, audiveris_tokens,
    )
    # Build a one-note score with the lyric "jab".
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    n = m21note.Note("C5", quarterLength=1.0)
    n.addLyric("jab", lyricNumber=1)
    m.append(n)
    p.append(m)
    sc.append(p)

    part_idx, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["jah"]
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    # After alignment, the lyric should be "jah".
    lyric_text = next(iter(by_verse[1]))[2].text
    assert lyric_text == "jah", f"expected 'jah' after lyric-prefer; got {lyric_text!r}"


def test_apply_alignment_keeps_audi_when_truth_not_gershwin(tmp_path) -> None:
    """When truth is NOT a Gershwin syllable, the original kept_dict
    behaviour stays: real audi word wins."""
    from music21 import stream, note as m21note
    from omr_leadsheet.pipeline.spell_check import (
        apply_alignment, audiveris_tokens,
    )
    sc = stream.Score()
    p = stream.Part()
    m = stream.Measure(number=1)
    n = m21note.Note("C5", quarterLength=1.0)
    n.addLyric("cat", lyricNumber=1)  # generic dict word
    m.append(n)
    p.append(m)
    sc.append(p)

    _, all_notes, by_verse = audiveris_tokens(sc)
    truth = ["bat"]  # similar, but bat is NOT a Gershwin syllable
    apply_alignment(by_verse[1], truth, all_notes, verse_num=1)

    lyric_text = next(iter(by_verse[1]))[2].text
    assert lyric_text == "cat", f"audi should win when truth isn't a Gershwin syllable; got {lyric_text!r}"
