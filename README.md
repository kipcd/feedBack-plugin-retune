# feedBack Plugin: Retune

Convert a feedpak song to another tuning. Retune pitch-shifts every audio stem and rewrites the
charts so the song plays in the tuning you're already in: Eb Standard → E Standard, Drop C → Drop D,
C Standard → Drop C, and so on.

The original song is never modified. The converted copy is written next to it as
`<name>_<Tuning>.feedpak` and shows up in the library straight away.

## What it can convert

Pick a target from the **Retune…** entry in a feedpak song card's menu. The plugin offers:

| From | To | Audio | Chart |
|---|---|---|---|
| any Standard | any other Standard (±7 semitones) | shifted | frets unchanged |
| any Drop | any other Drop | shifted | frets unchanged |
| a Standard | the Drop with the same top strings (E Std → Drop D, Eb Std → Drop C#…) | unchanged | low string re-fretted |
| a Standard / Drop | any Drop / Standard | shifted | low string re-fretted |
| any other tuning (Open G, DADGAD…) | the same tuning shifted up/down | shifted | frets unchanged |

### How the chart is rewritten

The audio moves by one shift for the whole song, chosen so the upper strings keep their frets. When
the low string changes relative to the others (Standard ↔ Drop), notes on it are re-fretted by ±2:

- Notes that land above fret 24 move to the next string up at the same pitch.
- Notes that would go below the open low string (e.g. an open D after Drop D → E Standard) move up an
  octave, since the new tuning can't play that pitch.
- Chord shapes, hand shapes, slides, multi-difficulty phrase levels and fingerings are updated to
  match. Fingerings on moved notes are cleared rather than guessed.

Other arrangements only have their low string changed when it matches the guitar's: same note, same
gap to the next string. A bass in Standard while the guitar is in Drop, or the low B of a 5-string
bass or 7-string guitar, keeps its tuning shape and only gets the audio shift.

Pitch data stored alongside the chart is transposed by the same shift: keys/piano charts, staff
notation (notes and key signatures), vocal pitch, the vocal pitch contour, `keys.json` and
`harmony.json`. Drum tabs, lyrics and
timing are unchanged.

### Audio quality

Audio is shifted with ffmpeg's `rubberband` filter when available (the Docker image's ffmpeg build has
it), which keeps the tempo and sounds clean for shifts of a few semitones. Without rubberband the
plugin falls back to a resample-based shift and says so. Shifts beyond ±3 semitones are allowed but
flagged, because they start to sound processed.

## Installation

```bash
cd /path/to/feedBack/plugins
git clone https://github.com/kipcd/feedback-plugin-retune.git retune
```

Restart feedBack. The plugin needs `ffmpeg` on the server for any conversion that shifts the audio;
conversions that only re-fret the low string work without it.

## Limitations

- Only feedpak (`.feedpak` / `.sloppak`) songs are supported.
- Chord template names (e.g. `Em7`) are left as they are, since charts differ on whether they name
  the shape or the sounding chord.
- `manifest.yaml` is re-serialized, so comments in it are not preserved. Hand-edited `.jsonc`
  arrangement files are written back as plain JSON.

## Development

```bash
pip install pytest fastapi httpx pyyaml
pytest tests
```

The audio test runs only when `ffmpeg` is installed.

## License

MIT — see [LICENSE](LICENSE).
