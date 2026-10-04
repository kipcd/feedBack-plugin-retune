import copy

import pytest


def lead(tuning, notes=None, chords=None, templates=None, handshapes=None, **extra):
    return {
        "name": "Lead",
        "tuning": tuning,
        "capo": 0,
        "notes": notes or [],
        "chords": chords or [],
        "anchors": [{"time": 0.0, "fret": 1, "width": 4}],
        "handshapes": handshapes or [],
        "templates": templates or [],
        **extra,
    }


def manifest_for(lead_tuning, bass_tuning=None, **extra):
    arrangements = [{"id": "lead", "name": "Lead", "file": "arrangements/lead.json", "tuning": lead_tuning}]
    if bass_tuning is not None:
        arrangements.append({"id": "bass", "name": "Bass", "file": "arrangements/bass.json", "tuning": bass_tuning})
    arrangements.append({"id": "drums", "name": "Drums", "type": "drums", "drum_tab": "drum_tab.json"})
    return {
        "title": "Song", "artist": "Band", "duration": 10.0,
        "arrangements": arrangements,
        "stems": [{"id": "full", "file": "stems/full.ogg", "default": True}],
        **extra,
    }


@pytest.mark.parametrize("offsets,name", [
    ([0] * 6, "E Standard"),
    ([-1] * 6, "Eb Standard"),
    ([-4] * 6, "C Standard"),
    ([-2, 0, 0, 0, 0, 0], "Drop D"),
    ([-3, -1, -1, -1, -1, -1], "Drop C#"),
    ([-1] * 4, "Eb Standard"),
    ([0, 0, 0, -1, 0, 0], "Custom (0 0 0 -1 0 0)"),
])
def test_tuning_name(core, offsets, name):
    assert core.tuning_name(offsets) == name


def test_seven_string_drop_is_named_after_its_low_string(core):
    assert core.tuning_name([-2, 0, 0, 0, 0, 0, 0], core.STANDARD_OPEN[("guitar", 7)]) == "Drop A"


def test_targets_from_eb_standard_cover_standard_and_drop(core):
    targets = {t["name"]: t for t in core.list_targets([-1] * 6, core.STANDARD_OPEN[("guitar", 6)])}
    assert (targets["E Standard"]["shift"], targets["E Standard"]["low_adjust"]) == (1, 0)
    assert (targets["Drop D"]["shift"], targets["Drop D"]["low_adjust"]) == (1, -2)
    assert (targets["Drop C#"]["shift"], targets["Drop C#"]["low_adjust"]) == (0, -2)
    assert "Eb Standard" not in targets
    assert targets["B Standard"]["large_shift"]


def test_targets_from_drop_offer_drop_and_standard(core):
    targets = {t["name"]: t for t in core.list_targets([-2, 0, 0, 0, 0, 0], core.STANDARD_OPEN[("guitar", 6)])}
    assert (targets["Drop C"]["shift"], targets["Drop C"]["low_adjust"]) == (-2, 0)
    assert (targets["E Standard"]["shift"], targets["E Standard"]["low_adjust"]) == (0, 2)


def test_standard_to_standard_keeps_frets_and_shifts_side_files(core):
    notes = [{"t": 1.0, "s": 0, "f": 0}, {"t": 2.0, "s": 5, "f": 12, "sl": 14}]
    files = {
        "arrangements/lead.json": lead([-1] * 6, notes=notes),
        "arrangements/bass.json": lead([-1] * 6, notes=[{"t": 1.0, "s": 0, "f": 3}], name="Bass"),
        "vocal_pitch.json": {"version": 1, "notes": [{"t": 1.0, "d": 0.5, "midi": 63}]},
        "vocal_pitch_contour.json": {"version": 1, "samples": [{"t": 0.0, "hz": 220.0}]},
        "keys.json": {"version": 1, "events": [{"t": 0.0, "key": "Ebm", "scale": "natural_minor"}]},
        "harmony.json": {"version": 1, "events": [{"t": 0.0, "root": "Bb", "quality": "7", "bass": "D"}]},
    }
    manifest = manifest_for([-1] * 6, [-1] * 6, vocal_pitch="vocal_pitch.json",
                            vocal_pitch_contour="vocal_pitch_contour.json",
                            keys="keys.json", harmony="harmony.json")
    before = copy.deepcopy(files["arrangements/lead.json"]["notes"])

    report = core.retune_pack(manifest, files, 1, 0)

    assert report["from"] == "Eb Standard" and report["to"] == "E Standard"
    assert manifest["arrangements"][0]["tuning"] == [0] * 6
    assert manifest["arrangements"][1]["tuning"] == [0] * 6
    assert files["arrangements/lead.json"]["tuning"] == [0] * 6
    assert files["arrangements/lead.json"]["notes"] == before
    assert files["vocal_pitch.json"]["notes"][0]["midi"] == 64
    assert files["vocal_pitch_contour.json"]["samples"][0]["hz"] == pytest.approx(233.08, abs=0.01)
    assert files["keys.json"]["events"][0]["key"] == "Em"
    assert files["harmony.json"]["events"][0]["root"] == "B"
    assert files["harmony.json"]["events"][0]["bass"] == "Eb"
    assert report["chart"]["refretted"] == 0
    assert "tuning" not in manifest["arrangements"][2]


