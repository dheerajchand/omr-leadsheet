#!/usr/bin/env python3
"""Relabel chord-crop files in the dataset directory.

Reads a JSON file of `{"<old_label>": "<new_label>"}` mappings and moves
every PNG under `dataset/<old_label>/` into `dataset/<new_label>/`.

To merge a whole class into another, pass `{"C5": "C6"}`.
To delete a class entirely (e.g. OCR garbage), pass `{"BadClass": null}`.

Usage:
  clean_labels.py <dataset-dir> <mapping.json>

The mapping file:
  {
    "C5": "C6",
    "Bb": null,
    "F#": null
  }
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sys


def safe_filename(value: str) -> str:
    """Match dataset_extract.py's mangling."""
    return (value.replace("/", "_slash_")
            .replace("#", "sharp")
            .replace("+", "aug")
            .replace(" ", "")
            .replace(":", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir")
    ap.add_argument("mapping_json")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would happen, don't move anything")
    args = ap.parse_args()

    with open(args.mapping_json) as f:
        mapping: dict[str, str | None] = json.load(f)

    for old, new in mapping.items():
        src = os.path.join(args.dataset_dir, safe_filename(old))
        if not os.path.isdir(src):
            print(f"  (skip) {old}: no such folder {src}")
            continue
        files = [f for f in os.listdir(src) if f.lower().endswith(".png")]
        if new is None:
            print(f"  {old}: deleting {len(files)} crops")
            if not args.dry_run:
                shutil.rmtree(src)
            continue
        dst = os.path.join(args.dataset_dir, safe_filename(new))
        print(f"  {old} → {new}: moving {len(files)} crops")
        if args.dry_run:
            continue
        os.makedirs(dst, exist_ok=True)
        for f in files:
            shutil.move(os.path.join(src, f), os.path.join(dst, f))
        # Remove now-empty source dir
        try:
            os.rmdir(src)
        except OSError:
            pass


if __name__ == "__main__":
    main()
