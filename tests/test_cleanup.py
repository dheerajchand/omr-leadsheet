"""MusicXML tuplet cleanup."""
from __future__ import annotations

from pathlib import Path

from omr_leadsheet.pipeline.cleanup import cleanup, fix_tuplets_in_measure


_UNBALANCED = (
    '<measure number="1">'
    '<note><pitch><step>C</step><octave>4</octave></pitch>'
    '<notations><tuplet type="start" number="1"/></notations></note>'
    '<note><pitch><step>D</step><octave>4</octave></pitch></note>'
    "</measure>"
)


_BALANCED = (
    '<measure number="2">'
    '<note><pitch><step>E</step><octave>4</octave></pitch>'
    '<notations><tuplet type="start"/></notations></note>'
    '<note><pitch><step>F</step><octave>4</octave></pitch>'
    '<notations><tuplet type="stop"/></notations></note>'
    "</measure>"
)


def test_fix_measure_strips_unbalanced_tuplet() -> None:
    out = fix_tuplets_in_measure(_UNBALANCED)
    assert 'tuplet type="start"' not in out
    assert "<step>C</step>" in out, "notes must survive the cleanup"


def test_fix_measure_keeps_balanced_tuplet() -> None:
    assert fix_tuplets_in_measure(_BALANCED) == _BALANCED


def test_cleanup_writes_file(tmp_path: Path) -> None:
    src = tmp_path / "in.xml"
    src.write_text(f"<score>{_UNBALANCED}{_BALANCED}</score>")
    dst = tmp_path / "out.xml"
    fixed = cleanup(src, dst)
    assert fixed == 1
    text = dst.read_text()
    assert "<step>C</step>" in text
    assert "<step>E</step>" in text


def test_cleanup_aggressive_strips_everything(tmp_path: Path) -> None:
    src = tmp_path / "in.xml"
    src.write_text(f"<score>{_UNBALANCED}{_BALANCED}</score>")
    dst = tmp_path / "out.xml"
    cleanup(src, dst, aggressive=True)
    text = dst.read_text()
    assert "<tuplet" not in text
