#!/usr/bin/env python3
"""Replace garbled Audiveris lyrics with clean tesseract text via NW alignment.

Architecture:
  * Tesseract text is ground truth (clean words, correct order, hyphens split
    syllables). Imperfect but way cleaner than Audiveris.
  * Audiveris lyrics: one syllable per note, divided into verses (1, 2, ...).
    Verse 1 is the primary lyric; verse 2 is the stacked second stanza in
    refrain measures.

Algorithm (per verse):
  1. Build the Audiveris token stream in note order (A_1, A_2, ... A_n).
  2. Build the tesseract token stream for that verse (T_1, T_2, ... T_m).
     For verse 1, include all tesseract tokens. For verse 2, use only the
     tokens that appear in stacked-verse sections (detected by verse 2
     having matching notes) - we pass the whole stream but NW alignment
     penalises unrelated prefix/suffix automatically.
  3. Needleman-Wunsch global alignment with:
        substitution cost = 1 - similarity(a, b) (0..1)
        gap cost = 0.6
     Similarity is SequenceMatcher ratio on lowercased strings.
  4. Walk the alignment. For each Audiveris token aligned to a tesseract
     token, apply the replacement rule:
        - If Audiveris token IS a real dictionary word (>= 3 chars), keep it.
        - Otherwise, replace with the aligned tesseract token.
     Gaps and low-similarity matches are left alone.

Dictionary gating prevents "is" → "this" kinds of bad swaps.

Usage: spell_check_lyrics.py <in.musicxml> <tesseract.txt> <out.musicxml>
"""
from __future__ import annotations
import re
import sys
from difflib import SequenceMatcher
from music21 import converter, note


# Tokenizer accepts both straight (0x27) and curly (U+2019) apostrophes.
# Tesseract OCR of typeset jazz fonts often emits the curly variant for
# contractions ("I'll", "don't"); without the curly here _line_to_tokens
# truncates at the apostrophe and downstream NW alignment loses the rest
# of the contraction (#68: v2 lost "'ll" from "I'll").
WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")


# Load system dict
with open("/usr/share/dict/words") as f:
    DICT = {w.strip().lower() for w in f if w.strip()}
# Gershwin-specific jazz syllables that aren't English words.
# Kept as a SEPARATE set (not unioned into MODERN_ENGLISH) so the
# lyric-prefer rule in apply_alignment can distinguish "jah" (a
# legitimate jazz syllable) from "knows" (just a modern dict word).
GERSHWIN_SYLLABLES = {
    "pa", "ja", "jah", "po", "tah", "ma", "mah", "to", "oh", "im",
    "ee", "ny", "eye", "nee", "ther", "lawf", "awf", "nil", "nel",
    "sas", "rel", "ril", "mance", "romance", "ness", "ing",
    "ers", "erst", "oyst", "sters", "oysters", "ersters",
    "af", "ty", "dont", "nah",
}
# Common modern English inflections that web2 (1913) doesn't have
MODERN_ENGLISH = {
    "knows", "goes", "does", "says", "shows", "grows", "flows", "throws",
    "feels", "thinks", "cares", "wears", "wants", "calls", "tells", "gives",
    "takes", "makes", "looks", "comes", "plays", "stays", "sings", "loves",
    "hears", "sees", "means", "meets", "finds", "needs", "keeps", "turns",
    "puts", "gets", "lets", "sits", "runs", "fits", "hits", "reads",
    "ers", "oysters", "without",
    "i'll", "i'm", "i've", "i'd", "we'll", "we're", "we've", "we'd",
    "you'll", "you're", "you've", "you'd", "he'll", "he's", "he'd",
    "she'll", "she's", "she'd", "they'll", "they're", "they've", "they'd",
    "it'll", "it's", "it'd", "that'll", "that's", "what's", "let's",
    "don't", "won't", "can't", "isn't", "wasn't", "aren't", "weren't",
    "didn't", "doesn't", "haven't", "hasn't", "hadn't", "shouldn't",
    "wouldn't", "couldn't",
}
# Backwards-compatible alias for downstream callers that imported the
# old name. Both sets contribute to the dict.
LYRIC_SYLLABLES = GERSHWIN_SYLLABLES | MODERN_ENGLISH
DICT |= LYRIC_SYLLABLES


