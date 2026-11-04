"""Single-pass generation service. Job directories preserve all earlier results."""

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from local_subs.inference import POLICY, cache_key, load_model, resolve_language
from local_subs.media import extract_audio, inspect_media, milliseconds, select_track
from local_subs.subtitles import compose


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, default=str))


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(
    path,
    settings,
    audio_stream=None,
    start_ms=0,
    duration_ms=None,
    notify=lambda _: None,
    model_loader=load_model,
):
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps

    if start_ms < 0 or (duration_ms is not None and duration_ms <= 0):
        raise ValueError("Start must be nonnegative; duration must be positive")
    notify("Inspecting media")
    path = path.resolve()
    info = inspect_media(path)
    track = select_track(info, settings.source_language, audio_stream)
    source_duration = milliseconds(info["format"]["duration"])
    if start_ms >= source_duration:
        raise ValueError("Sample starts outside the playable media range")
    duration_ms = min(duration_ms or source_duration, source_duration - start_ms)
    job_id = uuid4().hex
    directory = settings.output_dir.resolve() / job_id
    directory.mkdir(parents=True)
    began = time.perf_counter()
    stat = path.stat()
    manifest = {
        "schema_version": 1,
        "pipeline_version": "phase1-v1",
        "job_id": job_id,
        "state": "preparing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "fingerprint_strategy": "sha256-full",
        },
        "audio_stream": track["index"],
        "source_duration_ms": source_duration,
        "format_start_time": info["format"].get("start_time"),
        "audio_start_time": track.get("start_time"),
        "video_start_times": [
            s.get("start_time") for s in info["streams"] if s["codec_type"] == "video"
        ],
        "sample_start_ms": start_ms,
        "sample_duration_ms": duration_ms,
        "settings": settings.model_dump(mode="json"),
        "requested_source_language": settings.source_language,
        "resolved_source_language": None,
        "target_language": "en",
        "versions": {p: version(p) for p in ("faster-whisper", "ctranslate2", "srt")},
        "warnings": [],
        "artifacts": {},
    }

    def save():
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest["elapsed_seconds"] = round(time.perf_counter() - began, 3)
        write_json(directory / "manifest.json", manifest)

    save()
    try:
        manifest["source"]["sha256"] = fingerprint(path)
        notify(
            f"Extracting global audio stream {track['index']}; sample retains movie offset {start_ms} ms"
        )
        extract_audio(path, track, info, directory / "audio.wav", start_ms, duration_ms)
        audio = decode_audio(str(directory / "audio.wav"), sampling_rate=16000)
        if not len(audio):
            raise ValueError("Selected range contains no decoded audio")
        playable_end = min(
            start_ms + milliseconds(len(audio) / 16000), start_ms + duration_ms
        )
        if settings.source_language != "auto" and not settings.vad:
            notify("VAD disabled for explicit language; processing original audio")
            speech = [{"start": 0, "end": len(audio)}] if audio.any() else []
        else:
            notify("Checking speech regions (Silero VAD); original timeline retained")
            speech = get_speech_timestamps(audio)
        raw, cues = [], []
        if not speech:
            manifest["state"] = "empty"
            manifest["warnings"].append(
                "No speech detected by VAD; empty subtitle output. This is a heuristic, not proof of silence."
            )
        else:
            model, runtime = model_loader(settings, notify)
            manifest.update(runtime)
            manifest["state"] = "processing"
            detection_key = cache_key(
                {
                    "source": manifest["source"]["sha256"],
                    "track": track["index"],
                    "start": start_ms,
                    "duration": duration_ms,
                    "settings": manifest["settings"],
                    "runtime": runtime,
                    "versions": manifest["versions"],
                    "policy": POLICY,
                }
            )
            cache_path = settings.output_dir / ".detection" / f"{detection_key}.json"
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = None
            language, diagnostics = resolve_language(
                model, audio, settings, start_ms, speech, cached
            )
            manifest["resolved_source_language"] = language
            manifest["language_detection"] = diagnostics
            write_json(cache_path, {"language": language, "diagnostics": diagnostics})
            task = "transcribe" if language == "en" else "translate"
            manifest["task"] = task
            manifest["configuration_hash"] = cache_key(
                {
                    "settings": manifest["settings"],
                    "runtime": runtime,
                    "resolved_language": language,
                    "task": task,
                }
            )
            save()
            notify(
                f"Resolved source language: {language}; task: {task}; English output"
            )
            segments, _ = model.transcribe(
                audio,
                language=language,
                task=task,
                vad_filter=settings.vad,
                beam_size=settings.beam_size,
            )
            for index, segment in enumerate(segments, 1):
                original = asdict(segment)
                start = start_ms + milliseconds(segment.start)
                end = start_ms + milliseconds(segment.end)
                identity = f"seg_{index:06d}"
                raw.append(
                    {
                        "id": identity,
                        "start_ms": start,
                        "end_ms": end,
                        "text": segment.text,
                        "source_chunk": "single",
                        "task": task,
                        "language": language,
                        "model_result": original,
                    }
                )
                write_json(directory / "raw_segments.json", raw)
                text = segment.text.strip()
                bounded_start, bounded_end = (
                    max(start_ms, start),
                    min(playable_end, end),
                )
                if text and bounded_start < bounded_end:
                    flags = (
                        ["clipped_to_playable_range"]
                        if (start, end) != (bounded_start, bounded_end)
                        else []
                    )
                    cues.append(
                        {
                            "id": f"cue_{index:06d}",
                            "source_segment_ids": [identity],
                            "start_ms": bounded_start,
                            "end_ms": bounded_end,
                            "text": text,
                            "flags": flags,
                            "edit_version": 0,
                            "origin": "model",
                        }
                    )
                else:
                    manifest["warnings"].append(
                        f"{identity}: empty text or nonpositive playable duration; raw result preserved"
                    )
                notify(
                    f"Processed movie position {end / 1000:.2f}s; elapsed {time.perf_counter() - began:.1f}s"
                )
            manifest["state"] = "exporting"
            save()
            manifest["state"] = "completed" if cues else "empty"
        write_json(directory / "raw_segments.json", raw)
        write_json(directory / "generated_cues.json", cues)
        atomic_text(directory / "subtitles.en.srt", compose(cues, playable_end))
        manifest["artifacts"] = {
            name: str(directory / name)
            for name in (
                "raw_segments.json",
                "generated_cues.json",
                "subtitles.en.srt",
                "audio.wav",
            )
        }
        manifest["cue_count"] = len(cues)
        save()
        notify(
            f"{manifest['state']}: {directory / 'subtitles.en.srt'} ({len(cues)} cues)"
        )
        for warning in manifest["warnings"]:
            notify(f"Warning: {warning}")
        return directory
    except BaseException as exc:
        if hasattr(exc, "diagnostics"):
            manifest["language_detection"] = exc.diagnostics
        manifest["failure_stage"] = manifest["state"]
        manifest["state"] = (
            "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        )
        manifest["error"] = str(exc)
        save()
        raise
