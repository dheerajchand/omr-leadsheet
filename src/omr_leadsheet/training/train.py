#!/usr/bin/env python3
"""Train a multi-head CNN on the chord-symbol dataset.

Inputs:  a `dataset/<chord-label>/*.png` directory tree produced by
         dataset_extract.py.
Outputs: `classifier.pt` - a state-dict containing the trained model
         plus the label-class lists.

Architecture:
  * Shared CNN backbone (~30K params, runs on CPU)
  * Four prediction heads: root, quality, extension, alteration
  * Cross-entropy loss summed across heads, equal weight

Why four heads instead of one flat 116-way classifier?
  The chord vocabulary follows a strong factorisation - root × quality ×
  extension × alteration. Each axis has many more samples (~100+) than
  any individual chord-string label (often 1-2). Decomposed classifiers
  generalise to unseen combinations of seen axis-values.

Usage:
  train_classifier.py <dataset-dir> <output.pt>
                      [--epochs 30] [--batch-size 32] [--lr 1e-3]
                      [--val-split 0.1] [--min-per-class 3]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

from omr_leadsheet.chord_ops.parser import (
    ALTERATIONS,
    EXTENSIONS,
    QUALITIES,
    ROOTS,
    parse_chord,
)

# We import torch lazily so people can read the file without installing it.
def _import_torch():
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader
    return torch, nn, Dataset, DataLoader


# --------------------------------------------------------------------------
# Image loading (no torchvision dependency - keep the install footprint low)
# --------------------------------------------------------------------------

IMG_W, IMG_H = 64, 32  # standard input size after pad/resize


def load_png_as_tensor(path: str):
    """Load grayscale PNG → (1, IMG_H, IMG_W) torch float tensor in [0, 1]."""
    import torch
    from PIL import Image
    img = Image.open(path).convert("L")
    # Pad to aspect, then resize to IMG_W × IMG_H
    w, h = img.size
    target_ratio = IMG_W / IMG_H
    img_ratio = w / h
    if img_ratio > target_ratio:
        new_h = int(w / target_ratio)
        new_img = Image.new("L", (w, new_h), 255)
        new_img.paste(img, (0, (new_h - h) // 2))
    else:
        new_w = int(h * target_ratio)
        new_img = Image.new("L", (new_w, h), 255)
        new_img.paste(img, ((new_w - w) // 2, 0))
    new_img = new_img.resize((IMG_W, IMG_H))
    # Pillow 14 deprecates Image.getdata(); use numpy when available.
    try:
        import numpy as np
        arr = torch.from_numpy(np.asarray(new_img, dtype="float32")).unsqueeze(0)
    except ImportError:
        arr = torch.tensor(
            list(new_img.getdata()), dtype=torch.float32
        ).reshape(1, IMG_H, IMG_W)
    return arr / 255.0


def augment(t):
    """Light augmentation: random brightness + small translation."""
    import torch
    # Brightness jitter
    t = t * (0.85 + 0.3 * torch.rand(1).item())
    t = t.clamp(0, 1)
    # Random horizontal shift up to ±2 px
    shift = random.randint(-2, 2)
    if shift != 0:
        t = torch.roll(t, shifts=shift, dims=2)
    return t


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------


def build_index(dataset_dir: str, min_per_class: int) -> list[tuple[str, str]]:
    """Return [(file_path, raw_label), ...] keeping only classes with
    >= min_per_class samples and whose label parses."""
    counts: Counter = Counter()
    candidates: list[tuple[str, str]] = []
    for cls_dir in sorted(os.listdir(dataset_dir)):
        path = os.path.join(dataset_dir, cls_dir)
        if not os.path.isdir(path):
            continue
        label = cls_dir
        # Reverse the safe_filename mangling
        label = label.replace("sharp", "#").replace("aug", "+").replace("_slash_", "/")
        # `aug` is also a quality - we only mangle root+quality, so this
        # de-mangling is conservative; misreadings here just become unparseable
        if parse_chord(label) is None:
            continue
        files = [f for f in os.listdir(path) if f.lower().endswith(".png")]
        if len(files) < min_per_class:
            continue
        for f in files:
            candidates.append((os.path.join(path, f), label))
            counts[label] += 1
    return candidates


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


def build_model(n_root: int, n_quality: int, n_ext: int, n_alt: int):
    """Small CNN with four classification heads sharing a backbone."""
    torch, nn, *_ = _import_torch()

    class ChordCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = nn.Sequential(
                nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
                nn.AdaptiveAvgPool2d((2, 4)),
                nn.Flatten(),
            )
            self.feat = nn.Sequential(nn.Linear(64 * 2 * 4, 128), nn.ReLU(), nn.Dropout(0.3))
            self.head_root = nn.Linear(128, n_root)
            self.head_qual = nn.Linear(128, n_quality)
            self.head_ext = nn.Linear(128, n_ext)
            self.head_alt = nn.Linear(128, n_alt)

        def forward(self, x):
            h = self.feat(self.backbone(x))
            return (self.head_root(h), self.head_qual(h),
                    self.head_ext(h), self.head_alt(h))

    return ChordCNN()


# --------------------------------------------------------------------------
# Train loop
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset_dir")
    ap.add_argument("output_path")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-split", type=float, default=0.1)
    ap.add_argument("--min-per-class", type=int, default=3)
    args = ap.parse_args()

    torch, nn, Dataset, DataLoader = _import_torch()

    index = build_index(args.dataset_dir, args.min_per_class)
    print(f"Kept {len(index)} samples across "
          f"{len({lbl for _, lbl in index})} classes")

    # Parse all labels
    parsed = []
    for path, label in index:
        f = parse_chord(label)
        if f is None:
            continue
        parsed.append((path, f))
    print(f"Parsed {len(parsed)} samples")

    random.seed(42)
    random.shuffle(parsed)
    n_val = max(1, int(len(parsed) * args.val_split))
    val, train = parsed[:n_val], parsed[n_val:]
    print(f"train: {len(train)}  val: {len(val)}")

    root_idx = {r: i for i, r in enumerate(ROOTS)}
    qual_idx = {q: i for i, q in enumerate(QUALITIES)}
    ext_idx = {e: i for i, e in enumerate(EXTENSIONS)}
    alt_idx = {a: i for i, a in enumerate(ALTERATIONS)}

    class ChordDataset(Dataset):
        def __init__(self, items, augment_input: bool):
            self.items = items
            self.augment = augment_input

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            path, f = self.items[i]
            t = load_png_as_tensor(path)
            if self.augment:
                t = augment(t)
            return t, (
                root_idx[f.root], qual_idx[f.quality],
                ext_idx[f.extension], alt_idx[f.alteration],
            )

    model = build_model(len(ROOTS), len(QUALITIES), len(EXTENSIONS), len(ALTERATIONS))
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()

    train_loader = DataLoader(ChordDataset(train, augment_input=True),
                              batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(ChordDataset(val, augment_input=False),
                            batch_size=args.batch_size, shuffle=False)

    for epoch in range(args.epochs):
        model.train()
        train_loss = 0.0
        for x, (r, q, e, a) in train_loader:
            opt.zero_grad()
            pr, pq, pe, pa = model(x)
            loss = (loss_fn(pr, r) + loss_fn(pq, q)
                    + loss_fn(pe, e) + loss_fn(pa, a))
            loss.backward()
            opt.step()
            train_loss += loss.item() * x.size(0)

        model.eval()
        with torch.no_grad():
            correct = [0, 0, 0, 0]
            joint_correct = 0
            total = 0
            for x, (r, q, e, a) in val_loader:
                pr, pq, pe, pa = model(x)
                preds = [pr.argmax(1), pq.argmax(1), pe.argmax(1), pa.argmax(1)]
                trues = [r, q, e, a]
                for i, (p, t) in enumerate(zip(preds, trues)):
                    correct[i] += (p == t).sum().item()
                joint = ((preds[0] == r) & (preds[1] == q)
                         & (preds[2] == e) & (preds[3] == a))
                joint_correct += joint.sum().item()
                total += x.size(0)
        print(f"epoch {epoch+1:3d}/{args.epochs}  loss {train_loss/len(train):.3f}  "
              f"val root {correct[0]/total:.2%}  qual {correct[1]/total:.2%}  "
              f"ext {correct[2]/total:.2%}  alt {correct[3]/total:.2%}  "
              f"joint {joint_correct/total:.2%}")

    torch.save({
        "state_dict": model.state_dict(),
        "roots": ROOTS, "qualities": QUALITIES,
        "extensions": EXTENSIONS, "alterations": ALTERATIONS,
        "img_w": IMG_W, "img_h": IMG_H,
    }, args.output_path)
    print(f"saved {args.output_path}")


if __name__ == "__main__":
    main()
