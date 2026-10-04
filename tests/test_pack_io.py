import json

import pytest


def test_strip_jsonc_keeps_strings_intact(pack_io):
    text = '{\n  // comment\n  "url": "http://x//y", /* block */ "n": [1, 2,],\n}'
    assert json.loads(pack_io.strip_jsonc(text)) == {"url": "http://x//y", "n": [1, 2]}


def test_strip_jsonc_keeps_commas_inside_strings(pack_io):
    text = '{"name": "Riff, ]", "alt": "a,}", "esc": "q\\",]", "list": ["x", // c\n],}'
    assert json.loads(pack_io.strip_jsonc(text)) == {"name": "Riff, ]", "alt": "a,}", "esc": 'q",]', "list": ["x"]}


def test_broken_text_files_are_pack_errors(pack_io, tmp_path):
    d = tmp_path / "Song.feedpak"
    d.mkdir()
    (d / "manifest.yaml").write_text("title: [unclosed\n")
    (d / "lead.json").write_bytes(b'{"name": "\xff\xfe"}')
    with pack_io.Pack(d) as pack:
        with pytest.raises(pack_io.PackError, match="not valid YAML"):
            pack.manifest()
        with pytest.raises(pack_io.PackError, match="not UTF-8"):
            pack.read_json("lead.json")


@pytest.mark.parametrize("rel,key", [("./a//b.json", "a/b.json"), ("a\\b.json", "a/b.json"), ("a/x/../b", "a/b")])
def test_member_names_are_normalized_like_the_host(pack_io, rel, key):
    assert pack_io.normalize_member(rel) == key


@pytest.mark.parametrize("rel", ["../evil", "..\\evil", "/abs", "a/../../b", "C:/x", "C:\\x", ""])
def test_rejects_paths_outside_the_pack(pack_io, rel):
    with pytest.raises(pack_io.PackError):
        pack_io.normalize_member(rel)


def test_output_path_never_overwrites(pack_io, tmp_path):
    src = tmp_path / "Song_Band.feedpak"
    src.write_bytes(b"")
    first = pack_io.output_path(src, "C# Standard")
    assert first.name == "Song_Band_Cs_Standard.feedpak"
    first.write_bytes(b"")
    pack_io.release_output(first)
    assert pack_io.output_path(src, "C# Standard").name == "Song_Band_Cs_Standard_2.feedpak"


def test_concurrent_reservations_get_different_names(pack_io, tmp_path):
    src = tmp_path / "Song.feedpak"
    src.write_bytes(b"")

    first = pack_io.output_path(src, "E Standard")
    second = pack_io.output_path(src, "E Standard")

    assert first != second
    assert not first.exists() and not second.exists()
    pack_io.release_output(first)
    pack_io.release_output(second)
    assert pack_io.output_path(src, "E Standard") == first
    pack_io.release_output(first)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Song.feedpak"]


def test_directory_pack_is_read(pack_io, tmp_path):
    d = tmp_path / "Song.feedpak"
    (d / "arrangements").mkdir(parents=True)
    (d / "manifest.yaml").write_text("title: T\nartist: A\narrangements: []\nstems: []\n")
    (d / "arrangements" / "lead.jsonc").write_text('{"tuning": [0,0,0,0,0,0], // x\n}')
    with pack_io.Pack(d) as pack:
        assert pack.manifest()["title"] == "T"
        assert pack.read_json("arrangements/lead.jsonc") == {"tuning": [0] * 6}
