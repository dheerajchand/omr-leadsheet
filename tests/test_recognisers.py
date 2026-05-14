"""Recogniser protocol contract.

A recogniser is any object with ``recognise(image_or_path) -> tuple[str, float]``.
Both ``ChordClassifier`` (CNN) and ``VLMClassifier`` implement this informally;
the contract is documented here so future backends are interchangeable.
"""
from __future__ import annotations

from pathlib import Path

import pytest


class StubRecogniser:
    """Minimal recogniser returning a canned answer; for protocol tests only."""

    def __init__(self, answer: str = "C", conf: float = 0.99) -> None:
        self.answer = answer
        self.conf = conf
        self.calls = 0

    def recognise(self, image: object) -> tuple[str, float]:
        self.calls += 1
        return self.answer, self.conf


def test_stub_returns_tuple() -> None:
    stub = StubRecogniser()
    chord, conf = stub.recognise("anything")
    assert chord == "C"
    assert 0.0 <= conf <= 1.0


def test_blob_scan_uses_recogniser(tmp_path: Path) -> None:
    PIL = pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    from omr_leadsheet.recognisers.blobs import scan_chord_row_blobs

    img = Image.new("L", (300, 60), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle([50, 20, 75, 50], outline=0, width=2)
    draw.line([(55, 25), (70, 45)], fill=0, width=2)
    src = tmp_path / "strip.png"
    img.save(src)

    stub = StubRecogniser(answer="A7", conf=0.9)
    results = scan_chord_row_blobs(str(src), 0, 60, stub)
    assert stub.calls >= 1
    assert all(chord == "A7" for _, chord, _ in results)
