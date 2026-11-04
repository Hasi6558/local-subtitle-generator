"""One local preview encoder; preserve source timing and never change the source."""

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from local_subs.api_worker import allowed_media
from local_subs.inference import cache_key
from local_subs.jobs import fingerprint
from local_subs.media import inspect_media, select_track


def preview_command(source, track, info, destination, force=False):
    videos = [s for s in info["streams"] if s["codec_type"] == "video"]
    if not videos:
        raise ValueError("This file has no video to preview")
    video = videos[0]
    copy_video = video.get("codec_name") == "h264" and not force
    copy_audio = track.get("codec_name") == "aac" and not force
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-n",
        "-copyts",
        "-start_at_zero",
        "-i",
        str(source),
        "-map",
        f"0:{video['index']}",
        "-map",
        f"0:{track['index']}",
        "-sn",
        "-dn",
    ]
    command += (
        ["-c:v", "copy"]
        if copy_video
        else [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=w='min(1280,iw)':h=-2",
        ]
    )
    command += (
        ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    )
    command += [
        "-avoid_negative_ts",
        "disabled",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    return command, "remux" if copy_video and copy_audio else (
        "audio transcode" if copy_video else "video transcode"
    )


class PreviewManager:
    def __init__(self, root, roots, repository):
        self.root, self.roots, self.repository = root, roots, repository
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.guard = threading.Lock()
        self.process = None
        self.stopping = False
        repository.recover_previews()

    def request(self, manifest, force=False):
        source = allowed_media(
            Path(manifest.get("source_path") or manifest["source"]["path"]),
            self.roots,
            self.root,
        )
        info = inspect_media(source)
        track = select_track(info, "auto", manifest["audio_stream"])
        key = cache_key(
            {
                "source": fingerprint(source),
                "track": track["index"],
                "force_transcode": force,
                "preview_policy": "movie-timeline-v1",
            }
        )
        directory = self.root / manifest["job_id"] / "previews" / key
        command, mode = preview_command(
            source, track, info, directory / "unused.mp4", force
        )
        with self.guard:
            if self.stopping:
                raise ValueError("Server is stopping")
            try:
                previous = self.repository.preview(manifest["job_id"], key)
                if previous["state"] in ("queued", "processing") or (
                    previous["state"] == "completed"
                    and Path(previous["path"]).is_file()
                    and fingerprint(Path(previous["path"])) == previous.get("sha256")
                ):
                    return previous
            except KeyError:
                pass
            data = {
                "job_id": manifest["job_id"],
                "cache_key": key,
                "state": "queued",
                "mode": mode,
                "audio_stream": track["index"],
                "source_start_time": info["format"].get("start_time", "0"),
                "source_duration": info["format"].get("duration"),
                "path": str(directory / "preview.mp4"),
            }
            self.repository.save_preview(data)
            self.executor.submit(self._prepare, data, source, track, info, force)
            return data

    def _prepare(self, data, source, track, info, force):
        temporary = None
        try:
            allowed_media(source, self.roots, self.root)
            directory = Path(data["path"]).parent
            directory.mkdir(parents=True, exist_ok=True)
            temporary = directory / f"{uuid4().hex}.part.mp4"
            command, _ = preview_command(source, track, info, temporary, force)
            with self.guard:
                if self.stopping:
                    raise ValueError("Preview cancelled during server shutdown")
                data = data | {"state": "processing"}
                self.repository.save_preview(data)
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            _, error = self.process.communicate()
            if self.process.returncode:
                raise ValueError(
                    f"Preview preparation failed: {error.decode('utf-8', errors='replace')[-2000:]}"
                )
            prepared = inspect_media(temporary)
            if not any(s["codec_type"] == "video" for s in prepared["streams"]):
                raise ValueError("Prepared preview contains no video")
            os.replace(temporary, data["path"])
            self.repository.save_preview(
                data
                | {
                    "state": "completed",
                    "duration": prepared["format"].get("duration"),
                    "sha256": fingerprint(Path(data["path"])),
                }
            )
        except Exception as exc:
            self.repository.save_preview(data | {"state": "failed", "error": str(exc)})
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
            with self.guard:
                self.process = None

    def stop(self):
        with self.guard:
            self.stopping = True
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
        self.executor.shutdown(wait=True, cancel_futures=False)
