"""qwen2.5vl crop padding (#20 followup).

The qwen2.5vl image processor in ollama enforces a minimum of 28 px on
each axis (the SmartResize factor). Chord-symbol crops can be small
slivers (e.g. 23 px tall from the chord-row strip) which trigger a
server-side panic returning HTTP 500. _pad_to_min_size pads the crop
on the right/bottom with white before encoding.
"""
from __future__ import annotations

import io
from PIL import Image

from omr_leadsheet.recognisers.vlm import VLMClassifier


def _png_bytes(w: int, h: int, mode: str = "L") -> bytes:
    im = Image.new(mode, (w, h), 255 if mode in ("L", "RGB") else (255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _size(b: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(b)).size


def test_short_crop_padded_to_min_height() -> None:
    raw = _png_bytes(100, 23)
    out = VLMClassifier._pad_to_min_size(raw)
    assert _size(out) == (100, 28)


def test_narrow_crop_padded_to_min_width() -> None:
    raw = _png_bytes(20, 60)
    out = VLMClassifier._pad_to_min_size(raw)
    assert _size(out) == (28, 60)


def test_both_dimensions_below_min_padded() -> None:
    raw = _png_bytes(10, 10)
    out = VLMClassifier._pad_to_min_size(raw)
    assert _size(out) == (28, 28)


def test_already_large_crop_unchanged() -> None:
    raw = _png_bytes(60, 60)
    out = VLMClassifier._pad_to_min_size(raw)
    assert out == raw, "no padding should be applied when both axes >= 28"


def test_rgb_mode_padded_with_white() -> None:
    raw = _png_bytes(20, 20, mode="RGB")
    out = VLMClassifier._pad_to_min_size(raw)
    im = Image.open(io.BytesIO(out))
    assert im.size == (28, 28)
    # The bottom-right corner that was added should be white.
    assert im.getpixel((27, 27)) == (255, 255, 255)
