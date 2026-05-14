#!/usr/bin/env python3
"""OCR chord symbols directly above each vocal staff.

Audiveris sometimes fails to even detect a chord-name glyph (as opposed
to detecting it but mis-reading the value). For those cases we do a
fresh OCR pass over the strip of pixels directly above each vocal
staff, where chord symbols sit in piano-vocal arrangements.

Pipeline per sheet:
  1. Extract BINARY.png from the .omr zip (Audiveris's own rendered image).
  2. Parse the .omr XML for staff y-coordinates and staff-barline x-ranges.
  3. Identify vocal staves (staves that own lyric <chord-syllable> relations).
  4. For each vocal staff:
       - Crop a strip from ~55 px above the top staff line to ~5 px above.
       - Run tesseract with a chord-friendly whitelist.
       - Find chord-like tokens (match /^[A-G][#b♯♭]?[a-zA-Z0-9+/-]*$/).
       - Convert token x-positions to (measure_number, offset_fraction)
         using the existing staff-barline table.
  5. Return the recovered chords — to be merged with Audiveris's parsed
     chord-names before insertion into the reduced MusicXML.

Usage: chord_row_ocr.py <path-to-.omr>

Integration: main pipeline imports `recover_chord_row_chords()`.
"""
from __future__ import annotations
import os
import re
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass


CHORD_REGEX = re.compile(r"^[A-G][#b♯♭]?(?:maj|min|aug|dim|sus|m|M|b|#|\+|\-|[0-9/\+])*$")
# Tight whitelist of characters that appear in chord symbols
CHORD_CHARS = "ABCDEFGabdefgimsu#b+-0123456789"


@dataclass
class RowChord:
    sheet: int
    staff: int
    x: float
    y: float
    value: str
    measure: int | None = None
    measure_frac: float | None = None


def _identify_vocal_staves(root: ET.Element) -> set[int]:
    """Staves that have lyric words attached. Matches the same heuristic
    used by head_recovery."""
    staves: set[int] = set()
    for w in root.iter("word"):
        s = w.get("staff")
        if s is not None:
            staves.add(int(s))
    return staves


def _staff_top_lines(root: ET.Element) -> dict[int, float]:
    """Top staff-line y-coordinate for each staff. The .omr XML has
    <staff><lines><line><point y=.../>.. </line>..</lines></staff>
    where the first <line> is the top staff line."""
    out: dict[int, float] = {}
    for st in root.iter("staff"):
        s_id = st.get("id")
        if s_id is None:
            continue
        lines = st.find("lines")
        if lines is None:
            continue
        first_line = lines.find("line")
        if first_line is None:
            continue
        pts = list(first_line.iter("point"))
        if not pts:
            continue
        # Average the top-line y across points so we don't bias to one end
        ys = [float(p.get("y")) for p in pts if p.get("y") is not None]
        if ys:
            out[int(s_id)] = sum(ys) / len(ys)
    return out


def _measure_xranges(root: ET.Element) -> dict[int, list[tuple[float, int]]]:
    """Per-staff list of (right_barline_x, measure_id) sorted by x.
    Mirrors chord_diff's logic."""
    sb_x: dict[str, tuple[float, int]] = {}
    for sb in root.iter("staff-barline"):
        sbid = sb.get("id")
        sf = sb.get("staff")
        bounds = sb.find("bounds")
        if sbid is None or sf is None or bounds is None:
            continue
        sb_x[sbid] = (float(bounds.get("x")), int(sf))
    per_staff: dict[int, list[tuple[float, int]]] = {}
    for m in root.iter("measure"):
        mid_str = m.get("id") or ""
        mm = re.match(r"(\d+)", mid_str)
        if not mm:
            continue
        mid = int(mm.group(1))
        rb = m.find("right-barline")
        if rb is None:
            continue
        sb_list = rb.find("staff-barlines")
        if sb_list is None or sb_list.text is None:
            continue
        for bid in sb_list.text.split():
            if bid in sb_x:
                x, staff = sb_x[bid]
                per_staff.setdefault(staff, []).append((x, mid))
    for lst in per_staff.values():
        lst.sort()
    return per_staff


