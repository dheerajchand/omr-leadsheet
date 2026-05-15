# Chord-symbol notation

This pipeline emits chord symbols that MuseScore parses into structured
chord descriptors, which it then renders using the configured **chord
style preset**. We separate two concerns:

1. **Emission grammar** — the ASCII tokens we write into MusicXML /
   `.mscx`. This is fixed by MuseScore's parser and is the same
   regardless of how the chord eventually displays.

2. **Display style** — controlled by the chord-style preset in the
   `.mss` style file applied during `mscore -S … -o …`. The preset
   chooses whether `m` displays as `m` or `–`, whether `o` displays as
   `o` or `°`, etc.

Reference: <https://handbook.musescore.org/text/chord-symbols>.

## Emission grammar (what the renderer writes)

MuseScore refuses Unicode chord glyphs on input. Specifically, the
handbook warns: *"Do not input Unicode characters like U+266F (♯) or
U+266D (♭) directly; MuseScore will not render them."* The renderer
therefore strips Unicode and emits only ASCII tokens. The strip is
implemented by
`omr_leadsheet.chord_ops.parser.normalize_for_musescore` and is
applied at every chord-text entry point (CNN classifier, VLM
classifier, hand-edits re-imported from external tools).

### Roots and accidentals

| Symbol | Emit |
|---|---|
| Sharp | `#` |
| Flat | `b` |
| Double sharp | `##` or `x` |
| Double flat | `bb` |

Never `♯`, `♭`, `𝄪`, `𝄫`.

### Qualities (token table)

The renderer emits one of two equivalent token sets depending on the
`notation_style` config field. Both parse identically in MuseScore;
the preset decides the displayed glyph.

| Quality | Symbolic (default) | Textual | Renders as (Jazz preset) | Renders as (Std preset) |
|---|---|---|---|---|
| major | `` (empty) | `` (empty) | _(none)_ | _(none)_ |
| minor | `-` | `m` | `–` | `m` |
| augmented | `+` | `aug` | `+` | `+` |
| diminished | `o` | `dim` | `°` | `dim` |
| dim 7 | `o7` | `dim7` | `°7` | `dim7` |
| half-diminished | `0` | `m7b5` | `ø` | `m7♭5` |
| major 7 | `t` | `maj7` | `△` | `maj7` |
| minor 7 | `-7` | `m7` | `–7` | `m7` |
| dom 7 | `7` | `7` | `7` | `7` |
| 6 | `6` | `6` | `6` | `6` |
| minor 6 | `-6` | `m6` | `–6` | `m6` |
| sus | `sus` | `sus` | `sus` | `sus` |

### Extensions and alterations

- Extensions `9`, `11`, `13` are appended directly: `G9`, `C-11`, `Ft13`.
- Alterations are emitted in parentheses: `G7(b5)`, `C7(#9)`.
- **Stacked 9-over-7** (the historical `G⁹⁷` notation) is emitted as
  literal `97`, not `9` or `9/7`. MuseScore's chord-recognition table
  treats `9` and `97` as distinct chord descriptors with different
  playback voicings. Collapsing them to `9` is audible and incorrect.
  Emitting `/7` is also incorrect because `/` is MuseScore's slash-bass
  separator and `G9/7` parses as *G9 over a 7th bass note* — nonsense.

### Bass / slash chords

`/` is the slash-bass separator: `C7/E` is C7 over E.

### "No chord" marker

`N.C.`

## Configuration

Set the project-level emission style via the `notation_style` field
on `Config` (or `NOTATION_STYLE` env var):

```python
config = Config(
    book_dir=...,
    notation_style="symbolic",  # default; or "textual"
)
```

The same string is exported to subprocess env (`NOTATION_STYLE=…`)
so the CNN and VLM classifiers honour it during inference.

To make the displayed glyph match the symbolic emission, point
`style_file` at a MuseScore style preset whose `<chordStyle>` is
`jazz` and `<chordDescriptionFile>` is `chords_jazz.xml`. For textual
display use the Standard preset (`<chordStyle>std`, `chords_std.xml`).

## Why two tokens for the same quality?

Both `Cm` and `C-` parse to "C minor" in MuseScore — the parser
accepts a half-dozen synonyms for most qualities. We pick one canonical
token per `notation_style` so:

- chord text round-trips cleanly (parse → format → parse is a
  fixed point);
- diffs between pipeline output and hand-edits don't churn purely
  because the user typed `-` where the recogniser emitted `m`;
- a single grep for `-7` finds all minor 7 chords in a corpus.

## Round-trip example

```python
from omr_leadsheet.chord_ops.parser import parse_chord, format_chord

# Mixed-style input including Unicode glyphs:
f = parse_chord("F♯△7")
# → ChordFields(root="F#", quality="maj7", extension="none", alteration="none")

format_chord(f, style="symbolic")  # → "F#t"
format_chord(f, style="textual")   # → "F#maj7"
```

## Pitfalls / gotchas

- **Half-diminished is the digit zero `0`, not the letter `O` or the
  glyph `ø`.** This is per the handbook: *"Type `D0` for D
  half-diminished, not `Dm70` or `Dm0`."*
- **The triangle is the letter `t`, not `△` / `Δ`.** On macOS the
  literal `ˆ` (Option-i) also works in MuseScore's UI, but the
  pipeline emits `t` for portability.
- Major-7 written as plain `M7` or `Ma7` is also accepted by
  MuseScore but we don't emit those — they collide with other
  abbreviations in some sources (e.g. `Ma6` is ambiguous in roman
  numeral analysis).