def test_drop_d_to_e_standard_refrets_low_string(core):
    templates = [{"name": "D5", "fingers": [0, 1, 1, -1, -1, -1], "frets": [0, 0, 0, -1, -1, -1]},
                 {"name": "G5", "fingers": [1, 1, 1, -1, -1, -1], "frets": [5, 5, 5, -1, -1, -1]}]
    chords = [
        {"t": 1.0, "id": 0, "notes": [{"s": 0, "f": 0}, {"s": 1, "f": 0}, {"s": 2, "f": 0}]},
        {"t": 2.0, "id": 1, "notes": [{"s": 0, "f": 5}, {"s": 1, "f": 5}, {"s": 2, "f": 5}]},
    ]
    notes = [
        {"t": 3.0, "s": 0, "f": 0, "fg": 0},
        {"t": 3.5, "s": 0, "f": 7, "sl": 9, "fg": 1},
        {"t": 4.0, "s": 1, "f": 2},
    ]
    handshapes = [{"chord_id": 0, "start_time": 0.9, "end_time": 1.5}]
    files = {
        "arrangements/lead.json": lead([-2, 0, 0, 0, 0, 0], notes=notes, chords=chords,
                                       templates=templates, handshapes=handshapes),
        "arrangements/bass.json": lead([0, 0, 0, 0], notes=[{"t": 1.0, "s": 0, "f": 0}], name="Bass"),
    }
    manifest = manifest_for([-2, 0, 0, 0, 0, 0], [0, 0, 0, 0])

    report = core.retune_pack(manifest, files, 0, 2)
    arr = files["arrangements/lead.json"]

    assert report["to"] == "E Standard"
    assert manifest["arrangements"][0]["tuning"] == [0] * 6
    assert manifest["arrangements"][1]["tuning"] == [0, 0, 0, 0]
    assert files["arrangements/bass.json"]["notes"] == [{"t": 1.0, "s": 0, "f": 0}]

    open_d, fretted, other = arr["notes"]
    assert (open_d["s"], open_d["f"], open_d["fg"]) == (0, 10, -1)
    assert (fretted["s"], fretted["f"], fretted["sl"], fretted["fg"]) == (0, 5, 7, -1)
    assert (other["s"], other["f"]) == (1, 2)

    power_open, power_g = arr["chords"]
    assert [(n["s"], n["f"]) for n in power_open["notes"]] == [(0, 10), (1, 0), (2, 0)]
    assert [(n["s"], n["f"]) for n in power_g["notes"]] == [(0, 3), (1, 5), (2, 5)]
    assert power_g["id"] == 1
    assert arr["templates"][1]["frets"] == [3, 5, 5, -1, -1, -1]
    assert arr["templates"][1]["fingers"] == [-1, 1, 1, -1, -1, -1]
    assert power_open["id"] == 2
    assert arr["templates"][2]["frets"] == [10, 0, 0, -1, -1, -1]
    assert arr["templates"][0]["frets"] == [-1, 0, 0, -1, -1, -1]
    assert arr["handshapes"][0]["chord_id"] == 2
    assert report["chart"]["octave_moved"] == 2
    assert report["chart"]["refretted"] == 4


def test_e_standard_to_drop_d_moves_high_low_string_notes_up_a_string(core):
    notes = [{"t": 1.0, "s": 0, "f": 23}, {"t": 2.0, "s": 0, "f": 3}]
    files = {"arrangements/lead.json": lead([0] * 6, notes=notes)}
    manifest = manifest_for([0] * 6)

    report = core.retune_pack(manifest, files, 0, -2)

    high, low = files["arrangements/lead.json"]["notes"]
    assert (high["s"], high["f"]) == (1, 18)
    assert (low["s"], low["f"]) == (0, 5)
    assert report["chart"]["relocated"] == 1
    assert manifest["arrangements"][0]["tuning"] == [-2, 0, 0, 0, 0, 0]


