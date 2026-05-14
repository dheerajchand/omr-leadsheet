"""chord_blob_scan ink-cluster detection."""
from __future__ import annotations

from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from omr_leadsheet.recognisers.blobs import _find_blobs


def _make_strip(tmp_path: Path, glyphs: list[tuple[int, int]]) -> Path:
    """Render a white strip with text-like outlines at each (x, y).

    Uses hollow rectangles (frames) so the ink-density gate inside
    _find_blobs (which filters out solid bars like staff lines) accepts
    the result. Real chord glyphs have similar density: ~10-25% dark.
    """
    img = Image.new("L", (500, 80), 255)
    draw = ImageDraw.Draw(img)
    for x, y in glyphs:
        draw.rectangle([x, y, x + 20, y + 25], outline=0, width=2)
        draw.line([(x + 5, y + 5), (x + 15, y + 20)], fill=0, width=2)
    out = tmp_path / "strip.png"
    img.save(out)
    return out


def test_detects_separated_glyphs(tmp_path: Path) -> None:
    strip = _make_strip(tmp_path, [(40, 30), (200, 30), (380, 30)])
    blobs = _find_blobs(str(strip), 0, 80)
    assert len(blobs) == 3
    x_centers = [(b.x_left + b.x_right) // 2 for b in blobs]
    assert x_centers == sorted(x_centers)


def test_ignores_too_narrow_blobs(tmp_path: Path) -> None:
    img = Image.new("L", (300, 80), 255)
    ImageDraw.Draw(img).rectangle([100, 30, 105, 50], fill=0)  # 6 px wide
    strip = tmp_path / "thin.png"
    img.save(strip)
    assert _find_blobs(str(strip), 0, 80) == []


def test_returns_empty_on_blank(tmp_path: Path) -> None:
    Image.new("L", (400, 60), 255).save(tmp_path / "blank.png")
    assert _find_blobs(str(tmp_path / "blank.png"), 0, 60) == []
