import json
import shutil
import subprocess
from decimal import Decimal, ROUND_HALF_UP


def milliseconds(seconds):
    return int(
        (Decimal(str(seconds)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def parse_time(value):
    parts = str(value).split(":")
    if len(parts) not in (1, 3):
        raise ValueError("Time must be seconds or HH:MM:SS[.mmm]")
    numbers = [Decimal(p) for p in parts]
    if any(not n.is_finite() or n < 0 for n in numbers):
        raise ValueError("Time must be finite and nonnegative")
    if len(numbers) == 3:
        if numbers[1] >= 60 or numbers[2] >= 60:
            raise ValueError("Minutes and seconds must be below 60")
        seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    else:
        seconds = numbers[0]
    return milliseconds(seconds)


def select_track(info, source_language, index=None):
    tracks = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not tracks:
        raise ValueError("No audio streams found")
    if index is not None:
        for track in tracks:
            if track["index"] == index:
                return track
        raise ValueError(f"Global stream {index} is not an audio stream; run inspect")
    if len(tracks) == 1:
        return tracks[0]
    # Container ISO-639-2 tags differ from Whisper's ISO-639-1 codes.
    from babel.core import get_global

    mapping = get_global("language_aliases")
    matches = []
    for track in tracks:
        tag = (
            track.get("tags", {})
            .get("language", "")
            .lower()
            .replace("_", "-")
            .split("-")[0]
        )
        normalized = mapping.get(tag, tag).split("_")[0]
        if normalized == "jv":
            normalized = "jw"
        if source_language != "auto" and normalized == source_language:
            matches.append(track)
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        "Ambiguous audio tracks; select a global index using --audio-stream (see inspect)"
    )


def extract_audio(
    path, track, info, destination, start_ms=0, duration_ms=None, *, codec="pcm_s16le"
):
    """Decode on the movie timeline; pad a delayed audio start, never concatenate speech."""
    if not shutil.which("ffmpeg"):
        raise ValueError("ffmpeg missing; install FFmpeg and add bin to PATH")
    origin = float(info.get("format", {}).get("start_time", 0))
    trim = f"atrim=start={start_ms / 1000}"
    if duration_ms is not None:
        trim += f":end={(start_ms + duration_ms) / 1000}"
    filters = f"asetpts=PTS-({origin})/TB,aresample=16000:async=1:first_pts=0,{trim},asetpts=PTS-STARTPTS"
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-n",
            "-copyts",
            "-i",
            str(path.resolve()),
            "-map",
            f"0:{track['index']}",
            "-vn",
            "-af",
            filters,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            codec,
            str(destination),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise ValueError(f"Audio extraction failed: {result.stderr.strip()}")


def inspect_media(path):
    if not path.is_file():
        raise ValueError(f"Media file does not exist: {path}")
    if not shutil.which("ffprobe"):
        raise ValueError(
            "ffprobe missing; install FFmpeg and add its bin directory to PATH"
        )
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path.resolve()),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise ValueError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)