def test_relocation_avoids_strings_already_sounding(core):
    notes = [{"t": 1.0, "s": 0, "f": 23}, {"t": 1.0, "s": 1, "f": 0}]
    files = {"arrangements/lead.json": lead([0] * 6, notes=notes)}

    core.retune_pack(manifest_for([0] * 6), files, 0, -2)

    moved = files["arrangements/lead.json"]["notes"][0]
    assert (moved["s"], moved["f"]) == (2, 13)


def test_phrase_levels_are_refretted(core):
    phrases = [{"start_time": 0, "end_time": 5, "max_difficulty": 0,
                "levels": [{"difficulty": 0, "notes": [{"t": 1.0, "s": 0, "f": 5}], "chords": [],
                            "anchors": [], "handshapes": []}]}]
    files = {"arrangements/lead.json": lead([-2, 0, 0, 0, 0, 0], phrases=phrases)}

    core.retune_pack(manifest_for([-2, 0, 0, 0, 0, 0]), files, -2, 0)
    assert files["arrangements/lead.json"]["phrases"][0]["levels"][0]["notes"][0]["f"] == 5

    core.retune_pack(manifest_for([-4, -2, -2, -2, -2, -2]), files, 0, 2)
    assert files["arrangements/lead.json"]["phrases"][0]["levels"][0]["notes"][0]["f"] == 3


def test_notation_is_transposed(core):
    notation = {"version": 1, "instrument": "piano", "staves": [{"id": "rh", "clef": "G2"}],
                "measures": [{"idx": 1, "t": 0.0, "ks": -3, "staves": {"rh": {"voices": [
                    {"v": 1, "beats": [{"t": 0.0, "dur": 4, "notes": [{"midi": 63}]}]}]}}}]}
    manifest = manifest_for([-1] * 6)
    manifest["arrangements"].append({"id": "keys", "type": "piano", "notation": "arrangements/notation_keys.json"})
    files = {"arrangements/lead.json": lead([-1] * 6), "arrangements/notation_keys.json": notation}

    core.retune_pack(manifest, files, 1, 0)

    measure = notation["measures"][0]
    assert measure["ks"] == 4
    assert measure["staves"]["rh"]["voices"][0]["beats"][0]["notes"][0]["midi"] == 64
    assert "tuning" not in manifest["arrangements"][-1]


@pytest.mark.parametrize("ks,shift,expected", [(0, 1, -5), (-3, 1, 4), (0, -1, 5), (-1, 2, 1), (6, 0, 6), (-6, 0, -6)])
def test_key_signature_transposition(core, ks, shift, expected):
    assert core.transpose_key_signature(ks, shift) == expected


@pytest.mark.parametrize("name,shift,expected", [("Em", 1, "Fm"), ("Ebm", 1, "Em"), ("F#", 1, "G"),
                                                  ("Bb", 2, "C"), ("C", 1, "C#"), ("Ab7", -1, "G7")])
def test_note_name_transposition(core, name, shift, expected):
    assert core.transpose_note_name(name, shift) == expected


def test_rejects_identity_and_out_of_range(core):
    files = {"arrangements/lead.json": lead([0] * 6)}
    with pytest.raises(core.RetuneError):
        core.retune_pack(manifest_for([0] * 6), files, 0, 0)
    with pytest.raises(core.RetuneError):
        core.retune_pack(manifest_for([0] * 6), files, 9, 0)
    with pytest.raises(core.RetuneError):
        core.retune_pack(manifest_for([0] * 6), files, 0, 1)


def test_bass_with_padded_six_element_tuning(core):
    entry = {"id": "bass", "name": "Bass", "file": "b.json", "tuning": [-2, 0, 0, 0, 0, 0]}
    arr = lead([-2, 0, 0, 0, 0, 0], notes=[{"t": 1.0, "s": 3, "f": 2}])
    assert core.string_count(entry, arr, entry["tuning"]) == 4


def test_notation_drops_spelling_overrides_and_gains_a_key_signature(core):
    notation = {"version": 1, "instrument": "piano", "staves": [{"id": "rh", "clef": "G2"}],
                "measures": [{"idx": 1, "t": 0.0, "staves": {"rh": {"voices": [
                    {"v": 1, "beats": [{"t": 0.0, "dur": 4, "notes": [{"midi": 61, "acc": 1}]}]}]}}},
                    {"idx": 2, "t": 2.0, "staves": {}}]}

    core.transpose_notation(notation, 1)

    first = notation["measures"][0]
    assert first["ks"] == -5
    assert first["staves"]["rh"]["voices"][0]["beats"][0]["notes"][0] == {"midi": 62}
    assert "ks" not in notation["measures"][1]