SINGLE_CHAR_WORDS = {"a", "i", "o"}  # legitimate single-char English words


def _has_canonical_case(raw: str) -> bool:
    """True if ``raw`` is all-lower, all-upper, or first-upper-rest-lower.

    Filters out OCR-noise tokens like ``thIng`` (I/l/1 confusion in the
    middle of a word) that still appear as a dictionary word when
    lowercased. False-positive surface: legitimate inner-capital tokens
    like ``McDonald`` -- rare in song lyrics and outside the scope of
    this OCR-cleanup heuristic.
    """
    letters = [c for c in raw if c.isalpha()]
    if not letters:
        return True
    if all(c.islower() for c in letters):
        return True
    if all(c.isupper() for c in letters):
        return True
    if letters[0].isupper() and all(c.islower() for c in letters[1:]):
        return True
    return False


def is_real_word(tok: str) -> bool:
    """True if the token looks like a real word that we should trust.

    Audi tokens that pass this gate are kept as-is during NW-alignment
    pass-1, even if a more plausible truth-token aligns to them. So
    being permissive here means OCR garbage stays. Being too strict
    means good Audiveris reads get clobbered by noisy tesseract truth.

    Length-based rule of thumb:

    - 1-char tokens: only ``a``, ``i``, ``o`` are real English words.
      Tesseract systematically truncates short syllables to single
      letters (the→t, oh→o (which is fine), it→i, etc.), so trusting
      every 1-char token causes the OCR-truncation class of bugs
      (issue #11). Whitelist instead.
    - 2-char tokens: lots of real two-letter words (to, of, go, on,
      in, my, we, he, ...). Even when an OCR truncation is in this
      range (oth→th), trusting them gives better outcomes on average
      than rejecting them.
    - 3+ chars: defer to the dictionary, but ALSO require canonical
      capitalization. ``thIng`` lowercases to ``thing`` which is in
      the dict, but the internal capital I betrays an OCR confusion
      (I/l/1 in serif jazz fonts). Without this guard, pass-1 keeps
      ``thIng`` verbatim instead of letting NW replace it with the
      tesseract-OCR'd ``thing`` -- visible on LCWTO m25 v1.
    """
    # Normalise curly apostrophe to straight so dict lookups succeed
    # for OCR'd contractions like "I'll" (U+2019).
    raw = tok.replace("’", "'").strip(".,;:!?\"''()[]-_")
    t = raw.lower()
    if len(t) == 0:
        return False
    if len(t) == 1:
        return t in SINGLE_CHAR_WORDS
    if len(t) == 2:
        return True  # mostly legitimate; see docstring
    if t in DICT and _has_canonical_case(raw):
        return True
    return False


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def nw_align(audi: list[str], truth: list[str], gap: float = 0.6) -> list[tuple[int | None, int | None]]:
    """Classic Needleman-Wunsch using cost (lower is better).
    Substitution cost = 1 - similarity. Gap cost = `gap`.
    Returns list of (audi_index, truth_index); None on either side means gap.
    """
    n, m = len(audi), len(truth)
    # cost matrix
    C = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        C[i][0] = C[i - 1][0] + gap
    for j in range(1, m + 1):
        C[0][j] = C[0][j - 1] + gap
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = C[i - 1][j - 1] + (1 - sim(audi[i - 1], truth[j - 1]))
            del_ = C[i - 1][j] + gap
            ins_ = C[i][j - 1] + gap
            C[i][j] = min(sub, del_, ins_)
    # traceback
    i, j = n, m
    out: list[tuple[int | None, int | None]] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and C[i][j] == C[i - 1][j - 1] + (1 - sim(audi[i - 1], truth[j - 1])):
            out.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and C[i][j] == C[i - 1][j] + gap:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    out.reverse()
    return out


