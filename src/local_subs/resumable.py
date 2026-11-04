"""Chunk-level checkpointing; immutable result files and export revisions."""

import errno
import json
import os
import shutil
import time
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from local_subs.chunks import plan_chunks, read_audio, stitch, wav_info
from local_subs.config import Settings
from local_subs.inference import POLICY, cache_key, load_model, resolve_language
from local_subs.jobs import atomic_text, fingerprint, write_json
from local_subs.media import extract_audio, inspect_media, milliseconds, select_track
from local_subs.subtitles import compose
from local_subs.worker import active_worker, worker_lock

PIPELINE = "chunked-v1"


class Cancelled(Exception):
    pass


def job_directory(root, job_id):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Invalid job ID; use jobs list")
    directory = root.resolve() / job_id
    if not (directory / "manifest.json").is_file():
        raise ValueError("Job not found in this output directory")
    return directory


def read_manifest(directory):
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def generate(
    path,
    settings,
    audio_stream=None,
    start_ms=0,
    duration_ms=None,
    notify=lambda _: None,
    model_loader=load_model,
):
    if start_ms < 0 or (duration_ms is not None and duration_ms <= 0):
        raise ValueError("Start must be nonnegative and duration positive")
    path = path.resolve()
    info = inspect_media(path)
    track = select_track(info, settings.source_language, audio_stream)
    total = milliseconds(info["format"]["duration"])
    if start_ms >= total:
        raise ValueError("Sample starts outside media")
    directory = settings.output_dir.resolve() / uuid4().hex
    directory.mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "job_id": directory.name,
        "state": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(path),
        "audio_stream": track["index"],
        "sample_start_ms": start_ms,
        "sample_duration_ms": min(duration_ms or total, total - start_ms),
        "source_duration_ms": total,
        "settings": settings.model_dump(mode="json"),
        "chunks": [],
        "attempts": 0,
        "elapsed_seconds": 0,
        "artifacts": {},
    }
    write_json(directory / "manifest.json", manifest)
    notify(
        f'Created job {directory.name}; resume with local-subs resume {directory.name} --output-dir "{settings.output_dir}"'
    )
    return run(directory, manifest, settings, notify, model_loader)


def resume(
    job_id,
    root,
    overrides=None,
    audio_stream=None,
    notify=lambda _: None,
    model_loader=load_model,
):
    directory = job_directory(root, job_id)
    manifest = read_manifest(directory)
    if manifest.get("schema_version") != 2:
        raise ValueError("This is a Phase 1 job; generate a new chunked job instead")
    data = manifest["settings"] | {
        k: v for k, v in (overrides or {}).items() if v is not None
    }
    data["output_dir"] = str(root.resolve())
    settings = Settings.model_validate(data)
    if audio_stream is not None:
        manifest["audio_stream"] = audio_stream
    return run(directory, manifest, settings, notify, model_loader)