def test_anchors_grow_to_cover_moved_notes(core):
    notes = [{"t": 1.0, "s": 0, "f": 0}, {"t": 1.5, "s": 0, "f": 3}, {"t": 5.0, "s": 1, "f": 7}]
    anchors = [{"time": 0.0, "fret": 1, "width": 4}, {"time": 4.0, "fret": 7, "width": 4}]
    files = {"arrangements/lead.json": lead([-2, 0, 0, 0, 0, 0], notes=notes, anchors=anchors)}

    core.retune_pack(manifest_for([-2, 0, 0, 0, 0, 0]), files, 0, 2)

    first, second = files["arrangements/lead.json"]["anchors"]
    assert (first["fret"], first["width"]) == (1, 10)
    assert (second["fret"], second["width"]) == (7, 4)


@pytest.mark.parametrize("entry,kind", [
    ({"type": "piano", "name": "Lead"}, "keys"),
    ({"type": "keys"}, "keys"),
    ({"name": "Keys"}, "keys"),
    ({"name": "Synth Pad"}, "keys"),
    ({"name": "Monkeys Medley"}, "guitar"),
    ({"name": "Lead Vocals"}, "vocals"),
    ({"type": "rhythm", "name": "Bass 2"}, "bass"),
    ({"type": "drums"}, "drums"),
    ({"name": "Lead"}, "guitar"),
])
def test_instrument_kind_matches_the_host(core, entry, kind):
    assert core.instrument_kind(entry) == kind


def test_keys_chart_is_neither_reference_nor_refretted(core):
    keys_chart = lead([0] * 6, notes=[{"t": 1.0, "s": 0, "f": 0}], name="Keys")
    files = {
        "arrangements/keys.json": keys_chart,
        "arrangements/lead.json": lead([-2, 0, 0, 0, 0, 0], notes=[{"t": 1.0, "s": 0, "f": 5}]),
    }
    manifest = manifest_for([-2, 0, 0, 0, 0, 0])
    manifest["arrangements"].insert(0, {"id": "keys", "name": "Keys", "type": "piano",
                                        "file": "arrangements/keys.json"})

    assert core.reference_entry(manifest, files)["id"] == "lead"
    report = core.retune_pack(manifest, files, 0, 2)

    assert report["from"] == "Drop D" and report["to"] == "E Standard"
    assert [a["id"] for a in report["arrangements"]] == ["lead"]
    assert files["arrangements/lead.json"]["notes"][0]["f"] == 3
    assert keys_chart["notes"][0]["f"] == 0
    assert "tuning" not in manifest["arrangements"][0]


def test_keys_chart_follows_the_audio_shift(core):
    keys_chart = lead([0] * 6, notes=[{"t": 1.0, "s": 2, "f": 23}, {"t": 2.0, "s": 2, "f": 12}],
                      chords=[{"t": 3.0, "id": 0, "notes": [{"s": 2, "f": 12}, {"s": 2, "f": 16}]}],
                      name="Keys")
    files = {"arrangements/keys.json": keys_chart, "arrangements/lead.json": lead([-1] * 6)}
    manifest = manifest_for([-1] * 6)
    manifest["arrangements"].append({"id": "keys", "name": "Keys", "type": "keys",
                                     "file": "arrangements/keys.json"})

    core.retune_pack(manifest, files, 1, 0)

    assert [(n["s"], n["f"]) for n in keys_chart["notes"]] == [(3, 0), (2, 13)]
    assert [(n["s"], n["f"]) for n in keys_chart["chords"][0]["notes"]] == [(2, 13), (2, 17)]
    assert "tuning" not in manifest["arrangements"][-1]


@pytest.mark.parametrize("kind,count,src", [("bass", 5, [0] * 5), ("guitar", 7, [0] * 7)])
def test_extended_range_low_b_is_not_dropped_with_the_guitar(core, kind, count, src):
    extra = {"id": "ext", "name": "Bass" if kind == "bass" else "Lead 7", "type": kind,
             "file": "arrangements/ext.json", "tuning": src}
    files = {
        "arrangements/lead.json": lead([0] * 6, notes=[{"t": 1.0, "s": 0, "f": 3}]),
        "arrangements/ext.json": lead(src, notes=[{"t": 1.0, "s": 0, "f": 3}], name=extra["name"]),
    }
    manifest = manifest_for([0] * 6)
    manifest["arrangements"].append(extra)

    core.retune_pack(manifest, files, 0, -2)

    assert manifest["arrangements"][0]["tuning"] == [-2, 0, 0, 0, 0, 0]
    assert extra["tuning"] == src
    assert files["arrangements/ext.json"]["notes"][0]["f"] == 3


