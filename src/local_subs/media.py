import json
import shutil
import subprocess


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