def _line_to_tokens(line: str) -> list[str]:
    # Normalise curly apostrophe (U+2019) to straight before tokenising so
    # downstream comparisons and dict lookups all see the same form (#68).
    line = line.replace("’", "'").replace(" - ", " ").replace("_", " ")
    out: list[str] = []
    for piece in re.split(r"[-\s]+", line):
        m = WORD.match(piece)
        if m:
            out.append(m.group(0))
    return out


def _is_lyric_line(s: str) -> bool:
    """Reject lines that are clearly not lyrics (titles, credits)."""
    if not s.strip():
        return False
    low = s.lower()
    if low.startswith(("copyright ", "lyrics by", "music by")):
        return False
    if re.fullmatch(r"[A-Z'\s]+", s):
        return False
    return True


def tesseract_verse_streams(path: str) -> tuple[list[str], list[str]]:
    """Return (v1_tokens, v2_tokens).

    Heuristic: consecutive lyric lines pair as verse 1 / verse 2 of
    the same passage if they share most of their FIRST FEW tokens.
    Verses of the same passage start with the same melody phrase --
    "So if you ..." in both verse 1 and verse 2 of a refrain row --
    but diverge later (``pa-ja-mas`` vs ``oyst-ers``). Anchoring the
    pair signal at the start (#55, #56) catches pairings that the
    earlier full-line-overlap rule missed; lines whose openings
    differ are still treated as unpaired and go to both verses.

    Also requires the two lines to be reasonably similar in length
    (no more than 2x apart in token count) so that a long verse-2
    line isn't paired with a short fragment that just happens to
    share a few opening tokens.
    """
    with open(path) as f:
        raw = [l.rstrip() for l in f if _is_lyric_line(l.rstrip())]

    def first_letters(line: str, k: int = 2) -> list[str]:
        return [t[:k].lower() for t in _line_to_tokens(line) if len(t) >= k]

    def first_n_overlap(a: list[str], b: list[str], n: int = 5) -> float:
        """Fraction of the first ``n`` tokens of A and B that match
        (multiset). 0.0 if either side has fewer than n/2 tokens."""
        a_head = a[:n]
        b_head = b[:n]
        if len(a_head) < max(2, n // 2) or len(b_head) < max(2, n // 2):
            return 0.0
        sa = list(a_head)
        matches = 0
        for t in b_head:
            if t in sa:
                sa.remove(t)
                matches += 1
        return matches / max(len(a_head), len(b_head))

    def lengths_close(a: list[str], b: list[str]) -> bool:
        if not a or not b:
            return False
        return 0.5 <= len(a) / len(b) <= 2.0

    v1_tokens: list[str] = []
    v2_tokens: list[str] = []
    i = 0
    while i < len(raw):
        line_i = raw[i]
        if i + 1 < len(raw):
            sig_i = first_letters(line_i)
            sig_j = first_letters(raw[i + 1])
            if (
                first_n_overlap(sig_i, sig_j, n=5) >= 0.6
                and lengths_close(sig_i, sig_j)
            ):
                # Treat as v1/v2 pair
                v1_tokens.extend(_line_to_tokens(line_i))
                v2_tokens.extend(_line_to_tokens(raw[i + 1]))
                i += 2
                continue
        # Unpaired: belongs to both verses
        toks = _line_to_tokens(line_i)
        v1_tokens.extend(toks)
        v2_tokens.extend(toks)
        i += 1

    return v1_tokens, v2_tokens


def tesseract_tokens(path: str) -> list[str]:
    v1, _ = tesseract_verse_streams(path)
    return v1


def audiveris_tokens(score) -> tuple[int, list, dict[int, list]]:
    """Return (part_index, all_notes_in_order, {verse_num: [(note_index_in_all, note, lyric), ...]})."""
    # vocal part = part with most lyrics
    best_idx, best = 0, -1
    for i, p in enumerate(score.parts):
        c = sum(1 for n in p.recurse().notes if isinstance(n, note.Note) and n.lyrics)
        if c > best:
            best_idx, best = i, c
    vocal = score.parts[best_idx]
    all_notes: list = [n for n in vocal.recurse().notes if isinstance(n, note.Note)]
    by_verse: dict[int, list] = {}
    for idx, n in enumerate(all_notes):
        if not n.lyrics:
            continue
        for lyr in n.lyrics:
            v = lyr.number or 1
            by_verse.setdefault(v, []).append((idx, n, lyr))
    return best_idx, all_notes, by_verse


CONTRACTION_FIX = {
    "dont": "don't",
    "wont": "won't",
    "cant": "can't",
    "lll": "I'll",
    "ill": "I'll",
    "im": "I'm",
    "youre": "you're",
    "theyre": "they're",
    "isnt": "isn't",
    "wasnt": "wasn't",
    "lets": "Let's",
}


def split_merged(tok: str, min_piece: int = 2) -> str:
    """Try to split a merged-word token into dict-matchable pieces.
    Uses simple DP: find a segmentation into dict words if one exists.
    Returns the space-joined split, or the original token if no split found.
    Preserves leading/trailing punctuation and capitalization."""
    # Separate punctuation
    m = re.match(r"([^A-Za-z]*)([A-Za-z]+)([^A-Za-z]*)", tok)
    if not m:
        return tok
    lead, core, trail = m.group(1), m.group(2), m.group(3)
    low = core.lower()
    if len(low) < 6:  # only attempt for long tokens
        return tok
    # If the whole thing is a real word, don't split.
    if low in DICT:
        return tok
    n = len(low)
    # dp[i] = best split of low[:i] as list of pieces (words)
    dp: list[list[str] | None] = [None] * (n + 1)
    dp[0] = []
    for i in range(1, n + 1):
        for j in range(max(0, i - 15), i):
            if dp[j] is None:
                continue
            piece = low[j:i]
            if len(piece) < min_piece:
                continue
            if piece in DICT:
                cand = dp[j] + [piece]
                if dp[i] is None or len(cand) < len(dp[i]):
                    dp[i] = cand
    if dp[n] is None or len(dp[n]) < 2:
        return tok
    # Reassemble with the original casing of the first character
    pieces = dp[n]
    if core[0].isupper():
        pieces[0] = pieces[0].capitalize()
    return lead + " ".join(pieces) + trail


def fix_contraction(tok: str) -> str:
    m = re.match(r"([A-Za-z']+)(.*)", tok)
    if not m:
        return tok
    core, rest = m.group(1), m.group(2)
    low = core.lower()
    if low in CONTRACTION_FIX:
        fixed = CONTRACTION_FIX[low]
        # Preserve capitalisation of the original
        if core[0].isupper() and fixed[0].islower():
            fixed = fixed[0].upper() + fixed[1:]
        return fixed + rest
    return tok


def polish(tok: str) -> str:
    """Apply word-splitting + contraction repair to one token."""
    # First try to fix a known contraction
    fixed = fix_contraction(tok)
    # Then try to split merged runs
    fixed = split_merged(fixed)
    # Retry contraction fix on any produced pieces
    parts = fixed.split()
    parts = [fix_contraction(p) for p in parts]
    return " ".join(parts)


def apply_alignment(audi_pairs: list, truth: list[str], all_notes: list, verse_num: int) -> dict:
    """audi_pairs: [(note_index_in_all, note, lyric)]; truth: tesseract tokens."""
    tokens = [(lp[2].text or "") for lp in audi_pairs]
    alignment = nw_align(tokens, truth)
    stats = {
        "replaced": 0,
        "kept_dict": 0,
        "kept_other": 0,
        "audi_gaps": 0,
        "truth_gaps": 0,
        "split": 0,
        "contracted": 0,
        "inserted": 0,
    }
    # Pass 1: replace/repair in place on the Audiveris side
    for ai, ti in alignment:
        if ai is None or ti is None:
            if ai is None:
                stats["truth_gaps"] += 1
            else:
                # Audi-gap: just polish the token (no truth alignment)
                lyr = audi_pairs[ai][2]
                original = lyr.text or ""
                polished = polish(original)
                if polished != original:
                    lyr.text = polished
                    stats["split" if " " in polished else "contracted"] += 1
                stats["audi_gaps"] += 1
            continue
        lyr = audi_pairs[ai][2]
        audi_tok = lyr.text or ""
        truth_tok = truth[ti]
        if is_real_word(audi_tok):
            # #70: when the truth token is a Gershwin-specific lyric
            # syllable (e.g. "jah" from "pa-jah-mas") and the audi
            # token is a generic English word that isn't a Gershwin
            # syllable (e.g. "jab" -- a real word, but the wrong one
            # for this context), prefer the lyric form. Bounded by:
            # - sim >= 0.6 (one-character mismatches only)
            # - length 2-5 (typical jazz syllable length)
            # - audi NOT itself a Gershwin syllable (so we don't
            #   thrash legitimate "ee" / "pa" / etc.)
            audi_lo = audi_tok.lower().strip(",.;:!?\"'’()[]-_")
            truth_lo = truth_tok.lower().strip(",.;:!?\"'’()[]-_")
            if (
                truth_lo in GERSHWIN_SYLLABLES
                and audi_lo not in GERSHWIN_SYLLABLES
                and 2 <= len(audi_lo) <= 5
                and sim(audi_tok, truth_tok) >= 0.6
            ):
                polished = polish(truth_tok)
                lyr.text = polished
                stats["replaced"] += 1
                continue
            stats["kept_dict"] += 1
            continue
        candidate = truth_tok
        if sim(audi_tok, truth_tok) < 0.3 and not is_real_word(truth_tok):
            candidate = audi_tok
        polished = polish(candidate)
        if polished != audi_tok:
            lyr.text = polished
            if polished != candidate:
                stats["split" if " " in polished else "contracted"] += 1
            else:
                stats["replaced"] += 1
        else:
            stats["kept_other"] += 1

    # Pass 2: for each "truth_gap" (tesseract token that aligned to nothing),
    # try to insert it on a naked note that falls between the two surrounding
    # matched Audiveris notes.
    def neighboring_audi_positions(align_idx: int) -> tuple[int | None, int | None]:
        """Return (prev_note_idx, next_note_idx) bracketing this truth gap."""
        prev_ai = None
        for k in range(align_idx - 1, -1, -1):
            a, t = alignment[k]
            if a is not None and t is not None:
                prev_ai = a
                break
        next_ai = None
        for k in range(align_idx + 1, len(alignment)):
            a, t = alignment[k]
            if a is not None and t is not None:
                next_ai = a
                break
        prev_note = audi_pairs[prev_ai][0] if prev_ai is not None else -1
        next_note = audi_pairs[next_ai][0] if next_ai is not None else len(all_notes)
        return prev_note, next_note

    # Determine the range of note-indices where THIS verse actually appears,
    # so we don't invent v2 lyrics in the verse section (where v2 doesn't sing).
    verse_note_indices = [lp[0] for lp in audi_pairs]
    if verse_note_indices:
        verse_range = (min(verse_note_indices), max(verse_note_indices))
    else:
        verse_range = (0, len(all_notes) - 1)

    # Pickup/anacrusis tolerance: allow truth tokens whose alignment falls
    # just outside the audi-attached lyric range to land on the immediately-
    # adjacent pickup notes. Without this, a leading pickup syllable (e.g.
    # "If" in "If we call the whole thing off") whose note Audiveris failed
    # to attach a lyric to is permanently excluded from naked-note insertion
    # because verse_range[0] starts at the first audi-aligned note. Two
    # notes is enough to cover standard cut-time / 4-4 pickup patterns
    # without reaching into adjacent verse territory.
    PICKUP_TOLERANCE = 2

    # Maximum audi-side bracket width that pass 2 will fill (#29). A
    # truth-gap that spans more than this many notes between adjacent
    # audi-aligned positions almost always means the verse simply doesn't
    # sing through here -- this verse has a real silence in the middle.
    # Filling a 6+ note gap with truth tokens that aligned to nothing
    # invents lyrics where none belong (visible on LCWTO m33 v2: 5 chorus-
    # phrase tokens got inserted across a bracket where v2 has no sung
    # content). Capping at 4 lets pass 2 still rescue 1-4 missed lyrics
    # in a continuous lyric run while refusing to fill larger gaps.
    BRACKET_NOTE_CAP = 4

    from music21.note import Lyric
    for align_idx, (ai, ti) in enumerate(alignment):
        if ai is not None or ti is None:
            continue
        truth_tok = truth[ti]
        if not is_real_word(truth_tok):
            continue
        prev_note, next_note = neighboring_audi_positions(align_idx)
        # Clamp to the verse's actual range (plus pickup tolerance on each
        # side) to avoid inventing lyrics outside it.
        prev_note = max(prev_note, verse_range[0] - 1 - PICKUP_TOLERANCE)
        next_note = min(next_note, verse_range[1] + 1 + PICKUP_TOLERANCE)
        if prev_note + 1 >= next_note:
            continue
        # Bracket-size cap: refuse to insert into wide truth-gap brackets
        # where the verse probably doesn't sing. See BRACKET_NOTE_CAP.
        if next_note - prev_note - 1 > BRACKET_NOTE_CAP:
            continue
        naked = [
            i for i in range(prev_note + 1, next_note)
            if not any(
                (lyr.number or 1) == verse_num for lyr in all_notes[i].lyrics
            )
        ]
        if not naked:
            continue
        # Leftmost naked note (#29). Iterating the alignment in order
        # means truth tokens reach this loop in truth-stream order; the
        # leftmost-naked rule preserves that order in the output. The
        # previous "middle of naked" pick scrambled multi-token brackets
        # (visible on LCWTO m33 v2: 5 truth tokens landed in alignment
        # order 1,2,3,4,5 but on notes 137,138,136,139,135 -- read top-
        # to-bottom as E,C,A,B,D).
        target = naked[0]
        new_lyr = Lyric(text=truth_tok)
        new_lyr.number = verse_num
        all_notes[target].lyrics.append(new_lyr)
        stats["inserted"] += 1

    # Pass 3 (#73): phantom-note insertion for surviving truth-gaps.
    # When pass 2 found no naked note in the bracket but a Rest is
    # available in the previous-or-following measure, replace that
    # rest with a phantom pitched note carrying the truth syllable.
    # Pitch is copied from the previous audi-aligned note. The
    # phantom is marked with a "?" TextExpression so the user audits.
    #
    # Different bracket logic than pass 2: pass 2 needed a NAKED
    # NOTE in [prev_note+1, next_note); pass 3 needs a REST in the
    # measure of prev_note or the next 1-2 measures. Rests aren't
    # in all_notes (which is just Note instances), so we walk the
    # part's measures directly.
    from music21 import expressions
    stats["phantom_inserted"] = 0
    phantom_measures_used: set = set()
    for align_idx, (ai, ti) in enumerate(alignment):
        if ai is not None or ti is None:
            continue
        truth_tok = truth[ti]
        if not is_real_word(truth_tok):
            continue
        # Locate the previous audi-aligned note; without one we have
        # no anchor for measure or pitch.
        prev_ai = None
        for k in range(align_idx - 1, -1, -1):
            a, t = alignment[k]
            if a is not None and t is not None:
                prev_ai = a
                break
        if prev_ai is None:
            continue
        prev_audi_n = audi_pairs[prev_ai][1]
        prev_measure = prev_audi_n.activeSite
        if prev_measure is None:
            continue
        part = prev_measure.activeSite
        if part is None:
            continue
        # Did pass 2 already handle this gap? Look at any note in the
        # prev-or-following measures that now carries this lyric for
        # this verse.
        measures_in_part = list(part.getElementsByClass("Measure"))
        try:
            start_idx = measures_in_part.index(prev_measure)
        except ValueError:
            continue
        scan_measures = measures_in_part[start_idx:start_idx + 2]
        already_inserted = any(
            (lyr.number or 1) == verse_num and lyr.text == truth_tok
            for m_obj in scan_measures
            for n_obj in m_obj.recurse().notes
            for lyr in n_obj.lyrics
        )
        if already_inserted:
            continue
        # Pick the first Rest in a measure we haven't already used.
        target_rest = None
        target_measure = None
        target_m_num = None
        for m_obj in scan_measures:
            m_num = int(m_obj.number) if m_obj.number else 0
            if m_num in phantom_measures_used:
                continue
            for r in m_obj.recurse().getElementsByClass(note.Rest):
                target_rest = r
                target_measure = m_obj
                target_m_num = m_num
                break
            if target_rest is not None:
                break
        if target_rest is None:
            continue
        # Build phantom note: same duration as the rest, pitch copied
        # from the previous audi note.
        phantom = note.Note(prev_audi_n.pitch.nameWithOctave)
        phantom.duration = target_rest.duration
        ph_lyr = Lyric(text=truth_tok)
        ph_lyr.number = verse_num
        phantom.lyrics.append(ph_lyr)
        rest_offset = target_rest.offset
        target_measure.remove(target_rest)
        target_measure.insert(rest_offset, phantom)
        marker = expressions.TextExpression("?")
        marker.placement = "above"
        target_measure.insert(rest_offset, marker)
        stats["phantom_inserted"] += 1
        phantom_measures_used.add(target_m_num)

    return stats


def _swap_lone_v2_measures_to_v1(score) -> int:
    """Re-label verse-2 lyrics as verse-1 in measures where NO note
    carries any verse-1 lyric (#61).

    Audiveris classifies lyrics by their vertical position relative
    to the staff. In a 1st-ending bracketed block that contains only
    verse 1's text (typical for ABA-form songs where the 1st ending
    is a single-verse passage), the lyric line sometimes lands at the
    y-coordinate where verse 2 would normally appear in a 2-verse
    refrain. Audiveris then assigns the lyric verse=2, and spell_check
    has no v1 anchor to align the tesseract-recovered v1 text against.

    The heuristic: real verses progress in parallel -- when one note
    has v2 lyrics, a nearby note in the same measure typically has
    v1 lyrics. A measure where v1 is completely absent but v2 exists
    is almost certainly the mis-classification pattern, not a
    legitimate v2-only passage.

    Returns the count of lyrics re-labeled.
    """
    swapped = 0
    for p in score.parts:
        for m in p.getElementsByClass("Measure"):
            v1_count = 0
            v2_lyrs = []
            for n in m.recurse().notes:
                if not isinstance(n, note.Note) or not n.lyrics:
                    continue
                for lyr in n.lyrics:
                    v = lyr.number or 1
                    if v == 1:
                        v1_count += 1
                    elif v == 2:
                        v2_lyrs.append(lyr)
            if v1_count == 0 and v2_lyrs:
                for lyr in v2_lyrs:
                    lyr.number = 1
                    swapped += 1
    return swapped


def main(in_path: str, tess_path: str, out_path: str) -> None:
    v1_truth, v2_truth = tesseract_verse_streams(tess_path)
    score = converter.parse(in_path)
    lone_v2_swapped = _swap_lone_v2_measures_to_v1(score)
    part_idx, all_notes, by_verse = audiveris_tokens(score)
    report = {
        "part": part_idx,
        "v1_truth_tokens": len(v1_truth),
        "v2_truth_tokens": len(v2_truth),
        "lone_v2_swapped_to_v1": lone_v2_swapped,
        "verses": {},
    }
    for vnum, audi in by_verse.items():
        truth = v1_truth if vnum == 1 else v2_truth if v2_truth else v1_truth
        stats = apply_alignment(audi, truth, all_notes, vnum)
        report["verses"][vnum] = {"audi": len(audi), **stats}
    score.write("musicxml", fp=out_path, makeNotation=False)
    for k, v in report.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: spell_check_lyrics.py <in.musicxml> <tesseract.txt> <out.musicxml>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
