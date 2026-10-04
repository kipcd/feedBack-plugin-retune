from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

FALLBACK_RATE = 48000

CODEC_ENCODERS = {
    "vorbis": [["-c:a", "libvorbis", "-q:a", "5"], ["-c:a", "vorbis", "-strict", "experimental", "-q:a", "5"]],
    "opus": [["-c:a", "libopus", "-b:a", "160k"]],
    "mp3": [["-c:a", "libmp3lame", "-q:a", "2"]],
    "aac": [["-c:a", "aac", "-b:a", "256k"]],
    "flac": [["-c:a", "flac"]],
    "pcm": [["-c:a", "pcm_s16le"]],
}
CODEC_MUXERS = {
    "vorbis": "ogg",
    "opus": "ogg",
    "mp3": "mp3",
    "aac": "adts",
    "flac": "flac",
    "pcm": "wav",
}
CODEC_ALIASES = {"ogg": "vorbis", "wav": "pcm", "pcm_s16le": "pcm", "mpeg": "mp3"}
EXTENSION_CODECS = {
    ".ogg": "vorbis",
    ".opus": "opus",
    ".wav": "pcm",
    ".mp3": "mp3",
    ".flac": "flac",
    ".m4a": "aac",
    ".aac": "aac",
}


class AudioError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    try:
        from audio import _ffmpeg_cmd  # noqa: PLC0415

        found = _ffmpeg_cmd()
        if found:
            return found
    except Exception:
        pass
    return shutil.which("ffmpeg")


@functools.lru_cache(maxsize=4)
def has_rubberband(ffmpeg: str) -> bool:
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[1:2] == ["rubberband"] for line in r.stdout.splitlines() if line.strip())


def encoder_attempts(path: Path, codec: str | None = None) -> list[list[str]]:
    if codec:
        name = CODEC_ALIASES.get(codec.lower(), codec.lower())
        if name not in CODEC_ENCODERS:
            raise AudioError(f"{path.name} declares codec {codec!r}, which the plugin can't re-encode")
        if EXTENSION_CODECS.get(path.suffix.lower()) == name:
            return CODEC_ENCODERS[name]
        return [[*encoder, "-f", CODEC_MUXERS[name]] for encoder in CODEC_ENCODERS[name]]
    name = EXTENSION_CODECS.get(path.suffix.lower())
    return CODEC_ENCODERS[name] if name else [[]]


def filter_chain(ffmpeg: str, shift: int) -> str:
    ratio = 2 ** (shift / 12)
    if has_rubberband(ffmpeg):
        return f"rubberband=pitch={ratio:.10f}:pitchq=quality:transients=mixed"
    return (f"aresample={FALLBACK_RATE},asetrate={FALLBACK_RATE * ratio:.4f},"
            f"aresample={FALLBACK_RATE},atempo={1 / ratio:.10f}")


def shift_file(ffmpeg: str, src: Path, dst: Path, shift: int, codec: str | None = None) -> str:
    chain = filter_chain(ffmpeg, shift)
    last = "ffmpeg failed"
    for encoder in encoder_attempts(dst, codec):
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-y", "-i", str(src), "-map", "0:a:0", "-af", chain,
             *encoder, "-map_metadata", "0", str(dst)],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return "rubberband" if chain.startswith("rubberband") else "resample"
        lines = (r.stderr or "").strip().splitlines()
        if lines:
            last = lines[-1]
    raise AudioError(f"ffmpeg could not shift {src.name}: {last}")
