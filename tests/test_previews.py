import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_subs.api import create_app
from local_subs.jobs import fingerprint
from local_subs.media import inspect_media


@pytest.mark.parametrize(
    "codec,force,expected",
    [
        ("h264", False, "remux"),
        ("ffv1", False, "video transcode"),
        ("h264", True, "video transcode"),
    ],
)
def test_preview_codec_fallback_offsets_cache_and_source_preservation(
    tmp_path, codec, force, expected
):
    source = tmp_path / "delayed source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=32x32:duration=4",
            "-itsoffset",
            "1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264" if codec == "h264" else "ffv1",
            "-c:a",
            "aac",
            "-output_ts_offset",
            "7",
            str(source),
        ],
        check=True,
    )
    before = fingerprint(source)
    root = tmp_path / "output"
    app = create_app(root, [tmp_path], token="preview-test-token", start_worker=False)
    with TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer preview-test-token"},
    ) as client:
        job = client.post(
            "/jobs", json={"path": str(source), "settings": {"source_language": "ja"}}
        ).json()
        identifier = job["job_id"]
        response = client.post(
            f"/jobs/{identifier}/preview", json={"force_transcode": force}
        )
        assert response.status_code == 202, response.text
        key = response.json()["cache_key"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            preview = client.get(
                f"/jobs/{identifier}/preview", params={"key": key}
            ).json()
            if preview["state"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert preview["state"] == "completed", preview
        assert preview["mode"] == expected
        prepared = Path(preview["path"])
        info = inspect_media(prepared)
        assert [s["codec_name"] for s in info["streams"]] == ["h264", "aac"]
        video, audio = info["streams"]
        assert abs(float(video["start_time"])) < 0.08
        assert abs(float(audio["start_time"]) - 1) < 0.08
        cached_time = prepared.stat().st_mtime_ns
        cached = client.post(
            f"/jobs/{identifier}/preview", json={"force_transcode": force}
        ).json()
        assert cached["state"] == "completed"
        assert prepared.stat().st_mtime_ns == cached_time
        streamed = client.get(
            f"/jobs/{identifier}/preview/media",
            params={"key": key},
            headers={"Range": "bytes=0-15"},
        )
        assert streamed.status_code == 206
        assert streamed.content == prepared.read_bytes()[:16]
        assert fingerprint(source) == before


def test_playback_warns_when_browser_default_track_differs(tmp_path):
    source = tmp_path / "multiple.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=32x32:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "1:a",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-disposition:a:0",
            "default",
            "-disposition:a:1",
            "0",
            str(source),
        ],
        check=True,
    )
    app = create_app(
        tmp_path / "output", [tmp_path], token="track-test", start_worker=False
    )
    with TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer track-test"},
    ) as client:
        manifest = client.post(
            "/jobs", json={"path": str(source), "audio_stream": 2}
        ).json()
        response = client.get(f"/jobs/{manifest['job_id']}/playback").json()
        assert response["default_audio_stream"] == 1
        assert response["requires_selected_track_preview"] is True
