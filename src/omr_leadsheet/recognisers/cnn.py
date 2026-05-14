"""Load a trained chord-symbol classifier and run it on image crops.

The trained file (`classifier.pt`) bundles the model state and the
axis-class lists so this module is self-contained: no need to pass
ROOTS / QUALITIES / etc. at inference time.

Usage from another module::

    from omr_leadsheet.recognisers.cnn import ChordClassifier
    clf = ChordClassifier("classifier.pt")
    chord_str, confidence = clf.recognise("/path/to/crop.png")
    chord_str, confidence = clf.recognise_image(pil_image)
"""
from __future__ import annotations

import os

__all__ = ["ChordClassifier"]


class ChordClassifier:
    def __init__(self, model_path: str):
        import torch
        from PIL import Image  # noqa: F401  (proof Pillow is available)

        from omr_leadsheet.chord_ops.parser import ChordFields, format_chord
        from omr_leadsheet.training.train import IMG_H, IMG_W, build_model

        self._torch = torch
        self._format_chord = format_chord
        self._ChordFields = ChordFields

        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        self.roots = ckpt["roots"]
        self.qualities = ckpt["qualities"]
        self.extensions = ckpt["extensions"]
        self.alterations = ckpt["alterations"]
        self.img_w = ckpt.get("img_w", IMG_W)
        self.img_h = ckpt.get("img_h", IMG_H)

        self.model = build_model(
            len(self.roots), len(self.qualities),
            len(self.extensions), len(self.alterations),
        )
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()

    # ----- input preprocessing --------------------------------------------

    def _png_to_tensor(self, image_or_path):
        """Accept a path, a PIL.Image, or a numpy ndarray. Return a 1×1×H×W tensor."""
        from PIL import Image
        import torch
        if isinstance(image_or_path, (str, os.PathLike)):
            img = Image.open(image_or_path).convert("L")
        elif hasattr(image_or_path, "convert"):
            img = image_or_path.convert("L")
        else:
            # numpy ndarray
            img = Image.fromarray(image_or_path).convert("L")
        w, h = img.size
        target_ratio = self.img_w / self.img_h
        img_ratio = w / h if h else target_ratio
        if img_ratio > target_ratio:
            new_h = int(w / target_ratio) if target_ratio else h
            new_img = Image.new("L", (w, new_h), 255)
            new_img.paste(img, (0, (new_h - h) // 2))
        else:
            new_w = int(h * target_ratio)
            new_img = Image.new("L", (new_w, h), 255)
            new_img.paste(img, ((new_w - w) // 2, 0))
        new_img = new_img.resize((self.img_w, self.img_h))
        # Pillow 14 deprecation: prefer numpy if available, else fall back
        try:
            import numpy as np
            arr = np.asarray(new_img, dtype="float32") / 255.0
            t = torch.from_numpy(arr).unsqueeze(0).unsqueeze(0)
        except ImportError:
            t = torch.tensor(list(new_img.getdata()), dtype=torch.float32)
            t = (t / 255.0).reshape(1, 1, self.img_h, self.img_w)
        return t

    # ----- inference ------------------------------------------------------

    def recognise(self, image_or_path) -> tuple[str, float]:
        """Return (chord-string, joint-confidence) for the given crop."""
        torch = self._torch
        with torch.no_grad():
            x = self._png_to_tensor(image_or_path)
            pr, pq, pe, pa = self.model(x)
            soft_r = torch.softmax(pr, dim=1)[0]
            soft_q = torch.softmax(pq, dim=1)[0]
            soft_e = torch.softmax(pe, dim=1)[0]
            soft_a = torch.softmax(pa, dim=1)[0]
            i_r, i_q, i_e, i_a = (
                soft_r.argmax().item(), soft_q.argmax().item(),
                soft_e.argmax().item(), soft_a.argmax().item(),
            )
            # Joint confidence = product of per-axis top probabilities.
            # A simple, well-calibrated-ish measure for "trust this prediction".
            conf = float(soft_r[i_r] * soft_q[i_q] * soft_e[i_e] * soft_a[i_a])
        fields = self._ChordFields(
            root=self.roots[i_r],
            quality=self.qualities[i_q],
            extension=self.extensions[i_e],
            alteration=self.alterations[i_a],
        )
        return self._format_chord(fields), conf

    recognise_image = recognise  # alias


# CLI for spot-checking
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("image", nargs="+")
    args = ap.parse_args()
    clf = ChordClassifier(args.model)
    for path in args.image:
        chord, conf = clf.recognise(path)
        print(f"{path}: {chord!r}  conf={conf:.3f}")
