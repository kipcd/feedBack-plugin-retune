import array
import importlib.util
import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

PLUGIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_DIR))


def load_sibling(name):
    mod_name = f"retune_test_{name}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, PLUGIN_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def core():
    return load_sibling("retune_core")


@pytest.fixture
def pack_io():
    return load_sibling("pack_io")


def write_pack(path: Path, manifest: dict, files: dict[str, object]):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.yaml", yaml.safe_dump(manifest, sort_keys=False))
        for rel, content in files.items():
            if isinstance(content, (bytes, bytearray)):
                z.writestr(rel, content)
            else:
                z.writestr(rel, json.dumps(content))
    return path


def read_pack(path: Path):
    with zipfile.ZipFile(path) as z:
        manifest = yaml.safe_load(z.read("manifest.yaml"))
        files = {n: z.read(n) for n in z.namelist() if n != "manifest.yaml"}
    return manifest, files


def dominant_frequency(path: Path, lo: float, hi: float) -> float:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                          "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = array.array("h", raw)[2000:4000]
    best, best_f = 0.0, 0.0
    for f2 in range(int(lo * 2), int(hi * 2)):
        f = f2 / 2
        w = 2 * math.pi * f / 8000
        re_ = sum(s * math.cos(w * i) for i, s in enumerate(samples))
        im_ = sum(s * math.sin(w * i) for i, s in enumerate(samples))
        if re_ * re_ + im_ * im_ > best:
            best, best_f = re_ * re_ + im_ * im_, f
    return best_f


def ffprobe_codec(path: Path) -> str:
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                           "stream=codec_name", "-of", "default=nw=1:nk=1", str(path)],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def dlc_dir(tmp_path):
    d = tmp_path / "dlc"
    d.mkdir()
    return d


@pytest.fixture
def indexed():
    return []


@pytest.fixture
def client(dlc_dir, indexed):
    routes = load_sibling("routes")

    class FakeDb:
        def put(self, rel, mtime, size, meta):
            indexed.append((rel, meta))

    app = FastAPI()
    routes.setup(app, {
        "get_dlc_dir": lambda: str(dlc_dir),
        "load_sibling": load_sibling,
        "extract_meta": lambda p: {"title": p.name},
        "meta_db": FakeDb(),
    })
    with TestClient(app) as c:
        yield c
