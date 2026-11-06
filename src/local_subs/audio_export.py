"""Standalone, model-free audio exports with portable movie-timing metadata."""

import errno
import shutil
import time
import zipfile
from pathlib import Path
from uuid import uuid4

from local_subs.jobs import fingerprint, write_json
from local_subs.media import extract_audio, inspect_media, milliseconds, select_track


def export_audio(
    path,
    output_root,
    audio_stream=None,
    start_ms=0,
    duration_ms=None,
    audio_format="flac",
):
    if audio_format not in ("flac", "wav"):
        raise ValueError("Audio format must be flac or wav")
    if start_ms < 0 or (duration_ms is not None and duration_ms <= 0):
        raise ValueError("Start must be nonnegative and duration positive")
    path = Path(path).resolve()
    info = inspect_media(path)
    track = select_track(info, "auto", audio_stream)
    total_ms = milliseconds(info["format"]["duration"])
    if start_ms >= total_ms:
        raise ValueError("Sample starts outside media")
    duration_ms = min(duration_ms or total_ms, total_ms - start_ms)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    # Worst-case PCM payload plus a copy in the downloadable ZIP and working room.
    needed = duration_ms * 32 * 2 + 64 * 1024 * 1024
    if shutil.disk_usage(output_root).free < needed:
        raise OSError(
            errno.ENOSPC,
            f"Need at least {needed // (1024 * 1024)} MiB free for this audio export and ZIP",
        )
    directory = output_root / uuid4().hex
    directory.mkdir()
    began = time.perf_counter()
    temporary = directory / f"audio.part.{audio_format}"
    try:
        extract_audio(
            path,
            track,
            info,
            temporary,
            start_ms,
            duration_ms,
            codec="flac" if audio_format == "flac" else "pcm_s16le",
        )
        exported = inspect_media(temporary)
        stream = next(s for s in exported["streams"] if s["codec_type"] == "audio")
        actual_ms = milliseconds(exported["format"]["duration"])
        if (
            actual_ms <= 0
            or int(stream["sample_rate"]) != 16000
            or stream["channels"] != 1
        ):
            raise ValueError("Export did not produce nonempty 16 kHz mono audio")
        audio_path = directory / f"audio.{audio_format}"
        temporary.rename(audio_path)
        metadata = {
            "schema_version": 1,
            "export_id": directory.name,
            "audio_file": audio_path.name,
            "source_name": path.name,
            "audio_stream": track["index"],
            "timeline_offset_ms": start_ms,
            "requested_duration_ms": duration_ms,
            "audio_duration_ms": actual_ms,
            "source_duration_ms": total_ms,
            "sample_rate": 16000,
            "channels": 1,
            "audio_format": audio_format,
            "audio_sha256": fingerprint(audio_path),
            "extraction_seconds": round(time.perf_counter() - began, 3),
            "timing_note": "Audio begins at zero. Add timeline_offset_ms to subtitle times to play beside the original video. Delayed audio starts are padded; speech is not concatenated.",
        }
        write_json(directory / "audio_export.json", metadata)
        bundle = directory / "audio-export.zip"
        with zipfile.ZipFile(
            bundle.with_suffix(".part.zip"), "w", compression=zipfile.ZIP_STORED
        ) as archive:
            archive.write(audio_path, audio_path.name)
            archive.write(directory / "audio_export.json", "audio_export.json")
        bundle.with_suffix(".part.zip").rename(bundle)
        return directory, metadata
    except BaseException:
        # This UUID directory was created above solely for the failed export.
        # Remove only our known files; never touch source media or existing exports.
        for name in (
            temporary.name,
            f"audio.{audio_format}",
            "audio_export.json",
            "audio-export.part.zip",
        ):
            (directory / name).unlink(missing_ok=True)
        if not any(directory.iterdir()):
            directory.rmdir()
        raise
