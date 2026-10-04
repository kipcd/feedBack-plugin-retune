from __future__ import annotations

import contextvars
import copy
import math
import re
from collections import Counter

MAX_FRET = 24
MAX_SHIFT = 7
LARGE_SHIFT = 3
SAME_TIME = 1e-3

STANDARD_OPEN = {
    ("guitar", 4): [40, 45, 50, 55],
    ("guitar", 5): [40, 45, 50, 55, 59],
    ("guitar", 6): [40, 45, 50, 55, 59, 64],
    ("guitar", 7): [35, 40, 45, 50, 55, 59, 64],
    ("guitar", 8): [30, 35, 40, 45, 50, 55, 59, 64],
    ("bass", 4): [28, 33, 38, 43],
    ("bass", 5): [23, 28, 33, 38, 43],
    ("bass", 6): [23, 28, 33, 38, 43, 48],
}

PITCH_CLASS_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PITCH_CLASS_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCH_CLASS_DEFAULT = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class RetuneError(ValueError):
    pass


def tuning_family(offsets: list[int]) -> str:
    if len(offsets) < 2:
        return "other"
    if all(o == offsets[0] for o in offsets):
        return "standard"
    if offsets[0] == offsets[1] - 2 and all(o == offsets[1] for o in offsets[1:]):
        return "drop"
    return "other"


def tuning_name(offsets: list[int], standard_open: list[int] | None = None) -> str:
    family = tuning_family(offsets)
    if family == "standard":
        return f"{PITCH_CLASS_DEFAULT[(4 + offsets[0]) % 12]} Standard"
    if family == "drop":
        low_open = (standard_open or STANDARD_OPEN[("guitar", 6)])[0]
        return f"Drop {PITCH_CLASS_DEFAULT[(low_open + offsets[0]) % 12]}"
    return "Custom (" + " ".join(f"{o:+d}" if o else "0" for o in offsets) + ")"


def instrument_kind(entry: dict, arrangement: dict | None = None) -> str:
    kind = str(entry.get("type") or "").strip().lower()
    if kind in ("bass", "drums"):
        return kind
    if kind in ("piano", "keys"):
        return "keys"
    name = " ".join(str(v) for v in (entry.get("name"), entry.get("id"), (arrangement or {}).get("name")) if v).lower()
    if "bass" in name:
        return "bass"
    if "drum" in name or "percussion" in name:
        return "drums"
    if "vocal" in name:
        return "vocals"
    if re.search(r"\b(?:keys|piano|keyboard|synth)\b", name):
        return "keys"
    return "guitar"


def is_bass(entry: dict, arrangement: dict | None = None) -> bool:
    return instrument_kind(entry, arrangement) == "bass"


def is_pitched_chart(entry: dict, arrangement: dict | None = None) -> bool:
    return (bool(entry.get("file")) and not entry.get("drum_tab")
            and instrument_kind(entry, arrangement) in ("guitar", "bass"))


def _iter_chart_notes(arrangement: dict):
    for n in arrangement.get("notes") or []:
        yield n
    for c in arrangement.get("chords") or []:
        for n in c.get("notes") or []:
            yield n
    for phrase in arrangement.get("phrases") or []:
        for level in phrase.get("levels") or []:
            for n in level.get("notes") or []:
                yield n
            for c in level.get("chords") or []:
                for n in c.get("notes") or []:
                    yield n


def string_count(entry: dict, arrangement: dict, tuning: list[int]) -> int:
    highest = max((int(n.get("s", 0)) for n in _iter_chart_notes(arrangement)), default=-1)
    for t in arrangement.get("templates") or []:
        frets = t.get("frets") or []
        for s, f in enumerate(frets):
            if f is not None and f >= 0:
                highest = max(highest, s)
    count = len(tuning) if tuning else 6
    if is_bass(entry, arrangement) and count == 6 and highest < 4:
        count = 4
    return max(count, highest + 1)


def standard_open(entry: dict, arrangement: dict, count: int) -> list[int]:
    kind = "bass" if is_bass(entry, arrangement) else "guitar"
    key = (kind, count)
    if key in STANDARD_OPEN:
        return STANDARD_OPEN[key]
    base = STANDARD_OPEN[(kind, 6)]
    if count < len(base):
        return base[:count]
    return base + [base[-1] + 5 * (i + 1) for i in range(count - len(base))]


