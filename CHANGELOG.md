# Changelog

All notable changes to the Retune plugin are documented here.

## [Unreleased]

## [0.1.0]

### Added

- **Retune…** library card action for feedpak songs: converts a song to another Standard, Drop or
  shifted tuning and writes the result as a new pack next to the original.
- Audio pitch-shift of every stem and the preview clip with ffmpeg (`rubberband` when available,
  resample fallback otherwise).
- Chart rewrite for low-string changes (Standard ↔ Drop): re-frets notes, chords, chord templates,
  hand shapes and phrase levels; relocates notes above fret 24 to the next string, moves notes
  below the new open low string up an octave, and widens anchors to cover the moved notes.
- Stems are re-encoded in their resolved codec (the manifest `codec` field wins over the extension).
- Transposition of notation, vocal pitch, vocal pitch contour, `keys.json` and `harmony.json`.