def run(directory, manifest, settings, notify, model_loader):
    from faster_whisper.vad import get_speech_timestamps

    with worker_lock(directory.parent, directory.name):
        write_json(
            directory / "attempts" / f"{uuid4().hex}.json", read_manifest(directory)
        )
        request = directory / "cancel.request"
        request.unlink(missing_ok=True)
        began, previous_elapsed = (
            time.perf_counter(),
            manifest.get("elapsed_seconds", 0),
        )

        model = None

        def save():
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            manifest["elapsed_seconds"] = round(
                previous_elapsed + time.perf_counter() - began, 3
            )
            write_json(directory / "manifest.json", manifest)

        def check_cancel():
            if request.exists():
                raise Cancelled("Cancellation requested; completed chunks preserved")

        manifest["attempts"] += 1
        manifest["state"] = "preparing"
        manifest["stage"] = "inspect"
        manifest["settings"] = settings.model_dump(mode="json")
        manifest.pop("error", None)
        manifest.pop("failure_stage", None)
        save()
        try:
            source = Path(manifest["source_path"])
            info = inspect_media(source)
            track = select_track(
                info, settings.source_language, manifest["audio_stream"]
            )
            stat = source.stat()
            manifest["stage"] = "fingerprint"
            digest = fingerprint(source)
            manifest["source"] = {
                "path": str(source),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": digest,
                "fingerprint_strategy": "sha256-full",
            }
            manifest["format_start_time"] = info["format"].get("start_time")
            manifest["audio_start_time"] = track.get("start_time")
            manifest["video_start_times"] = [
                s.get("start_time")
                for s in info["streams"]
                if s["codec_type"] == "video"
            ]
            start, duration = (
                manifest["sample_start_ms"],
                manifest["sample_duration_ms"],
            )
            extraction_key = cache_key(
                {
                    "source": digest,
                    "track": track["index"],
                    "start": start,
                    "duration": duration,
                    "timeline": "container-relative-v1",
                }
            )
            audio_path = directory / f"audio-{extraction_key}.wav"
            manifest["stage"] = "extraction"
            save()
            cached_audio = manifest.get("prepared_audio", {})
            usable = (
                audio_path.is_file()
                and cached_audio.get("key") == extraction_key
                and fingerprint(audio_path) == cached_audio.get("sha256")
            )
            if not usable:
                check_cancel()
                needed = duration * 32 + 64 * 1024 * 1024
                if shutil.disk_usage(directory).free < needed:
                    raise OSError(
                        errno.ENOSPC,
                        f"Need at least {needed // (1024 * 1024)} MiB free for prepared audio and working space",
                    )
                temporary = directory / f"audio-{uuid4().hex}.part.wav"
                try:
                    notify(
                        "Extracting selected track to disk (no full audio array in memory)"
                    )
                    extract_audio(source, track, info, temporary, start, duration)
                    wav_info(temporary)
                    os.replace(temporary, audio_path)
                finally:
                    temporary.unlink(missing_ok=True)
                manifest["prepared_audio"] = {
                    "key": extraction_key,
                    "path": str(audio_path),
                    "sha256": fingerprint(audio_path),
                }
            else:
                notify("Reusing verified prepared audio")
            end = start + min(duration, wav_info(audio_path))
            if end <= start:
                raise ValueError("Selected range contains no decoded audio")
            plan_key = cache_key(
                {
                    "extraction": extraction_key,
                    "end": end,
                    "chunk": settings.chunk_seconds,
                    "overlap": settings.overlap_seconds,
                    "pipeline": PIPELINE,
                }
            )
            if manifest.get("plan_key") != plan_key:
                manifest["chunks"] = plan_chunks(
                    audio_path,
                    start,
                    end,
                    settings.chunk_seconds * 1000,
                    settings.overlap_seconds * 1000,
                )
                manifest["plan_key"] = plan_key
            manifest["pipeline_version"] = PIPELINE
            manifest["versions"] = {
                p: version(p) for p in ("faster-whisper", "ctranslate2", "srt")
            }
            inference_settings = {
                k: v
                for k, v in settings.model_dump(mode="json").items()
                if k
                not in ("output_dir", "chunk_seconds", "overlap_seconds", "model_cache")
            }
            resolution_key = cache_key(
                {
                    "extraction": extraction_key,
                    "settings": inference_settings,
                    "versions": manifest["versions"],
                    "policy": POLICY,
                }
            )
            if manifest.get("resolution_key") != resolution_key:
                manifest["resolved_source_language"] = None
                manifest.pop("language_detection", None)
            manifest["requested_source_language"] = settings.source_language
            manifest["target_language"] = "en"
            model, runtime = None, None
            results = []
            manifest["state"], manifest["stage"] = "processing", "chunks"
            save()
            for index, chunk in enumerate(manifest["chunks"]):
                check_cancel()
                audio = read_audio(
                    audio_path,
                    chunk["context_start_ms"] - start,
                    chunk["context_end_ms"] - start,
                )
                speech = (
                    get_speech_timestamps(audio)
                    if settings.vad or settings.source_language == "auto"
                    else ([{"start": 0, "end": len(audio)}] if audio.any() else [])
                )
                if speech and model is None:
                    manifest["stage"] = "model_loading"
                    save()
                    model, runtime = model_loader(settings, notify)
                    # A different snapshot invalidates language resolution and inference.
                    if manifest.get("runtime") != runtime:
                        manifest["resolved_source_language"] = None
                    manifest["runtime"] = runtime
                    manifest["stage"] = "chunks"
                if speech and not manifest.get("resolved_source_language"):
                    language, diagnostics = resolve_language(
                        model, audio, settings, chunk["context_start_ms"], speech
                    )
                    manifest["resolved_source_language"] = language
                    manifest["language_detection"] = diagnostics
                    manifest["resolution_key"] = resolution_key
                    notify(f"Resolved language once for job: {language}")
                    save()
                language = manifest.get("resolved_source_language")
                key = cache_key(
                    {
                        "extraction": extraction_key,
                        "chunk": {
                            k: v
                            for k, v in chunk.items()
                            if k
                            in (
                                "id",
                                "owner_start_ms",
                                "owner_end_ms",
                                "context_start_ms",
                                "context_end_ms",
                            )
                        },
                        "language": language if speech else None,
                        "settings": inference_settings if speech else "silence-v1",
                        "runtime": runtime if speech else None,
                        "versions": manifest["versions"],
                        "pipeline": PIPELINE,
                    }
                )
                checkpoint = directory / "chunks" / f"{chunk['id']}-{key}.json"
                segments = None
                if chunk.get("key") == key and checkpoint.is_file():
                    try:
                        if fingerprint(checkpoint) == chunk.get("sha256"):
                            segments = json.loads(
                                checkpoint.read_text(encoding="utf-8")
                            )["segments"]
                    except (OSError, ValueError, KeyError):
                        pass
                if segments is not None:
                    notify(f"Reusing completed {chunk['id']}")
                else:
                    segments = []
                    chunk["state"] = "processing"
                    save()
                    if speech:
                        task = "transcribe" if language == "en" else "translate"
                        manifest["task"] = task
                        iterator, _ = model.transcribe(
                            audio,
                            language=language,
                            task=task,
                            vad_filter=settings.vad,
                            beam_size=settings.beam_size,
                        )
                        for number, segment in enumerate(iterator):
                            check_cancel()
                            segments.append(
                                {
                                    "id": f"{chunk['id']}_seg_{number:06d}",
                                    "start_ms": chunk["context_start_ms"]
                                    + milliseconds(segment.start),
                                    "end_ms": chunk["context_start_ms"]
                                    + milliseconds(segment.end),
                                    "text": segment.text,
                                    "source_chunk": chunk["id"],
                                    "language": language,
                                    "task": task,
                                    "model_result": asdict(segment),
                                }
                            )
                    write_json(checkpoint, {"key": key, "segments": segments})
                    chunk.update(
                        key=key,
                        state="completed",
                        path=str(checkpoint),
                        sha256=fingerprint(checkpoint),
                    )
                    save()
                    notify(
                        f"Checkpointed {chunk['id']} ({index + 1}/{len(manifest['chunks'])}); movie position {chunk['owner_end_ms'] / 1000:.1f}s"
                    )
                results.append(segments)
                del audio
                check_cancel()
            manifest["state"], manifest["stage"] = "exporting", "stitch"
            save()
            raw, cues, report = stitch(manifest["chunks"], results, start, end)
            revision = directory / "exports" / uuid4().hex
            revision.mkdir(parents=True)
            for name, data in [
                ("raw_segments.json", raw),
                ("generated_cues.json", cues),
                ("boundaries.json", report),
            ]:
                write_json(revision / name, data)
            atomic_text(revision / "subtitles.en.srt", compose(cues, end))
            manifest["artifacts"] = {
                name: str(revision / name)
                for name in (
                    "raw_segments.json",
                    "generated_cues.json",
                    "boundaries.json",
                    "subtitles.en.srt",
                )
            }
            manifest["cue_count"] = len(cues)
            manifest["result"] = "subtitles" if cues else "empty"
            manifest["state"], manifest["stage"] = "completed", "done"
            save()
            write_json(revision / "manifest.json", manifest)
            notify(
                f"Completed: {revision / 'subtitles.en.srt'}; {len(cues)} cues; inspect boundaries.json for uncertain boundaries"
            )
            return directory
        except BaseException as exc:
            manifest["failure_stage"] = manifest.get("stage")
            manifest["state"] = (
                "cancelled"
                if isinstance(exc, (Cancelled, KeyboardInterrupt))
                else "failed"
            )
            if hasattr(exc, "diagnostics"):
                manifest["language_detection"] = exc.diagnostics
            hint = "Fix the error and resume; completed matching chunks are preserved. No automatic retries."
            if manifest["state"] == "cancelled":
                hint = "Resume when ready; completed matching chunks are preserved. The unfinished chunk restarts."
            if isinstance(exc, MemoryError) or "out of memory" in str(exc).lower():
                hint = "Use a smaller model or shorter chunks; changing model settings invalidates inference checkpoints."
            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                hint = "Free disk space before resuming; existing completed checkpoints are retained."
            manifest["error"] = {
                "message": str(exc),
                "type": type(exc).__name__,
                "retry_hint": hint,
            }
            try:
                save()
            except OSError:
                notify(
                    "Could not persist failure state; last durable manifest and checkpoints remain available"
                )
            notify(f"{manifest['state']}: {hint}")
            raise
        finally:
            model = None


def cancel(job_id, root):
    directory = job_directory(root, job_id)
    manifest = read_manifest(directory)
    if manifest["state"] == "completed":
        raise ValueError("Job has already completed")
    atomic_text(directory / "cancel.request", "cancel")
    active = active_worker(root)
    if not active or active["job_id"] != job_id:
        manifest["state"] = "cancelled"
        write_json(directory / "manifest.json", manifest)
    return "Cancellation requested. Active inference stops at the next segment/checkpoint; extraction stops after FFmpeg finishes."


def cleanup(job_id, root):
    directory = job_directory(root, job_id)
    active = active_worker(root)
    if active and active["job_id"] == job_id:
        raise ValueError(
            "Cannot clean up an active job; cancel it and wait for it to stop"
        )
    with worker_lock(root, job_id):
        removed = 0
        for path in directory.glob("audio-*.wav"):
            if path.resolve().parent != directory.resolve():
                raise ValueError("Refusing cleanup outside job directory")
            removed += path.stat().st_size
            path.unlink()
        return removed