def test_bass_in_the_same_tuning_drops_with_the_guitar(core):
    files = {"arrangements/lead.json": lead([0] * 6),
             "arrangements/bass.json": lead([0, 0, 0, 0], notes=[{"t": 1.0, "s": 0, "f": 3}], name="Bass")}
    manifest = manifest_for([0] * 6, [0, 0, 0, 0])

    core.retune_pack(manifest, files, 0, -2)

    assert manifest["arrangements"][1]["tuning"] == [-2, 0, 0, 0]
    assert files["arrangements/bass.json"]["notes"][0]["f"] == 5


def test_files_shared_by_two_arrangements_are_transformed_once(core):
    notation = {"version": 1, "measures": [{"idx": 1, "t": 0.0, "ks": 0, "staves": {"rh": {"voices": [
        {"v": 1, "beats": [{"t": 0.0, "dur": 4, "notes": [{"midi": 60}]}]}]}}}]}
    chart = lead([-2, 0, 0, 0, 0, 0], notes=[{"t": 1.0, "s": 0, "f": 5}])
    manifest = manifest_for([-2, 0, 0, 0, 0, 0])
    manifest["arrangements"].append({"id": "lead2", "name": "Lead 2", "file": "arrangements/lead.json",
                                     "tuning": [-2, 0, 0, 0, 0, 0]})
    for i in (1, 2):
        manifest["arrangements"].append({"id": f"keys{i}", "type": "piano",
                                         "notation": "arrangements/notation.json"})
    files = {"arrangements/lead.json": chart, "arrangements/notation.json": notation}

    report = core.retune_pack(manifest, files, 1, 2)

    assert chart["notes"][0]["f"] == 3
    assert report["chart"]["refretted"] == 1
    assert manifest["arrangements"][2]["tuning"] == [1, 1, 1, 1, 1, 1]
    assert notation["measures"][0]["staves"]["rh"]["voices"][0]["beats"][0]["notes"][0]["midi"] == 61
    assert notation["measures"][0]["ks"] == -5


def test_difficulty_levels_are_not_counted_twice(core):
    def level(difficulty):
        return {"difficulty": difficulty, "notes": [{"t": 1.0, "s": 0, "f": 5}], "chords": [],
                "anchors": [], "handshapes": []}

    phrases = [{"start_time": 0, "end_time": 5, "max_difficulty": 2, "levels": [level(0), level(1), level(2)]}]
    with_top = lead([-2, 0, 0, 0, 0, 0], notes=[{"t": 1.0, "s": 0, "f": 5}], phrases=copy.deepcopy(phrases))
    levels_only = lead([-2, 0, 0, 0, 0, 0], phrases=copy.deepcopy(phrases))

    for arrangement in (with_top, levels_only):
        report = core.retune_pack(manifest_for([-2, 0, 0, 0, 0, 0]),
                                  {"arrangements/lead.json": arrangement}, 0, 2)
        assert report["chart"]["refretted"] == 1
        assert [lv["notes"][0]["f"] for lv in arrangement["phrases"][0]["levels"]] == [3, 3, 3]


def test_capo_relative_frets_stay_playable_down_to_the_capo(core):
    notes = [{"t": 1.0, "s": 0, "f": 2}, {"t": 2.0, "s": 0, "f": 3}]
    files = {"arrangements/lead.json": lead([-2, 0, 0, 0, 0, 0], notes=notes)}
    manifest = manifest_for([-2, 0, 0, 0, 0, 0])
    manifest["arrangements"][0]["capo"] = 2

    core.retune_pack(manifest, files, 0, 2)

    assert [(n["s"], n["f"]) for n in files["arrangements/lead.json"]["notes"]] == [(0, 0), (0, 1)]


def test_capo_lowers_the_highest_playable_fret(core):
    notes = [{"t": 1.0, "s": 0, "f": 21}]
    files = {"arrangements/lead.json": lead([0] * 6, notes=notes)}
    manifest = manifest_for([0] * 6)
    manifest["arrangements"][0]["capo"] = 2

    report = core.retune_pack(manifest, files, 0, -2)

    note = files["arrangements/lead.json"]["notes"][0]
    assert (note["s"], note["f"]) == (1, 16)
    assert report["chart"]["relocated"] == 1
    assert core._highest_fret.get() == core.MAX_FRET
