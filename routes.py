from __future__ import annotations

import asyncio
import copy
import logging
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

_ctx: dict = {}
_log = logging.getLogger("feedBack.plugin.retune")
core = None
pack_io = None
audio = None


def setup(app, context):
    global core, pack_io, audio, _log
    _ctx.clear()
    _ctx.update(context)
    _log = context.get("log") or _log
    core = context["load_sibling"]("retune_core")
    pack_io = context["load_sibling"]("pack_io")
    audio = context["load_sibling"]("audio_shift")

    @app.get("/api/plugins/retune/options")
    def options(filename: str):
        path = _resolve(filename)
        try:
            with pack_io.Pack(path) as pack:
                manifest = pack.manifest()
                files = pack_io.load_json_files(pack, pack_io.chart_files(manifest))
            return _options(manifest, files)
        except (pack_io.PackError, core.RetuneError) as e:
            raise HTTPException(400, str(e)) from e

    @app.websocket("/ws/plugins/retune/run")
    async def run(websocket: WebSocket, filename: str, shift: int = 0, low_adjust: int = 0):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(msg: dict):
            loop.call_soon_threadsafe(queue.put_nowait, msg)

        def job():
            try:
                emit({"done": True, "progress": 100, **_retune(filename, shift, low_adjust, emit)})
            except HTTPException as e:
                emit({"error": e.detail})
            except (core.RetuneError, pack_io.PackError, audio.AudioError) as e:
                emit({"error": str(e)})
            except Exception as e:
                _log.exception("retune failed for %r", filename)
                emit({"error": f"Retune failed: {e}"})

        threading.Thread(target=job, name="retune-job", daemon=True).start()
        try:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)
                if msg.get("done") or msg.get("error"):
                    break
            await websocket.close()
        except WebSocketDisconnect:
            pass


def _dlc_dir() -> Path:
    getter = _ctx.get("get_dlc_dir")
    dlc = getter() if callable(getter) else None
    if not dlc:
        raise HTTPException(400, "Song library folder is not configured")
    return Path(dlc).resolve()


def _resolve(filename: str) -> Path:
    dlc = _dlc_dir()
    try:
        path = (dlc / filename).resolve()
        path.relative_to(dlc)
    except (ValueError, OSError) as e:
        raise HTTPException(400, "Invalid song path") from e
    if not path.exists():
        raise HTTPException(404, "Song not found")
    if not (path.is_dir() or path.suffix.lower() in pack_io.PACK_EXTS):
        raise HTTPException(400, "Only feedpak songs can be retuned")
    return path


def _options(manifest: dict, files: dict) -> dict:
    ref = core.reference_entry(manifest, files)
    if ref is None:
        raise HTTPException(400, "This song has no fretted arrangement to retune")
    ref_src, ref_std = core.reference_tuning(ref, files)
    chart_by_adjust = {}
    targets = core.list_targets(ref_src, ref_std)
    for adjust in {t["low_adjust"] for t in targets if t["low_adjust"]}:
        report = core.retune_pack(copy.deepcopy(manifest), copy.deepcopy(files), 0, adjust)
        chart_by_adjust[adjust] = report["chart"]
    ffmpeg = audio.find_ffmpeg()
    return {
        "title": manifest.get("title", ""),
        "artist": manifest.get("artist", ""),
        "source": {"name": core.tuning_name(ref_src, ref_std), "offsets": ref_src},
        "ffmpeg": bool(ffmpeg),
        "rubberband": bool(ffmpeg) and audio.has_rubberband(ffmpeg),
        "targets": [{**t, "chart": chart_by_adjust.get(t["low_adjust"])} for t in targets],
    }


def _retune(filename: str, shift: int, low_adjust: int, emit) -> dict:
    path = _resolve(filename)
    emit({"stage": "Reading pack…", "progress": 2})
    with pack_io.Pack(path) as pack, tempfile.TemporaryDirectory(prefix="retune-") as tmp:
        manifest = pack.manifest()
        side = [manifest[k] for k in core.SIDE_FILE_TRANSFORMS if isinstance(manifest.get(k), str)]
        files = pack_io.load_json_files(pack, pack_io.chart_files(manifest))
        files.update(pack_io.load_json_files(pack, side, required=False))

        emit({"stage": "Rewriting charts…", "progress": 5})
        report = core.retune_pack(manifest, files, shift, low_adjust)

        replacements: dict = {pack.manifest_name: pack_io.dump_manifest(manifest)}
        replacements.update({rel: pack_io.dump_json(doc) for rel, doc in files.items()})

        out_path = pack_io.output_path(path, report["to"])
        try:
            method = _shift_audio(pack, manifest, shift, Path(tmp), replacements, emit) if shift else None
            emit({"stage": "Writing new pack…", "progress": 92})
            pack_io.write_pack(pack, out_path, replacements)
        finally:
            pack_io.release_output(out_path)

    rel_name = out_path.relative_to(_dlc_dir()).as_posix()
    _index(out_path, rel_name)
    return {
        "stage": "Done",
        "filename": rel_name,
        "title": manifest.get("title", ""),
        "audio_method": method,
        "report": report,
    }


def _shift_audio(pack, manifest: dict, shift: int, tmp: Path, replacements: dict, emit) -> str | None:
    stems = {}
    stem_files = {s.get("file") for s in manifest.get("stems") or [] if isinstance(s, dict)}
    for rel, codec in pack_io.audio_files(manifest).items():
        if pack.has(rel):
            stems[rel] = codec
        elif rel in stem_files:
            raise pack_io.PackError(f"Audio file {rel} is listed in the manifest but missing from the pack")
    ffmpeg = audio.find_ffmpeg()
    if not ffmpeg:
        raise audio.AudioError("ffmpeg was not found, so the audio can't be pitch-shifted")
    emit({"stage": f"Pitch-shifting {len(stems)} audio file(s)…", "progress": 10})
    jobs = {}
    for rel, codec in stems.items():
        dst = tmp / "out" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        jobs[rel] = (pack.extract(rel, tmp / "in" / rel), dst, codec)
    method = None
    done = 0
    workers = max(1, min(len(stems), os.cpu_count() or 2, 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(audio.shift_file, ffmpeg, src, dst, shift, codec): rel
            for rel, (src, dst, codec) in jobs.items()
        }
        for future in as_completed(futures):
            rel = futures[future]
            method = future.result()
            replacements[rel] = jobs[rel][1]
            done += 1
            emit({"stage": f"Shifted {rel}", "progress": 10 + int(80 * done / len(stems))})
    return method


def _index(out_path: Path, rel_name: str):
    extract_meta, meta_db = _ctx.get("extract_meta"), _ctx.get("meta_db")
    if not (callable(extract_meta) and meta_db is not None):
        return
    try:
        stat = out_path.stat()
        meta_db.put(rel_name, stat.st_mtime, stat.st_size, extract_meta(out_path))
    except Exception:
        _log.warning("library indexing failed for %r", rel_name, exc_info=True)
