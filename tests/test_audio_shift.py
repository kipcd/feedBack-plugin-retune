import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import dominant_frequency, ffprobe_codec, load_sibling

audio = load_sibling("audio_shift")
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg not installed")


def has_encoder(name: str) -> bool:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


def tone(path: Path, freq: float, rate: int, codec: list[str]):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration=1:sample_rate={rate}", *codec, str(path)], check=True)
    return path


def test_declared_codec_wins_over_extension():
    assert audio.encoder_attempts(Path("guitar.ogg"), "opus")[0][:2] == ["-c:a", "libopus"]
    assert audio.encoder_attempts(Path("full.wav"), "mp3")[0][:2] == ["-c:a", "libmp3lame"]
    assert audio.encoder_attempts(Path("full.ogg"), None)[0][:2] == ["-c:a", "libvorbis"]
    assert audio.encoder_attempts(Path("full.wav"), None)[0][:2] == ["-c:a", "pcm_s16le"]


def test_unknown_declared_codec_is_an_error():
    with pytest.raises(audio.AudioError, match="wem"):
        audio.encoder_attempts(Path("full.ogg"), "wem")


def test_fallback_chain_does_not_depend_on_the_input_rate(monkeypatch):
    monkeypatch.setattr(audio, "has_rubberband", lambda ffmpeg: False)
    chain = audio.filter_chain("ffmpeg", 1)
    assert chain.startswith("aresample=48000,asetrate=")


@needs_ffmpeg
def test_fallback_shift_is_in_tune_for_48k_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(audio, "has_rubberband", lambda ffmpeg: False)
    src = tone(tmp_path / "in.wav", 311.13, 48000, ["-c:a", "pcm_s16le"])
    dst = tmp_path / "out.wav"

    assert audio.shift_file("ffmpeg", src, dst, 1) == "resample"

    assert dominant_frequency(dst, 300, 360) == pytest.approx(329.63, rel=0.01)
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "default=nw=1:nk=1", str(dst)],
                                    capture_output=True, text=True, check=True).stdout)
    assert duration == pytest.approx(1.0, abs=0.05)


@needs_ffmpeg
def test_opus_in_ogg_stays_opus(tmp_path):
    if not has_encoder("libopus"):
        pytest.skip("ffmpeg has no libopus")
    src = tone(tmp_path / "in.ogg", 440, 48000, ["-c:a", "libopus"])
    dst = tmp_path / "out.ogg"

    audio.shift_file("ffmpeg", src, dst, 1, "opus")

    assert ffprobe_codec(dst) == "opus"


def test_declared_codec_picks_its_container_when_the_extension_disagrees():
    assert audio.encoder_attempts(Path("full.wav"), "mp3")[0][-2:] == ["-f", "mp3"]
    assert audio.encoder_attempts(Path("full.wav"), "opus")[0][-2:] == ["-f", "ogg"]
    assert "-f" not in audio.encoder_attempts(Path("full.ogg"), "vorbis")[0]
    assert "-f" not in audio.encoder_attempts(Path("full.mp3"), "mp3")[0]


@needs_ffmpeg
def test_mp3_declared_in_a_wav_name_is_written_as_plain_mp3(tmp_path):
    if not has_encoder("libmp3lame"):
        pytest.skip("ffmpeg has no libmp3lame")
    src = tone(tmp_path / "in.wav", 440, 44100, ["-c:a", "pcm_s16le"])
    dst = tmp_path / "full.wav"

    audio.shift_file("ffmpeg", src, dst, 1, "mp3")

    assert not dst.read_bytes().startswith(b"RIFF")
    fmt = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name",
                          "-of", "default=nw=1:nk=1", str(dst)], capture_output=True, text=True, check=True)
    assert fmt.stdout.strip() == "mp3"
    assert ffprobe_codec(dst) == "mp3"
