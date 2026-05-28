"""Apply key-signature alterations to vocal-staff notes that Audiveris
emitted without an explicit <alter>.

Audiveris occasionally exports vocal-staff notes with ``<step>F</step>``
and no ``<alter>`` in a key signature carrying F#, producing F-natural
where the published score had no accidental marker (i.e. F# by key sig).
The piano staves get the alter right; only the vocal part is affected.
Symptom on #13 LCWTO m19/m21: "ee-ther" notes render as F-natural
(MuseScore correctly draws the natural sign because the MusicXML pitch
IS F-natural per spec) instead of the implied F#.

Notes with an explicit accidental (sharp, flat, natural, etc.) are left
untouched -- a published natural sign on an F in G major is a real
F-natural and must survive. Only notes that came through with no
accidental information at all get the key-signature alteration applied.
"""
from __future__ import annotations

from music21 import converter, key, note, pitch


def apply_key_signature_to_implicit_notes(score) -> int:
    """Fix notes whose pitch step is altered by the active key signature
    but which were emitted without an <alter>. Returns count of notes
    modified."""
    n_fixed = 0
    for part in score.parts:
        active_alters: dict[str, float] = {}
        for m in part.getElementsByClass("Measure"):
            for ks in m.recurse().getElementsByClass(key.KeySignature):
                active_alters = {
                    p.step: (p.accidental.alter if p.accidental else 0.0)
                    for p in ks.alteredPitches
                }
            if not active_alters:
                continue
            for n in m.recurse().notes:
                if not isinstance(n, note.Note):
                    continue
                if n.pitch.accidental is not None:
                    continue
                if n.pitch.step not in active_alters:
                    continue
                alter = active_alters[n.pitch.step]
                acc = pitch.Accidental(alter)
                # The note's pitch already matches the active key
                # signature -- suppress the explicit accidental sign in
                # output so MuseScore doesn't draw a redundant sharp on
                # every F# in a G-major song.
                acc.displayStatus = False
                n.pitch.accidental = acc
                n_fixed += 1
    return n_fixed


def process_file(in_path: str, out_path: str) -> int:
    score = converter.parse(in_path)
    n = apply_key_signature_to_implicit_notes(score)
    score.write("musicxml", fp=out_path, makeNotation=False)
    return n


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    args = ap.parse_args()
    n = process_file(args.input, args.output)
    print(f"  key-aware pitch: applied alteration to {n} note(s)")


if __name__ == "__main__":
    main()
