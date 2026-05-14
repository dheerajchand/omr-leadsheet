#!/usr/bin/env python3
"""Vision-language chord recogniser.

Reads a jazz chord-symbol crop and returns the recognised chord string.
This is the high-accuracy alternative to the local CNN classifier — it
doesn't need training data, handles novel combinations (C#+, F#9/7,
etc.) out of the box, and degrades to "unsure" rather than producing
confident-but-wrong answers like the CNN.

Two backends are supported:

  ollama       — local FOSS model (Qwen2.5-VL or MiniCPM-V) via the
                 ollama server at http://localhost:11434. Free, private,
                 offline-capable. Slower per-call (~3-5s on Apple Silicon).
                 Requires: `brew install ollama && ollama pull qwen2.5vl:7b`

  anthropic    — Anthropic Claude vision API. Paid, ~$0.002 per crop
                 with Haiku. Faster (~1s/call) and slightly more
                 accurate on edge cases. Requires ANTHROPIC_API_KEY.

Caching: every crop is hashed by content; identical crops reuse cached
answers. A typical 30-song book has thousands of chord glyphs but only
~200-300 unique visual instances, so the cache hit rate is very high
on re-runs and the cost / latency is mostly paid once.

Selection:
  export CHORD_VLM_BACKEND=ollama         # default
  export CHORD_VLM_MODEL=qwen2.5vl:7b     # ollama model tag, optional
  export CHORD_VLM_BACKEND=anthropic
  export ANTHROPIC_API_KEY=sk-...

Library usage:
  from chord_vlm import VLMClassifier
  clf = VLMClassifier()  # reads env for backend
  chord, conf = clf.recognise("/path/to/crop.png")

CLI usage:
  chord_vlm.py /path/to/crop.png [more crops...]
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error


SYSTEM_PROMPT = """You are an OCR system for jazz chord symbols printed in piano-vocal sheet music.
Crops come from scanned Real-Book / jazz-standard sheets.
The font is a serif text font; accidentals (sharp #, flat b) are tiny musical glyphs next to the root letter.
Extensions can stack vertically (a 9 over a 7 means "9/7").
Plus-sign means augmented. A small "m" means minor. "maj7" is major-7.

Output ONLY the chord symbol in shorthand: A7, Bbm, F#9/7, C#+, Em7, Dmaj7, A7(b5), etc.
If the image is not a chord (an accent mark, ornament, lyric text, random ink), output exactly: SKIP
If you cannot read it clearly, output exactly: UNSURE
No commentary, no explanation, no quotes — just the chord string or SKIP or UNSURE."""

CHORD_REGEX = re.compile(r"^[A-G][#b♯♭]?(?:maj|min|aug|dim|sus|m|M|b|#|\+|\-|[0-9/()])*$")


class VLMClassifier:
    def __init__(
        self,
        backend: str | None = None,
        model: str | None = None,
        cache_dir: str = "~/.cache/chord_vlm",
    ):
        self.backend = backend or os.environ.get("CHORD_VLM_BACKEND", "ollama")
        self.cache_dir = os.path.expanduser(cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)

        if self.backend == "anthropic":
            self.model = model or os.environ.get(
                "CHORD_VLM_MODEL", "claude-haiku-4-5-20251001"
            )
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not self.api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY env var not set. Get a key at "
                    "https://console.anthropic.com/ — then "
                    "`export ANTHROPIC_API_KEY=sk-...` before running."
                )
        elif self.backend == "ollama":
            self.model = model or os.environ.get(
                "CHORD_VLM_MODEL", "qwen2.5vl:7b"
            )
            self.ollama_url = os.environ.get(
                "OLLAMA_URL", "http://localhost:11434"
            )
        else:
            raise ValueError(
                f"Unknown VLM backend {self.backend!r}. "
                f"Set CHORD_VLM_BACKEND=ollama or anthropic."
            )

    # --- caching -----------------------------------------------------------

    def _hash(self, img_bytes: bytes) -> str:
        return hashlib.sha256(img_bytes + self.backend.encode() + self.model.encode()).hexdigest()[:16]

    def _cache_path(self, h: str) -> str:
        return os.path.join(self.cache_dir, f"{h}.json")

    def _load_cached(self, h: str) -> tuple[str, float] | None:
        p = self._cache_path(h)
        if not os.path.exists(p):
            return None
        try:
            with open(p) as f:
                d = json.load(f)
            return d["chord"], d["conf"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def _save_cached(self, h: str, chord: str, conf: float) -> None:
        try:
            with open(self._cache_path(h), "w") as f:
                json.dump(
                    {"chord": chord, "conf": conf,
                     "model": self.model, "backend": self.backend}, f,
                )
        except OSError:
            pass

    # --- backends ----------------------------------------------------------

    def _call_anthropic(self, img_bytes: bytes) -> str:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        body = {
            "model": self.model,
            "max_tokens": 32,
            "system": SYSTEM_PROMPT,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": b64,
                    }},
                    {"type": "text", "text": "Identify this chord."},
                ],
            }],
        }
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
        return resp["content"][0]["text"].strip()

    def _call_ollama(self, img_bytes: bytes) -> str:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        body = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": "Identify this chord.",
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 32},
        }
        req = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.load(r)
        return resp["response"].strip()

    # --- public API --------------------------------------------------------

    def recognise(self, img) -> tuple[str, float]:
        """Identify the chord in `img` (path string or PIL Image).

        Returns (chord_string, confidence). For VLMs, confidence is
        coarse — 0.95 for a clean chord match, 0.0 for SKIP / UNSURE /
        unparseable output. The pipeline's downstream threshold of
        0.55 accepts the former and rejects the latter.
        """
        if isinstance(img, str):
            with open(img, "rb") as f:
                img_bytes = f.read()
        else:
            import io
            buf = io.BytesIO()
            img.save(buf, "PNG")
            img_bytes = buf.getvalue()

        h = self._hash(img_bytes)
        cached = self._load_cached(h)
        if cached is not None:
            return cached

        # Retry on transient backend errors (ollama 500s when the model
        # crashes/restarts, Anthropic 529 overload, dropped connections).
        # Five attempts with exponential backoff covers most blips.
        answer = None
        backoff = 1.0
        for attempt in range(5):
            try:
                if self.backend == "anthropic":
                    answer = self._call_anthropic(img_bytes)
                else:
                    answer = self._call_ollama(img_bytes)
                break
            except urllib.error.HTTPError as e:
                # 5xx and 429 are retryable; 4xx (except 429) usually aren't
                if e.code >= 500 or e.code == 429:
                    print(f"  [vlm] HTTP {e.code} on attempt {attempt+1}/5, "
                          f"backing off {backoff:.1f}s", file=sys.stderr)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                print(f"  [vlm] HTTP {e.code}: {e.reason}", file=sys.stderr)
                return "", 0.0
            except urllib.error.URLError as e:
                print(f"  [vlm] connection error attempt {attempt+1}/5: {e}, "
                      f"backing off {backoff:.1f}s", file=sys.stderr)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            except Exception as e:
                print(f"  [vlm] unexpected error: {e}", file=sys.stderr)
                return "", 0.0
        if answer is None:
            # All retries exhausted — don't cache this failure permanently,
            # but return empty so the pipeline keeps going.
            return "", 0.0

        # Some models wrap output in quotes / add trailing punctuation
        answer = answer.strip().strip('"\'').rstrip(".,;:").strip()

        if answer in ("SKIP", "UNSURE", ""):
            self._save_cached(h, "", 0.0)
            return "", 0.0

        # Sanity-check the response looks like a chord
        if not CHORD_REGEX.match(answer):
            # Try unicode-accidental → ascii fixup
            cleaned = answer.replace("♯", "#").replace("♭", "b").replace("°", "dim")
            if CHORD_REGEX.match(cleaned):
                answer = cleaned
            else:
                self._save_cached(h, "", 0.0)
                return "", 0.0

        self._save_cached(h, answer, 0.95)
        return answer, 0.95


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    clf = VLMClassifier()
    print(f"# backend={clf.backend} model={clf.model}", file=sys.stderr)
    for p in sys.argv[1:]:
        chord, conf = clf.recognise(p)
        print(f"{p}: {chord!r} (conf {conf:.2f})")


if __name__ == "__main__":
    main()