def _measure_for(
    per_staff: dict[int, list[tuple[float, int]]],
    staff: int,
    x: float,
) -> tuple[int | None, float | None]:
    lst = per_staff.get(staff)
    if not lst:
        return None, None
    prev_bx = 0.0
    for bx, mid in lst:
        if x <= bx:
            width = bx - prev_bx
            frac = (x - prev_bx) / width if width > 0 else 0.0
            return mid, max(0.0, min(0.99, frac))
        prev_bx = bx
    return lst[-1][1], 0.99


def _ocr_run(img_path: str, psm: int, x_offset: int = 0) -> list[tuple[int, str]]:
    """Run tesseract in TSV mode. Returns [(x_center, token)]."""
    proc = subprocess.run(
        ["tesseract", img_path, "-",
         "--psm", str(psm),
         "-c", f"tessedit_char_whitelist={CHORD_CHARS}",
         "tsv"],
        capture_output=True, text=True, check=False,
    )
    out: list[tuple[int, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            left = int(parts[6])
            width = int(parts[8])
            conf = float(parts[10])
            text = parts[11].strip()
        except ValueError:
            continue
        if not text or not CHORD_REGEX.match(text):
            continue
        if conf < 25:
            continue
        # Single-letter tokens (A, D, F, etc.) are kept here so the classifier
        # can try to upgrade them to multi-char chords (A → A7, D → Dm7, …).
        # If the classifier doesn't upgrade them, they get rejected at the
        # end of _ocr_chord_row.
        out.append((x_offset + left + width // 2, text))
    return out


def _ocr_chord_row(png_path: str, top: int, bottom: int, img_width: int) -> list[tuple[int, str]]:
    """OCR a horizontal strip multiple ways and merge. Chord rows are
    often crowded — a single PSM fails to segment. We combine:
      - PSM 6 (uniform block) over the full strip
      - PSM 11 (sparse text) over the full strip
      - A sliding window with PSM 8 (single word) across the strip,
        catching crowded tokens that the whole-strip pass missed.
    Then dedupe by x-proximity.
    """
    if bottom <= top:
        return []
    strip_h = bottom - top
    with tempfile.TemporaryDirectory() as td:
        strip_path = os.path.join(td, "strip.png")
        subprocess.run(
            ["magick", png_path, "-crop", f"x{strip_h}+0+{top}", "+repage", strip_path],
            capture_output=True, check=False,
        )
        if not os.path.exists(strip_path):
            return []
        results: list[tuple[int, str]] = []
        # Whole-strip passes
        for psm in (6, 11):
            results.extend(_ocr_run(strip_path, psm))
        # Sliding window: 140 px wide, step 60 px, PSM 8
        win_w = 140
        step = 60
        x = 0
        while x < img_width:
            end = min(x + win_w, img_width)
            w = end - x
            win_path = os.path.join(td, f"win_{x}.png")
            subprocess.run(
                ["magick", png_path, "-crop", f"{w}x{strip_h}+{x}+{top}", "+repage", win_path],
                capture_output=True, check=False,
            )
            if os.path.exists(win_path):
                results.extend(_ocr_run(win_path, 8, x_offset=x))
            x += step
        # Dedupe by proximity — within 25px, keep the longer/more-specific token
        results.sort()
        deduped: list[tuple[int, str]] = []
        for xc, tok in results:
            if deduped and xc - deduped[-1][0] < 25:
                # Prefer longer chord figures (A7 > A, D7 > D, Cmaj7 > Cmaj)
                if len(tok) > len(deduped[-1][1]):
                    deduped[-1] = (xc, tok)
                continue
            deduped.append((xc, tok))

        # Optional: re-classify each token with a chord recogniser.
        # Two backends supported, in priority order:
        #   1. VLM (ollama or Anthropic Claude vision) — best accuracy,
        #      handles novel chords like C#+ and stacked extensions out
        #      of the box. Opt-in via CHORD_VLM=1.
        #   2. Trained CNN — local, fast, but limited to learned classes.
        # Tesseract is good at *localising* chords; the recogniser is
        # better at *reading* them.
        use_vlm = os.environ.get("CHORD_VLM") == "1"
        classifier_path = os.environ.get("CHORD_CLASSIFIER_PATH")
        clf = None
        # VLM can run the sweep on empty strips (zero false-positive
        # rate); CNN requires tesseract-found tokens to seed it.
        clf_can_run = use_vlm or bool(deduped)
        if use_vlm and clf_can_run:
            try:
                from omr_leadsheet.recognisers.vlm import VLMClassifier
                clf = VLMClassifier()
            except Exception as e:
                print(f"  (VLM disabled: {e})", file=sys.stderr)
        if clf is None and classifier_path and os.path.exists(classifier_path) and deduped:
            try:
                from omr_leadsheet.recognisers.cnn import ChordClassifier
                clf = ChordClassifier(classifier_path)
            except Exception as e:
                print(f"  (CNN disabled: {e})", file=sys.stderr)

        if clf is not None and clf_can_run:
            try:
                refined: list[tuple[int, str]] = []
                for xc, tok in deduped:
                    # Crop a window around the token's x-center
                    half = 40
                    x0 = max(0, xc - half)
                    w = min(img_width - x0, half * 2)
                    crop_path = os.path.join(td, f"clf_{xc}.png")
                    subprocess.run(
                        ["magick", png_path, "-crop",
                         f"{w}x{strip_h}+{x0}+{top}", "+repage", crop_path],
                        capture_output=True, check=False,
                    )
                    if not os.path.exists(crop_path):
                        refined.append((xc, tok))
                        continue
                    chord_str, conf = clf.recognise(crop_path)
                    # Confidence gate. Short predictions (bare letters like
                    # "A" or "D") are visually ambiguous with stray ink and
                    # need higher confidence to be trusted. Long ones can be
                    # accepted with lower confidence because their visual
                    # signature is more distinctive.
                    threshold = 0.8 if len(chord_str) <= 2 else 0.6
                    if conf >= threshold:
                        refined.append((xc, chord_str))
                    else:
                        refined.append((xc, tok))
                # Classifier-direct sweep: find chord glyphs tesseract
                # missed entirely. Slide a 60-px window across the strip
                # at 30-px steps; keep predictions that (a) match the
                # chord regex, (b) clear a high confidence floor, and
                # (c) don't sit within 35 px of an existing dedup'd token.
                covered_x = sorted(xc for xc, _ in refined)
                def _near_existing(x: int) -> bool:
                    for ex in covered_x:
                        if abs(ex - x) < 35:
                            return True
                    return False
                # Empty-strip sweep: slide a window across the chord-row
                # strip looking for glyphs Audiveris missed entirely
                # (e.g. m5 F#9/7 in song 13). Auto-enabled when the
                # recogniser is a VLM (false-positive rate is near-zero
                # because VLMs return SKIP on empty crops). For the CNN,
                # it remains opt-in (CHORD_SWEEP_ENABLE=1) because the
                # CNN produces confident wrong guesses on empty strips.
                sweep_enabled = (
                    os.environ.get("CHORD_SWEEP_ENABLE") == "1"
                    or os.environ.get("CHORD_VLM") == "1"
                )
                if not sweep_enabled:
                    refined.sort()
                    return refined
                sweep_w, sweep_step = 60, 30
                sx = 0
                # Need PIL to check ink density before invoking the classifier
                # — empty chord-row slices classify as Fmaj7 / Dm7 at ~0.6+
                # confidence and produce false positives across the board.
                try:
                    from PIL import Image as _PILImage
                except Exception:
                    _PILImage = None
                while sx < img_width:
                    end = min(sx + sweep_w, img_width)
                    w = end - sx
                    xc = sx + w // 2
                    if _near_existing(xc):
                        sx += sweep_step
                        continue
                    sweep_path = os.path.join(td, f"sweep_{sx}.png")
                    subprocess.run(
                        ["magick", png_path, "-crop",
                         f"{w}x{strip_h}+{sx}+{top}", "+repage", sweep_path],
                        capture_output=True, check=False,
                    )
                    if os.path.exists(sweep_path):
                        # Ink-density gate: chord glyphs are ~5-12% dark
                        # pixels in a tight bounding box. A near-empty
                        # crop should never reach the classifier.
                        ink_ok = True
                        if _PILImage is not None:
                            try:
                                im = _PILImage.open(sweep_path).convert("L")
                                px = list(im.getdata())
                                dark = sum(1 for p in px if p < 128)
                                frac = dark / max(1, len(px))
                                # Skip near-empty (< 1.5%) or near-full
                                # (> 30%, e.g. inside a chord stem) crops
                                ink_ok = 0.015 <= frac <= 0.30
                            except Exception:
                                pass
                        if ink_ok:
                            cs, cf = clf.recognise(sweep_path)
                            if cs and CHORD_REGEX.match(cs):
                                # Stricter floors: empty-ish strips still
                                # sometimes clear 0.7, so push higher.
                                floor = 0.90 if len(cs) <= 2 else 0.82
                                if cf >= floor:
                                    refined.append((xc, cs))
                                    covered_x.append(xc)
                                    covered_x.sort()
                    sx += sweep_step
                refined.sort()
                return refined
            except Exception as e:
                # Don't let the classifier break the pipeline; fall back to tesseract
                print(f"  (classifier disabled: {e})", file=__import__("sys").stderr)
        return deduped


def _recover_misclassified_articulations(
    root: ET.Element, bin_png: str, sheet_idx: int,
    vocal: set[int], tops: dict[int, float], per_staff,
    img_width: int,
) -> list[RowChord]:
    """Find MARCATO/ACCENT articulations sitting in chord-row territory and
    re-classify them as chord glyphs via the trained CNN.

    Audiveris occasionally classifies a jazz-font capital A above a note as
    a MARCATO articulation on the note itself, instead of as a chord-name
    glyph in the chord row above the staff. The visual signature is the
    same wedge shape. We pick up those misclassifications by:

      1. Walking <articulation shape="MARCATO|ACCENT"> elements.
      2. Finding the nearest VOCAL staff.
      3. If the articulation sits >20 px ABOVE that staff's top line,
         it's in chord-row territory — not a real note articulation.
      4. Crop a generous window around the glyph (wider on the right to
         catch trailing digits like "7" / "9").
      5. Run the chord classifier on the crop. If confidence >= 0.55
         AND the prediction looks like a chord, emit a RowChord.

    If the classifier isn't available (no CHORD_CLASSIFIER_PATH), the
    raw articulation is emitted as 'A' with low priority — caller can
    decide whether to trust it.
    """
    # Recogniser priority: VLM (if CHORD_VLM=1) > local CNN
    use_vlm = os.environ.get("CHORD_VLM") == "1"
    classifier_path = os.environ.get("CHORD_CLASSIFIER_PATH")
    clf = None
    if use_vlm:
        try:
            from omr_leadsheet.recognisers.vlm import VLMClassifier
            clf = VLMClassifier()
        except Exception as e:
            print(f"  (VLM disabled in art-recovery: {e})", file=sys.stderr)
    if clf is None and classifier_path and os.path.exists(classifier_path):
        try:
            from omr_leadsheet.recognisers.cnn import ChordClassifier
            clf = ChordClassifier(classifier_path)
        except Exception:
            clf = None

    out: list[RowChord] = []
    for el in root.iter("articulation"):
        shape = el.get("shape")
        if shape not in ("MARCATO", "ACCENT"):
            continue
        b = el.find("bounds")
        if b is None:
            continue
        x = float(b.get("x"))
        y = float(b.get("y"))
        bw = float(b.get("w") or 28)
        bh = float(b.get("h") or 24)
        # Find the nearest staff below this articulation. We used to
        # restrict to vocal-tagged staves, but Audiveris's word-staff
        # mapping is unreliable for piano-vocal scores — a real chord
        # glyph can sit above a staff that has no <word> attached.
        nearest_staff = None
        nearest_distance_above = -1.0
        for s, top in tops.items():
            d_above = top - y  # positive = articulation is above the staff
            if d_above < 0:
                continue
            if nearest_staff is None or d_above < nearest_distance_above:
                nearest_staff = s
                nearest_distance_above = d_above
        # Require the glyph to be 20–120 px above the staff top — that's the
        # chord-row region in this source's 200 DPI layout. Below 20 means
        # it's likely a real articulation on a high note; above 120 means
        # it's probably attached to the previous system.
        if nearest_staff is None or not (20 <= nearest_distance_above <= 120):
            continue
        if clf is None:
            continue
        # Diagnostic showed wide 80x80 crops dilute the signal. Sweep a few
        # tight windows centered on the glyph bounds and take the best.
        # The chord may extend rightward (e.g. "A7"), so try wider-right too.
        cx, cy = x + bw / 2.0, y + bh / 2.0
        candidates = [
            (40, 40, cx - 20, cy - 20),
            (50, 45, cx - 20, cy - 22),
            (70, 50, cx - 20, cy - 25),  # catch trailing "7"
            (90, 55, cx - 25, cy - 27),
        ]
        best_chord, best_conf = "", 0.0
        with tempfile.TemporaryDirectory() as cdir:
            import subprocess
            for i, (cw, ch, x0f, y0f) in enumerate(candidates):
                x0, y0 = max(0, int(x0f)), max(0, int(y0f))
                crop_path = os.path.join(cdir, f"art_{sheet_idx}_{int(x)}_{int(y)}_{i}.png")
                subprocess.run(
                    ["magick", bin_png, "-crop",
                     f"{int(cw)}x{int(ch)}+{x0}+{y0}", "+repage", crop_path],
                    capture_output=True, check=False,
                )
                if not os.path.exists(crop_path):
                    continue
                cs, cf = clf.recognise(crop_path)
                if cs and CHORD_REGEX.match(cs) and cf > best_conf:
                    best_chord, best_conf = cs, cf
        chord_str, conf = best_chord, best_conf
        if not chord_str or conf < 0.55:
            continue
        # The classifier output must at least look like a chord
        if not CHORD_REGEX.match(chord_str):
            continue
        mid, frac = _measure_for(per_staff, nearest_staff, x)
        if mid is None:
            continue
        out.append(RowChord(
            sheet=sheet_idx, staff=nearest_staff,
            x=x, y=y, value=chord_str, measure=mid, measure_frac=frac,
        ))
    return out


def recover_chord_row_chords(omr_path: str) -> list[RowChord]:
    out: list[RowChord] = []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(omr_path) as z:
            z.extractall(td)
        sheet_dirs = sorted(
            d for d in os.listdir(td)
            if os.path.isdir(os.path.join(td, d)) and d.startswith("sheet#")
        )
        for sd in sheet_dirs:
            sheet_idx = int(sd.split("#")[1])
            xml_path = os.path.join(td, sd, f"{sd}.xml")
            bin_png = os.path.join(td, sd, "BINARY.png")
            if not (os.path.exists(xml_path) and os.path.exists(bin_png)):
                continue
            root = ET.parse(xml_path).getroot()
            vocal = _identify_vocal_staves(root)
            tops = _staff_top_lines(root)
            per_staff = _measure_xranges(root)

            # Get image width for sliding window
            from subprocess import run as _run
            img_width = 2500
            try:
                ident = _run(["magick", "identify", "-format", "%w", bin_png],
                             capture_output=True, text=True, check=False)
                img_width = int(ident.stdout.strip())
            except Exception:
                pass

            # Sweep the chord row above vocal staves. We tried iterating
            # all staves with barlines, but that produced too many
            # partial-glyph false reads (the sweep window doesn't know
            # exact glyph bounds and crops mid-character). The MARCATO
            # recovery path handles chord glyphs above non-vocal staves
            # via Audiveris's own bounding boxes — that's the precise
            # path for those.
            for staff_id in sorted(vocal):
                top_y = tops.get(staff_id)
                if top_y is None:
                    continue
                strip_top = max(0, int(top_y - 70))
                strip_bottom = int(top_y - 10)
                row_tokens = _ocr_chord_row(bin_png, strip_top, strip_bottom, img_width)
                for x_center, tok in row_tokens:
                    mid, frac = _measure_for(per_staff, staff_id, x_center)
                    out.append(RowChord(
                        sheet=sheet_idx, staff=staff_id,
                        x=float(x_center), y=float(top_y - 30),
                        value=tok, measure=mid, measure_frac=frac,
                    ))

            # Additional pass: recover chord letters Audiveris classified as
            # marcato/accent articulations.
            out.extend(_recover_misclassified_articulations(
                root, bin_png, sheet_idx, vocal, tops, per_staff, img_width
            ))

            # Stage-2 pass: blob-based chord-row scan over EVERY staff
            # with barlines. Catches chord glyphs Audiveris dropped
            # entirely (no <chord-name>, no <articulation>) — these
            # never reach the tesseract sweep or the MARCATO recovery.
            # Only runs when a VLM is enabled because the blob-based
            # crops can be ambiguous, and VLMs degrade to SKIP cleanly
            # where the CNN forces a wrong class.
            if os.environ.get("CHORD_VLM") == "1":
                try:
                    from omr_leadsheet.recognisers.vlm import VLMClassifier
                    from omr_leadsheet.recognisers.blobs import scan_chord_row_blobs
                    vlm = VLMClassifier()
                    # Emit every blob the VLM identifies. We don't
                    # pre-dedup against tesseract-found tokens here —
                    # the blob VLM is more accurate (it reads stacked
                    # extensions and accidentals), so its readings
                    # should override. chord_diff.insert_missing has
                    # specificity-aware dedup that promotes the longer
                    # chord (G9/7 over G7) at insertion time.
                    for staff_id, top_y in tops.items():
                        if top_y is None or staff_id not in per_staff:
                            continue
                        # Wider strip than the tesseract path: stacked
                        # extensions (9 over 7) have the numerator
                        # sitting ~80-100 px above the staff, beyond
                        # the 70 px window the tesseract pass uses.
                        strip_top = max(0, int(top_y - 110))
                        strip_bottom = int(top_y - 10)
                        blobs = scan_chord_row_blobs(
                            bin_png, strip_top, strip_bottom, vlm
                        )
                        for xc, chord, conf in blobs:
                            mid, frac = _measure_for(per_staff, staff_id, xc)
                            if mid is None:
                                continue
                            out.append(RowChord(
                                sheet=sheet_idx, staff=staff_id,
                                x=float(xc), y=float(top_y - 30),
                                value=chord, measure=mid, measure_frac=frac,
                            ))
                except Exception as e:
                    print(f"  (blob-scan disabled: {e})", file=sys.stderr)
    return out


def main() -> None:
    chords = recover_chord_row_chords(sys.argv[1])
    print(f"OCR'd {len(chords)} chord-like tokens from chord rows:")
    for c in chords:
        print(f"  sheet {c.sheet} staff {c.staff} m{c.measure} frac={c.measure_frac:.2f} value={c.value!r}")


if __name__ == "__main__":
    main()
