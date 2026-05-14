# Vision-language chord recognition

The pipeline can use a vision-language model (VLM) instead of, or alongside, the local CNN classifier (`docs/classifier.md`). VLMs handle accidentals and stacked extensions out of the box — no training required — and degrade to a graceful "skip" on non-chord crops rather than producing confident-but-wrong answers.

This document covers two equivalent options:

- **ollama** — FOSS, local, free, slower per-call.
- **Anthropic Claude vision API** — closed-source, cloud, ~$0.002 per crop, faster.

Both go through the same `pipeline/chord_vlm.py` module and the same `CHORD_VLM=1` flag — only the backend differs. Both cache responses by image content, so subsequent runs of the same songbook cost nothing.

---

## Why VLM at all

The local CNN (`docs/classifier.md`) classifies a chord-symbol crop into one of ~115 trained classes. It works well for common chords (A7, Dm7, F7) but has three failure modes that no amount of hand-labeling fully fixes:

1. **Sharp-key chords** (C#+, F#9/7, etc.) — rare in the training data, and adding more labeled examples shifts the root-prediction boundary and *regresses* the common chords.
2. **Stacked extensions** (9-over-7 written vertically) — the CNN reads the larger digit and drops the other.
3. **Non-chord crops** (a stray accent mark Audiveris filed as MARCATO, a tempo word) — the CNN is *forced* to classify into one of its 115 classes at some confidence, often producing a wrong-but-confident chord.

A VLM reads the crop the way a person does. Empirically, on the four most-confounding crops from the Gershwin songbook:

| crop | CNN guess | VLM guess | truth |
|---|---|---|---|
| song 13 m5 first | G+ conf 0.85 | C#+ | C#+ |
| song 13 m5 second | F7 conf 1.00 | F#9/7 | F#9/7 |
| bare A above m6 | A conf 0.68 | A | A |
| accent `>` glyph | (forced into some chord) | SKIP | not a chord |

---

## Option A — Ollama (local, free)

### Install

```bash
brew install ollama
ollama pull qwen2.5vl:7b   # ~5GB, Apache 2.0
# or, smaller and faster:
ollama pull minicpm-v:8b   # ~5.5GB
```

Ollama runs as a background service. The first `ollama pull` starts it.

### Run

```bash
export CHORD_VLM=1
export CHORD_VLM_BACKEND=ollama
export CHORD_VLM_MODEL=qwen2.5vl:7b     # optional, this is the default
./scripts/process_song.sh "Individual Songs/13 - Let's Call The Whole Thing Off.pdf"
```

### Performance

- First run on a 30-song book: ~3–5 seconds per unique chord crop on Apple Silicon. Roughly 15–25 minutes total for the whole book (with ~200–300 unique crops; the rest are cache hits).
- Re-runs: near-instant (cache hits).
- RAM: ~6–8 GB while the model is loaded. Ollama unloads after a few minutes idle.

### Limitations

- ~5% worse than Claude on edge cases (very degraded scans, exotic chord notations). For the Gershwin songbook this hasn't mattered in testing.
- Requires keeping the ollama process running. `ollama serve &` in another terminal if it isn't running.

---

## Option B — Anthropic Claude API (cloud, paid)

### Get a key

1. Sign up at https://console.anthropic.com/
2. Add billing (a $5 minimum is enough for many songbooks).
3. Create an API key, copy the `sk-…` value.

### Run

```bash
export ANTHROPIC_API_KEY=sk-…
export CHORD_VLM=1
export CHORD_VLM_BACKEND=anthropic
# optional model override; default is the cheapest current Haiku
export CHORD_VLM_MODEL=claude-haiku-4-5-20251001
./scripts/process_song.sh "Individual Songs/13 - Let's Call The Whole Thing Off.pdf"
```

### Cost

- Haiku: ~$0.002 per unique crop. ~$0.50 for a 30-song book first run.
- Sonnet: ~$0.02 per unique crop, ~$5 for the same book. Use this only if Haiku is missing things.
- Re-runs: $0 (cache hits).

### Performance

- ~1 second per call, ~3–5 minutes total for a 30-song book on first run.

---

## How it plugs into the pipeline

`pipeline/chord_row_ocr.py` has two places that need a chord recogniser:

1. **Refining tesseract-detected tokens.** Tesseract finds something chord-shaped at a position; the recogniser reads what it actually says. Without a recogniser, raw tesseract output is used (often wrong on jazz fonts).

2. **Recovering misclassified articulations.** Audiveris sometimes files a jazz-font `A` or `C#+` as a MARCATO articulation on the note below. The recovery pass walks every MARCATO/ACCENT, crops the glyph, and asks the recogniser to read it.

In both places, the priority order is:

```
CHORD_VLM=1 → VLMClassifier (ollama or Anthropic)
otherwise   → ChordClassifier (local CNN at $CHORD_CLASSIFIER_PATH)
otherwise   → no refinement; raw tesseract output
```

So you can keep the CNN as a fallback by leaving `CHORD_CLASSIFIER_PATH` set, and turn the VLM on per-run with `CHORD_VLM=1`.

---

## Caching

`pipeline/chord_vlm.py` writes one JSON file per unique crop to `~/.cache/chord_vlm/<hash>.json`:

```json
{"chord": "C#+", "conf": 0.95, "model": "qwen2.5vl:7b", "backend": "ollama"}
```

The hash includes the backend + model, so switching from ollama to Anthropic re-runs every crop (no false cross-backend hits). Deleting `~/.cache/chord_vlm/` forces a fresh run.

---

## When to use which

- **You want it to "just work" and don't mind 5 GB of disk** → ollama (Option A). This is the default.
- **You want the absolute best accuracy and have an API key already** → Anthropic (Option B).
- **You're on a machine without enough RAM for a 7B model, or no internet** → fall back to the local CNN by leaving `CHORD_VLM` unset.
- **You want fully offline, ultra-fast, and don't care about sharp-key chords** → local CNN only.

---

## Troubleshooting

**`urllib.error.URLError: [Errno 61] Connection refused`** — ollama isn't running. `ollama serve &` to start it.

**`ANTHROPIC_API_KEY env var not set`** — `export ANTHROPIC_API_KEY=sk-…` before running, or add it to your shell rc.

**VLM returns chord but pipeline still inserts wrong chord** — the chord-name might be in the .omr's ground truth and the diff insertion is preferring the CNN/Audiveris value at that beat. Check `process_song.sh` step 4 output for "duplicate" skip messages.

**Model returns commentary instead of just the chord** — most models follow the system prompt. If yours doesn't (e.g. older `llava` variants), try `qwen2.5vl:7b` or `minicpm-v:8b`. They're the best-tested for this task.