def source_tuning(entry: dict, arrangement: dict | None) -> list[int]:
    tuning = entry.get("tuning")
    if tuning is None and arrangement is not None:
        tuning = arrangement.get("tuning")
    if tuning is None:
        tuning = [0, 0, 0, 0, 0, 0]
    return [int(o) for o in tuning]


def reference_entry(manifest: dict, arrangements: dict[str, dict]) -> dict | None:
    charts = [e for e in manifest.get("arrangements") or []
              if is_pitched_chart(e, arrangements.get(e.get("file")))]
    for e in charts:
        if not is_bass(e, arrangements.get(e["file"])):
            return e
    return charts[0] if charts else None


def reference_tuning(ref: dict, files: dict[str, dict]) -> tuple[list[int], list[int]]:
    arrangement = files.get(ref["file"]) or {}
    src = source_tuning(ref, arrangement)
    return src, standard_open(ref, arrangement, string_count(ref, arrangement, src))


def low_adjust_for(src: list[int], std: list[int], ref_src: list[int], ref_std: list[int],
                   low_adjust: int) -> int:
    if not low_adjust or len(src) < 2 or len(ref_src) < 2:
        return 0
    same_gap = src[0] - src[1] == ref_src[0] - ref_src[1]
    same_note = (std[0] + src[0]) % 12 == (ref_std[0] + ref_src[0]) % 12
    return low_adjust if same_gap and same_note else 0


def target_tuning(src: list[int], shift: int, low_adjust: int) -> list[int]:
    out = [o + shift for o in src]
    if out:
        out[0] += low_adjust
    return out


def list_targets(ref_src: list[int], ref_open: list[int]) -> list[dict]:
    family = tuning_family(ref_src)
    adjusts = [0]
    if family == "standard":
        adjusts.append(-2)
    elif family == "drop":
        adjusts.append(2)
    targets = []
    for adjust in adjusts:
        for shift in range(-MAX_SHIFT, MAX_SHIFT + 1):
            if shift == 0 and adjust == 0:
                continue
            offsets = target_tuning(ref_src, shift, adjust)
            targets.append({
                "shift": shift,
                "low_adjust": adjust,
                "offsets": offsets,
                "name": tuning_name(offsets, ref_open),
                "family": tuning_family(offsets),
                "large_shift": abs(shift) > LARGE_SHIFT,
            })
    targets.sort(key=lambda t: (t["family"] != "standard", -t["offsets"][-1], t["low_adjust"]))
    return targets


