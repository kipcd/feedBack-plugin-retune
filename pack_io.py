from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import yaml

PACK_EXTS = (".feedpak", ".sloppak")
MANIFEST_NAMES = ("manifest.yaml", "manifest.yml")
LEGACY_FULL_MIX = "original_audio"
REWRITTEN_KEYS = ("preview", LEGACY_FULL_MIX, "vocal_pitch", "vocal_pitch_contour", "keys", "harmony")
STORED_EXTS = (".ogg", ".opus", ".mp3", ".m4a", ".aac", ".flac", ".png", ".jpg", ".jpeg", ".webp")


class PackError(ValueError):
    pass


def normalize_member(rel: str) -> str:
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        raise PackError(f"Invalid path in pack: {rel!r}")
    norm = posixpath.normpath(rel.replace("\\", "/"))
    if norm.startswith(("/", "../")) or norm in ("..", ".") or re.match(r"^[A-Za-z]:", norm):
        raise PackError(f"Path escapes the pack: {rel!r}")
    return norm


def _stored_key(name: str) -> str | None:
    try:
        return normalize_member(name)
    except PackError:
        return None


def strip_jsonc(text: str) -> str:
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    out = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
            out.append(c)
        elif c == ",":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j >= n or text[j] not in "}]":
                out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _decode(data: bytes, rel: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise PackError(f"{rel} is not UTF-8 text") from e


def parse_json(data: bytes, rel: str):
    text = _decode(data, rel)
    if rel.endswith(".jsonc"):
        text = strip_jsonc(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise PackError(f"{rel} is not valid JSON: {e}") from e


class Pack:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._sources: dict[str, str | Path] = {}
        if self.path.is_dir():
            self._zip = None
            root = self.path.resolve()
            for p in sorted(self.path.rglob("*")):
                target = p.resolve()
                if not target.is_file() or not target.is_relative_to(root):
                    continue
                raw = p.relative_to(self.path).as_posix()
                key = _stored_key(raw)
                if key is not None and (key not in self._sources or raw == key):
                    self._sources[key] = target
        elif zipfile.is_zipfile(self.path):
            self._zip = zipfile.ZipFile(self.path)
            for info in self._zip.infolist():
                key = None if info.is_dir() else _stored_key(info.filename)
                if key is not None:
                    self._sources[key] = info.filename
        else:
            raise PackError(f"{self.path.name} is not a feedpak (zip or folder)")
        self._members = list(self._sources)
        self.manifest_name = next((m for m in MANIFEST_NAMES if m in self._sources), None)
        if self.manifest_name is None:
            raise PackError("manifest.yaml not found at the root of the pack")

    def close(self):
        if self._zip is not None:
            self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def members(self) -> list[str]:
        return list(self._members)

    def has(self, rel: str) -> bool:
        return normalize_member(rel) in self._sources

    def _source(self, rel: str) -> str | Path:
        key = normalize_member(rel)
        if key not in self._sources:
            raise PackError(f"{key} is listed in the manifest but missing from the pack")
        return self._sources[key]

    def read_bytes(self, rel: str) -> bytes:
        with self.open(rel) as f:
            return f.read()

    def open(self, rel: str):
        source = self._source(rel)
        if self._zip is not None:
            return self._zip.open(source)
        return open(source, "rb")

    def extract(self, rel: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.open(rel) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
        return dest

    def manifest(self) -> dict:
        try:
            data = yaml.safe_load(_decode(self.read_bytes(self.manifest_name), self.manifest_name))
        except yaml.YAMLError as e:
            raise PackError(f"{self.manifest_name} is not valid YAML: {e}") from e
        if not isinstance(data, dict):
            raise PackError("manifest.yaml must contain a mapping")
        normalize_manifest_paths(data)
        return data

    def read_json(self, rel: str):
        return parse_json(self.read_bytes(rel), rel)


def normalize_manifest_paths(manifest: dict):
    for key in REWRITTEN_KEYS:
        if isinstance(manifest.get(key), str):
            manifest[key] = normalize_member(manifest[key])
    for listing, fields in (("arrangements", ("file", "notation")), ("stems", ("file",))):
        for entry in manifest.get(listing) or []:
            if not isinstance(entry, dict):
                continue
            for field in fields:
                if isinstance(entry.get(field), str):
                    entry[field] = normalize_member(entry[field])


def chart_files(manifest: dict) -> list[str]:
    paths = []
    for entry in manifest.get("arrangements") or []:
        for key in ("file", "notation"):
            if isinstance(entry.get(key), str):
                paths.append(entry[key])
    return paths


def audio_files(manifest: dict) -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for stem in manifest.get("stems") or []:
        if isinstance(stem, dict) and isinstance(stem.get("file"), str):
            files.setdefault(stem["file"], stem.get("codec") if isinstance(stem.get("codec"), str) else None)
    for key in ("preview", LEGACY_FULL_MIX):
        if isinstance(manifest.get(key), str):
            files.setdefault(manifest[key], None)
    return files


def load_json_files(pack: Pack, rels: list[str], required: bool = True) -> dict[str, dict]:
    files = {}
    for rel in rels:
        if required or pack.has(rel):
            files[rel] = pack.read_json(rel)
    return files


def dump_manifest(manifest: dict) -> bytes:
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).encode("utf-8")


def dump_json(doc) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def write_pack(pack: Pack, out_path: Path, replacements: dict[str, bytes | Path]):
    fd, tmp_name = tempfile.mkstemp(prefix=f".{out_path.name}.", suffix=".part", dir=out_path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    os.chmod(tmp, pack.path.stat().st_mode & 0o666 if pack.path.is_file() else 0o644)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for rel in pack.members:
                compress = zipfile.ZIP_STORED if rel.lower().endswith(STORED_EXTS) else zipfile.ZIP_DEFLATED
                replacement = replacements.get(rel)
                if isinstance(replacement, Path):
                    out.write(replacement, rel, compress_type=compress)
                elif replacement is not None:
                    out.writestr(rel, replacement, compress_type=compress)
                else:
                    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = compress
                    with pack.open(rel) as src, out.open(info, "w", force_zip64=True) as dst:
                        shutil.copyfileobj(src, dst)
        tmp.replace(out_path)
    finally:
        tmp.unlink(missing_ok=True)


def output_path(source: Path, target_name: str) -> Path:
    stem = source.name
    for ext in PACK_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    suffix = re.sub(r"[^A-Za-z0-9#]+", "_", target_name).strip("_").replace("#", "s")
    base = f"{stem}_{suffix}"
    n = 1
    while True:
        candidate = source.with_name(f"{base}.feedpak" if n == 1 else f"{base}_{n}.feedpak")
        n += 1
        if candidate.exists():
            continue
        try:
            _lock_for(candidate).open("x").close()
        except FileExistsError:
            continue
        if candidate.exists():
            release_output(candidate)
            continue
        return candidate


def _lock_for(candidate: Path) -> Path:
    return candidate.with_name(f".{candidate.name}.lock")


def release_output(candidate: Path):
    _lock_for(candidate).unlink(missing_ok=True)
