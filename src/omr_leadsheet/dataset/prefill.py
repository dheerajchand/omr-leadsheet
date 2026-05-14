#!/usr/bin/env python3
"""Pre-fill labels.csv with the current classifier's best guess.

Reads labels.csv produced by dataset_extract_unlabeled.py, runs the
classifier on every crop (trying several crop windows and keeping the
best), and writes the prediction + confidence into the CSV. User then
only needs to *correct* the wrong ones.

Adds two columns:
  classifier_guess - current model's prediction
  classifier_conf - softmax confidence (0..1)

The `correct_label` column is left as it was. To accept the classifier's
guess for a row, you can set correct_label = classifier_guess in the
CSV - or leave it blank and we'll treat that as "skip / not a chord".

Usage: dataset_prefill_labels.py <labeling-dir>
"""
from __future__ import annotations
import csv
import os
import sys
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: prefill <labeling-dir>", file=sys.stderr)
        sys.exit(2)
    base = sys.argv[1]
    crops_dir = os.path.join(base, "crops")
    csv_path = os.path.join(base, "labels.csv")
    model_path = os.environ.get(
        "CHORD_CLASSIFIER_PATH",
        str(Path(__file__).resolve().parents[3] / "classifier.pt"),
    )
    from PIL import Image

    from omr_leadsheet.recognisers.cnn import ChordClassifier

    clf = ChordClassifier(model_path)
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    n = len(rows)
    for i, row in enumerate(rows, 1):
        fn = row["filename"]
        path = os.path.join(crops_dir, fn)
        if not os.path.exists(path):
            row["classifier_guess"] = ""
            row["classifier_conf"] = ""
            out_rows.append(row)
            continue
        img = Image.open(path).convert("L")
        W, H = img.size
        # Try several crops around the center to find the best confidence
        cx, cy = W / 2, H / 2
        windows = [
            (40, 40), (50, 50), (60, 50), (70, 55), (80, 60), (W, H),
        ]
        best = ("", 0.0)
        for w, h in windows:
            w = min(w, W); h = min(h, H)
            x0 = max(0, int(cx - w/2)); y0 = max(0, int(cy - h/2))
            crop = img.crop((x0, y0, x0 + w, y0 + h))
            cs, cf = clf.recognise(crop)
            if cs and cf > best[1]:
                best = (cs, cf)
        row["classifier_guess"] = best[0]
        row["classifier_conf"] = f"{best[1]:.2f}"
        out_rows.append(row)
        if i % 50 == 0:
            print(f"  {i}/{n}")

    fields = ["filename","source","audiveris_guess","context",
              "classifier_guess","classifier_conf","correct_label"]
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"Wrote {len(out_rows)} rows with predictions → {csv_path}")


if __name__ == "__main__":
    main()
