#!/usr/bin/env python3
"""Apply hand-corrected labels from labels.csv to the training dataset.

Reads the CSV produced by the labeling UI. For every row with a
non-empty `correct_label`, moves (copies) the crop into
<dataset-dir>/<safe_label>/<filename> so it's picked up by
train_classifier.py on the next training run.

Rows with empty `correct_label` are treated as "skip / not a chord"
and ignored.

Usage: dataset_import_corrections.py <labeling-dir> <dataset-dir>
"""
from __future__ import annotations
import csv
import os
import re
import shutil
import sys


def safe_filename(value: str) -> str:
    return (
        value.replace("/", "_slash_")
        .replace("#", "sharp")
        .replace("+", "aug")
        .replace(" ", "")
        .replace(":", "")
    )


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: dataset_import_corrections.py <labeling-dir> <dataset-dir>", file=sys.stderr)
        sys.exit(2)
    base, dataset = sys.argv[1], sys.argv[2]
    crops_dir = os.path.join(base, "crops")
    csv_path = os.path.join(base, "labels.csv")
    os.makedirs(dataset, exist_ok=True)

    moved: dict[str, int] = {}
    skipped = 0
    missing = 0
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            label = (row.get("correct_label") or "").strip()
            if not label:
                skipped += 1
                continue
            src = os.path.join(crops_dir, row["filename"])
            if not os.path.exists(src):
                missing += 1
                continue
            cls = safe_filename(label)
            cls_dir = os.path.join(dataset, cls)
            os.makedirs(cls_dir, exist_ok=True)
            dst = os.path.join(cls_dir, row["filename"])
            shutil.copy2(src, dst)
            moved[label] = moved.get(label, 0) + 1

    print(f"Imported {sum(moved.values())} labeled crops into {dataset}")
    print(f"  Skipped (no label):       {skipped}")
    print(f"  Missing crop files:       {missing}")
    print()
    print("Per-class additions:")
    for k in sorted(moved, key=lambda x: -moved[x]):
        print(f"  {k:<15}  +{moved[k]}")


if __name__ == "__main__":
    main()
