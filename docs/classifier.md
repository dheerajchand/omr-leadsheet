# Building a chord-symbol image classifier

The single highest-impact improvement to this pipeline is replacing
tesseract's generic OCR with a small neural-network classifier
specifically trained on chord-symbol crops. Chord glyphs are a small,
closed vocabulary (~50 distinct symbols across a typical jazz songbook)
and existing OMR data gives you most of the labels for free.

This document walks through doing that. It's a one-weekend project,
not a one-week one, and the payoff is permanent: once trained, the
classifier replaces tesseract in `chord_row_ocr.py` and the pipeline's
chord-recognition rate jumps from ~85% to ~99%.

## Why this is tractable

* The vocabulary is small. Real-world jazz lead sheets use roughly 50
  chord symbols (`C, Cm, C7, Cmaj7, C6, Cm6, Cm7, Cdim, Caug, C+,
  C7b5, C7#5, C9, Cm9, C11, C13, …` repeated for each of 12 roots).
* The crops are small (~60×40 pixels) and the visual variation is low
  — same handful of fonts across a songbook, same glyph shapes for
  digits, sharps, and flats.
* Training data is free: every chord Audiveris **already** recognised
  correctly is a labeled example. You can extract thousands per book.
* Inference is fast — a few ms per crop with a small CNN — and trivial
  to integrate.

## Strategy in one paragraph

Train a CNN that maps a `(H, W) → chord-symbol string` for ~50–200
chord classes. Get most of your training set from the `<chord-name>`
glyphs Audiveris labelled correctly in your `.omr` files (these come
with both the value string and the pixel-exact bounds). Augment with
corrections from `corrections.json` files (the human-in-the-loop
review output) for chords Audiveris missed. Validate on a held-out
song. Drop into `chord_row_ocr.py` behind a feature flag.

## Step-by-step

### Step 1: Extract a labeled dataset from existing `.omr` files

`omr-lead dataset extract` (module:
`omr_leadsheet.dataset.extract`) walks every `.omr` in your
`music_xml/` directory and emits crops:

```python
# pseudocode
for omr in omr_dir.glob("*.omr"):
    extract_sheet_pngs(omr) → each sheet's BINARY.png
    for chord_name in parse_chord_names(omr):
        if chord_name.value is not None:           # Audiveris parsed it
            x, y, w, h = chord_name.bounds
            crop = binary_png[y-pad:y+h+pad, x-pad:x+w+pad]
            save(crop, label=chord_name.value)
```

For our 30-song Gershwin book this yields ~600–800 labeled crops with
no manual work. Augment with rotation/scale/noise to get ~5,000
examples. Group by chord class; aim for at least 10 examples of each
class you want to recognise.

Save as `dataset/<chord>/<hash>.png` so you can browse by class and
spot-check labels.

### Step 2: Define a tiny CNN

Pure PyTorch, runs on CPU. Total params ~50K:

```python
import torch.nn as nn

class ChordCNN(nn.Module):
    def __init__(self, n_classes: int):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 8)),
        )
        self.head = nn.Sequential(
            nn.Flatten(), nn.Linear(64 * 4 * 8, 128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, n_classes),
        )

    def forward(self, x):
        return self.head(self.features(x))
```

Input: 32×64 grayscale crops (pad/resize each chord to that size).
Output: logits over your chord class set.

### Step 3: Train

Standard recipe:

* Dataset → 90/10 train/val split (preferably stratified, and ideally
  by song so a song's chords are entirely in either train or val).
* Random rotation ±5°, scale 0.95–1.05, brightness jitter, occasional
  morphological dilation/erosion (these match the kinds of variation
  you'll see across scan quality).
* `nn.CrossEntropyLoss`, Adam, learning rate 1e-3, batch size 32,
  20–50 epochs.
* Track top-1 accuracy and per-class precision/recall. Per-class
  matters: getting "C" right is easy; the chord-recognition gain
  comes from getting "C#+" right.

For ~5,000 examples × 50 classes you should see 95%+ val accuracy
within an hour of training on a laptop CPU.

### Step 4: Evaluate on a held-out song

Pick a song the model never saw during training. Run the chord-row
OCR pipeline against it, then run the classifier against the same
crops, then diff against the truth (your `corrections.json` if
available, else manual labeling).

Measure:

* **Recall on tesseract-missed chords** — the cases that previously
  fell through. This is the headline metric.
* **Precision on tesseract-caught chords** — make sure the
  classifier isn't worse than tesseract on the easy cases.
* **Per-class breakdown** — especially the chromatic / extended
  chords that motivated this project (G⁹⁷, C#+, F#⁹⁷, etc.).

### Step 5: Integrate into the pipeline

Add an optional code path in `chord_row_ocr.py`:

```python
if CHORD_CLASSIFIER_PATH:
    classifier = load_classifier(CHORD_CLASSIFIER_PATH)
    # Replace _ocr_run with a function that crops candidate windows
    # and runs them through `classifier` instead of tesseract.
```

Keep the tesseract path as fallback so the repo stays runnable
without the trained model. Set `CHORD_CLASSIFIER_PATH` via env
var or `env.sh`.

### Step 6: Active learning loop

The killer feature: every time the user corrects a chord in
`review.html` and exports `corrections.json`, that becomes new
training data. The `omr_leadsheet.dataset.import_corrections` module
already handles the labeling-UI side; a future
`incorporate_corrections` step would close the loop by walking
review-tool exports:

1. For each correction `m17 chord at beat 3: A7`, locate the
   measure's region in the source BINARY.png.
2. Crop the suspect region (use Audiveris's chord-name bounds
   if available, else estimate from the chord_row_ocr x-position).
3. Save with the corrected label into `dataset/`.
4. Trigger an incremental re-train.

After a few correction cycles the classifier converges to your
specific source's font and your project's chord vocabulary.

## Practical first session

If you want to validate the approach before committing to the full
project, a 2-hour session can do this:

1. Write `dataset_extract.py` (~30 min).
2. Eyeball the resulting `dataset/` to confirm labels look right.
3. Train the tiny CNN on the existing crops, no augmentation
   (~30 min including the training run).
4. Print the val confusion matrix.

If you see ≥90% val accuracy on that first untuned run, the full
project is worth doing. If you see <80%, the bottleneck is probably
data quality — look at your `dataset/` for mis-labeled crops or
ambiguous classes that should be merged.

## Alternatives considered

* **Fine-tune Tesseract on the chord font.** Tesseract supports
  fine-tuning, but it's geared for general text and the training
  pipeline is fiddly. Not worth it for a 50-class vocabulary.
* **Audiveris's built-in trainer.** Audiveris has a UI for training
  its symbol classifier. Useful for fixing detection (not just
  recognition) but slower to iterate on than a Python CNN. Worth
  doing in parallel for the specific case of missed `+` and stacked
  digits.
* **Large vision-language model.** Overkill — chord symbols are
  literally a small image classification problem, and a tiny CNN
  beats VLMs on latency, cost, and reliability for this class of task.