def _same_time(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < SAME_TIME


_highest_fret: contextvars.ContextVar[int] = contextvars.ContextVar("highest_fret", default=MAX_FRET)


def _valid_fret(f: int) -> bool:
    return 0 <= f <= _highest_fret.get()


def _candidates(pitch: int, string: int, opens: list[int], occupied: set[int]):
    options = []
    for octave_rank, p in enumerate((pitch, pitch + 12, pitch - 12)):
        for s, open_pitch in enumerate(opens):
            if s in occupied:
                continue
            f = p - open_pitch
            if _valid_fret(f):
                options.append((octave_rank, s != string, abs(s - string), f, s))
    options.sort()
    return [(s, f, rank) for rank, _, _, f, s in options]


class ChartReport:
    def __init__(self):
        self.refretted = 0
        self.relocated = 0
        self.octave_moved = 0
        self.removed = 0
        self.slides_cleared = 0
        self.harmonics_moved = 0

    def add(self, other: "ChartReport"):
        for k, v in vars(other).items():
            setattr(self, k, getattr(self, k) + v)

    def as_dict(self) -> dict:
        return dict(vars(self))


def _move_note(note: dict, new_s: int, new_f: int, report: ChartReport):
    old_f = int(note.get("f", 0))
    note["s"] = new_s
    note["f"] = new_f
    for key in ("sl", "slu"):
        target = note.get(key, -1)
        if target is None or target < 0:
            continue
        moved = target + (new_f - old_f)
        if _valid_fret(moved):
            note[key] = moved
        else:
            note[key] = -1
            report.slides_cleared += 1
    if note.get("fg", -1) not in (-1, None):
        note["fg"] = -1


def _refret_note(note: dict, delta: list[int], opens: list[int], occupied,
                 report: ChartReport, moved: list, t: float) -> bool:
    s = int(note.get("s", 0))
    d = delta[s] if s < len(delta) else 0
    if d == 0:
        return True
    old_f = int(note.get("f", 0))
    new_f = old_f + d
    report.refretted += 1
    if note.get("hm"):
        report.harmonics_moved += 1
    if _valid_fret(new_f):
        _move_note(note, s, new_f, report)
        moved.append((t, new_f))
        return True
    pitch = opens[s] + new_f
    for cand_s, cand_f, octave_rank in _candidates(pitch, s, opens, occupied()):
        note["f"] = old_f
        _move_note(note, cand_s, cand_f, report)
        moved.append((t, cand_f))
        if octave_rank:
            report.octave_moved += 1
        else:
            report.relocated += 1
        return True
    report.removed += 1
    return False


def _fit_anchors(anchors: list[dict], moved: list[tuple[float, int]]):
    if not moved:
        return
    ordered = sorted(anchors, key=lambda a: float(a.get("time", 0)))
    for i, anchor in enumerate(ordered):
        start = float(anchor.get("time", 0)) - SAME_TIME
        end = float(ordered[i + 1].get("time", 0)) - SAME_TIME if i + 1 < len(ordered) else math.inf
        frets = [f for t, f in moved if start <= t < end and f > 0]
        if not frets:
            continue
        fret = int(anchor.get("fret") or 1)
        width = anchor.get("width") or 4
        lo = min(fret, *frets)
        hi = max(fret + width - 1, *frets)
        anchor["fret"] = lo
        anchor["width"] = hi - lo + 1


def _refret_notes(notes: list[dict], delta, opens, report, moved) -> list[dict]:
    by_time: dict[float, list[dict]] = {}
    for n in notes:
        by_time.setdefault(round(float(n.get("t", 0)), 3), []).append(n)

    def occupied_for(note):
        t = round(float(note.get("t", 0)), 3)
        near = []
        for key in (t - 0.001, t, t + 0.001):
            near.extend(by_time.get(round(key, 3), []))
        return lambda: {int(o.get("s", 0)) for o in near
                        if o is not note and _same_time(o.get("t", 0), note.get("t", 0))}

    return [n for n in notes
            if _refret_note(n, delta, opens, occupied_for(n), report, moved, float(n.get("t", 0)))]


def _refret_chord(chord: dict, delta, opens, report, moved) -> list[tuple[int, int, int]]:
    moves = []
    kept = []
    notes = chord.get("notes") or []
    for note in notes:
        def occupied(note=note):
            return {int(o.get("s", 0)) for o in notes if o is not note}
        orig = (int(note.get("s", 0)), int(note.get("f", 0)))
        if _refret_note(note, delta, opens, occupied, report, moved, float(chord.get("t", 0))):
            kept.append(note)
            moves.append((orig[0], int(note["s"]), int(note["f"])))
        else:
            moves.append((orig[0], -1, -1))
    chord["notes"] = kept
    return moves


def _shift_template(template: dict, delta: list[int]) -> dict:
    out = copy.deepcopy(template)
    frets = list(out.get("frets") or [])
    fingers = list(out.get("fingers") or [-1] * len(frets))
    fingers += [-1] * (len(frets) - len(fingers))
    for s, f in enumerate(frets):
        d = delta[s] if s < len(delta) else 0
        if f is None or f < 0 or d == 0:
            continue
        nf = f + d
        if _valid_fret(nf):
            frets[s] = nf
            fingers[s] = 0 if nf == 0 else -1
        else:
            frets[s] = -1
            fingers[s] = -1
    out["frets"] = frets
    if "fingers" in template:
        out["fingers"] = fingers
    return out


class _TemplateBook:
    def __init__(self, templates: list[dict], delta: list[int]):
        self.originals = templates
        self.templates = [_shift_template(t, delta) for t in templates]
        self.variants: dict[tuple, int] = {}

    def resolve(self, old_id: int, moves: list[tuple[int, int, int]]) -> int:
        if not (0 <= old_id < len(self.templates)):
            return old_id
        base = self.templates[old_id]
        frets = list(base.get("frets") or [])
        for orig_s, new_s, new_f in moves:
            if new_s != orig_s and orig_s < len(frets):
                frets[orig_s] = -1
            if new_s >= 0:
                frets += [-1] * (new_s + 1 - len(frets))
                frets[new_s] = new_f
        if frets == list(base.get("frets") or []):
            return old_id
        key = (old_id, tuple(frets))
        if key in self.variants:
            return self.variants[key]
        variant = copy.deepcopy(base)
        if "fingers" in variant:
            fingers = list(variant["fingers"]) + [-1] * (len(frets) - len(variant["fingers"]))
            base_frets = list(base.get("frets") or [])
            variant["fingers"] = [
                fingers[s] if s < len(base_frets) and base_frets[s] == f else (0 if f == 0 else -1)
                for s, f in enumerate(frets)
            ]
        variant["frets"] = frets
        self.templates.append(variant)
        self.variants[key] = len(self.templates) - 1
        return self.variants[key]


def _refret_layer(layer: dict, book: _TemplateBook, delta, opens, report):
    moved: list[tuple[float, int]] = []
    if "notes" in layer:
        layer["notes"] = _refret_notes(layer.get("notes") or [], delta, opens, report, moved)
    usage: dict[int, list[tuple[float, int]]] = {}
    for chord in layer.get("chords") or []:
        moves = _refret_chord(chord, delta, opens, report, moved)
        old_id = int(chord.get("id", 0))
        new_id = book.resolve(old_id, moves)
        chord["id"] = new_id
        usage.setdefault(old_id, []).append((float(chord.get("t", 0)), new_id))
    for hs in layer.get("handshapes") or []:
        old_id = int(hs.get("chord_id", 0))
        start, end = float(hs.get("start_time", 0)), float(hs.get("end_time", 0))
        ids = Counter(new_id for t, new_id in usage.get(old_id, [])
                      if start - SAME_TIME <= t <= end + SAME_TIME)
        if ids:
            hs["chord_id"] = ids.most_common(1)[0][0]
    _fit_anchors(layer.get("anchors") or [], moved)


def refret_arrangement(arrangement: dict, delta: list[int], opens: list[int], capo: int = 0) -> ChartReport:
    report = ChartReport()
    if not any(delta):
        return report
    token = _highest_fret.set(MAX_FRET - max(0, int(capo or 0)))
    try:
        return _refret_arrangement(arrangement, delta, opens, report)
    finally:
        _highest_fret.reset(token)


def _refret_arrangement(arrangement: dict, delta: list[int], opens: list[int], report: ChartReport) -> ChartReport:
    book = _TemplateBook(arrangement.get("templates") or [], delta)
    _refret_layer(arrangement, book, delta, opens, report)
    counts_top_level = bool(arrangement.get("notes") or arrangement.get("chords"))
    for phrase in arrangement.get("phrases") or []:
        levels = phrase.get("levels") or []
        hardest = max(levels, key=lambda lv: lv.get("difficulty", 0), default=None)
        for level in levels:
            counted = not counts_top_level and level is hardest
            _refret_layer(level, book, delta, opens, report if counted else ChartReport())
    if "templates" in arrangement:
        arrangement["templates"] = book.templates
    return report


def transpose_note_name(name: str, shift: int) -> str:
    if not isinstance(name, str) or not name or name[0].upper() not in NOTE_BASE:
        return name
    root = name[0].upper()
    pc = NOTE_BASE[root]
    i = 1
    accidental = ""
    while i < len(name) and name[i] in "#b♯♭":
        accidental += name[i]
        pc += 1 if name[i] in "#♯" else -1
        i += 1
    rest = name[i:]
    new_pc = (pc + shift) % 12
    if any(a in "b♭" for a in accidental):
        table = PITCH_CLASS_FLAT
    elif accidental:
        table = PITCH_CLASS_SHARP
    else:
        table = PITCH_CLASS_DEFAULT
    return table[new_pc] + rest


def transpose_key_signature(ks: int, shift: int) -> int:
    pc = (int(ks) * 7 + shift) % 12
    fifths = (pc * 7) % 12
    if fifths > 6 or (fifths == 6 and ks < 0):
        fifths -= 12
    return fifths


def transpose_notation(doc: dict, shift: int):
    measures = doc.get("measures") or []
    if measures and measures[0].get("ks") is None:
        measures[0]["ks"] = 0
    for measure in measures:
        if "ks" in measure and measure["ks"] is not None:
            measure["ks"] = transpose_key_signature(measure["ks"], shift)
        for staff in (measure.get("staves") or {}).values():
            for voice in (staff or {}).get("voices") or []:
                for beat in voice.get("beats") or []:
                    for note in beat.get("notes") or []:
                        if isinstance(note.get("midi"), (int, float)):
                            note["midi"] = max(0, min(127, int(note["midi"]) + shift))
                            note.pop("acc", None)


def transpose_keys_chart(arrangement: dict, shift: int):
    for note in _iter_chart_notes(arrangement):
        try:
            midi = int(note.get("s", 0)) * 24 + int(note.get("f", 0))
        except (TypeError, ValueError):
            continue
        midi = max(0, min(127, midi + shift))
        note["s"], note["f"] = divmod(midi, 24)


def transpose_vocal_pitch(doc: dict, shift: int):
    for note in doc.get("notes") or []:
        if isinstance(note.get("midi"), (int, float)):
            note["midi"] = max(0, min(127, note["midi"] + shift))


def transpose_contour(doc: dict, shift: int):
    ratio = 2 ** (shift / 12)
    for sample in doc.get("samples") or []:
        hz = sample.get("hz")
        if isinstance(hz, (int, float)) and hz > 0:
            sample["hz"] = round(hz * ratio, 2)


def transpose_keys(doc: dict, shift: int):
    for event in doc.get("events") or []:
        if "key" in event:
            event["key"] = transpose_note_name(event["key"], shift)


def transpose_harmony(doc: dict, shift: int):
    for event in doc.get("events") or []:
        for field in ("root", "bass"):
            if event.get(field):
                event[field] = transpose_note_name(event[field], shift)


SIDE_FILE_TRANSFORMS = {
    "vocal_pitch": transpose_vocal_pitch,
    "vocal_pitch_contour": transpose_contour,
    "keys": transpose_keys,
    "harmony": transpose_harmony,
}


def plan_arrangement(entry: dict, arrangement: dict, ref_src: list[int], ref_std: list[int],
                     shift: int, low_adjust: int):
    src = source_tuning(entry, arrangement)
    count = string_count(entry, arrangement, src)
    std = standard_open(entry, arrangement, count)
    adjust = low_adjust_for(src, std, ref_src, ref_std, low_adjust)
    tgt = target_tuning(src, shift, adjust)
    padded = tgt + [tgt[-1] if tgt else shift] * (count - len(tgt))
    opens = [std[s] + padded[s] for s in range(count)]
    delta = [0] * count
    if count:
        delta[0] = -adjust
    return src, tgt, delta, opens, std


def retune_pack(manifest: dict, files: dict[str, dict], shift: int, low_adjust: int) -> dict:
    if shift == 0 and low_adjust == 0:
        raise RetuneError("Target tuning is the same as the source")
    if abs(shift) > MAX_SHIFT:
        raise RetuneError(f"Shift is limited to ±{MAX_SHIFT} semitones")
    if low_adjust not in (-2, 0, 2):
        raise RetuneError("Low-string adjustment must be -2, 0 or +2")
    ref = reference_entry(manifest, files)
    if ref is None:
        raise RetuneError("The pack has no fretted arrangement to retune")
    ref_src, ref_std = reference_tuning(ref, files)

    total = ChartReport()
    arrangements = []
    done: set[str] = set()

    def first_time(path) -> bool:
        if path in done:
            return False
        done.add(path)
        return True

    for entry in manifest.get("arrangements") or []:
        notation = entry.get("notation")
        if notation and notation in files and shift and first_time(notation):
            transpose_notation(files[notation], shift)
        chart = files.get(entry.get("file"))
        if shift and chart is not None and not entry.get("drum_tab") \
                and instrument_kind(entry, chart) == "keys" and first_time(entry["file"]):
            transpose_keys_chart(chart, shift)
        if not is_pitched_chart(entry, chart):
            continue
        arrangement = files.get(entry["file"])
        if arrangement is None:
            raise RetuneError(f"Arrangement file {entry['file']} is missing")
        src, tgt, delta, opens, std = plan_arrangement(entry, arrangement, ref_src, ref_std, shift, low_adjust)
        capo = entry.get("capo", arrangement.get("capo", 0))
        report = refret_arrangement(arrangement, delta, opens, capo) if first_time(entry["file"]) else ChartReport()
        total.add(report)
        entry["tuning"] = tgt
        if "tuning" in arrangement:
            arrangement["tuning"] = list(tgt)
        arrangements.append({
            "id": entry.get("id"),
            "name": entry.get("name") or entry.get("id"),
            "from": tuning_name(src, std),
            "to": tuning_name(tgt, std),
            "tuning": tgt,
            **report.as_dict(),
        })

    if shift:
        for key, transform in SIDE_FILE_TRANSFORMS.items():
            path = manifest.get(key)
            if isinstance(path, str) and path in files and first_time(path):
                transform(files[path], shift)

    return {
        "shift": shift,
        "low_adjust": low_adjust,
        "from": tuning_name(ref_src, ref_std),
        "to": tuning_name(target_tuning(ref_src, shift, low_adjust), ref_std),
        "arrangements": arrangements,
        "chart": total.as_dict(),
    }


def pitch_ratio(shift: int) -> float:
    return math.pow(2, shift / 12)
