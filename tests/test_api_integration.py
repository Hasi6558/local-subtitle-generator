"""Opt-in real loopback HTTP + subprocess inference/crash/restart verification."""

import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn

from local_subs.api import create_app


@contextmanager
def live_server(root, media):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    app = create_app(
        root,
        [media.parent],
        model_cache=Path(os.environ.get("LOCAL_SUBS_MODEL_CACHE", "models")).resolve(),
        token="integration-test-token",
        port=port,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "HTTP server did not start"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            headers={"Authorization": "Bearer integration-test-token"},
            timeout=5,
            trust_env=False,
        ) as client:
            yield client, app
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), "HTTP server did not shut down"


@pytest.mark.skipif(
    not os.getenv("LOCAL_SUBS_TEST_MEDIA"),
    reason="Set LOCAL_SUBS_TEST_MEDIA to enable local HTTP/model integration",
)
def test_real_http_inference_crash_restart_and_edits(tmp_path):
    media = Path(os.environ["LOCAL_SUBS_TEST_MEDIA"]).resolve()
    root = Path(os.environ.get("LOCAL_SUBS_API_TEST_OUTPUT", str(tmp_path))).resolve()
    latencies, checkpoint_time, crashed = [], None, False
    with live_server(root, media) as (client, app):
        response = client.post(
            "/jobs",
            json={
                "path": str(media),
                "settings": {
                    "source_language": "ja",
                    "speech_model": "small",
                    "device": "cpu",
                    "compute_type": "int8",
                    "chunk_seconds": 15,
                    "overlap_seconds": 2,
                },
                "duration_ms": 36000,
            },
        )
        assert response.status_code == 201, response.text
        job_id = response.json()["job_id"]
        queued = client.post(
            "/jobs",
            json={
                "path": str(media),
                "settings": {"source_language": "ja", "speech_model": "small"},
                "duration_ms": 1000,
            },
        ).json()["job_id"]
        assert client.post(f"/jobs/{queued}/cancel").json()["state"] == "cancelled"
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            before = time.monotonic()
            assert client.get("/health").status_code == 200
            latency = time.monotonic() - before
            state = client.get(f"/jobs/{job_id}").json()
            if state["state"] == "processing":
                latencies.append(latency)
            completed = [
                c for c in state.get("chunks", []) if c.get("state") == "completed"
            ]
            if completed and not crashed and state["state"] == "processing":
                checkpoint = Path(completed[0]["path"])
                checkpoint_time = checkpoint.stat().st_mtime_ns
                app.state.manager.process.kill()  # Kill only the test-owned inference child.
                crashed = True
            if state["state"] == "completed":
                break
            assert state["state"] not in ("failed", "cancelled"), state
            time.sleep(0.1)
        assert state["state"] == "completed", state
        assert crashed and app.state.manager.restarts == 1
        assert checkpoint.stat().st_mtime_ns == checkpoint_time
        assert latencies and max(latencies) < 2
        cues = client.get(f"/jobs/{job_id}/cues").json()
        cues["cues"][0]["text"] = "Manual API edit."
        saved = client.put(
            f"/jobs/{job_id}/cues",
            json={"expected_revision": cues["revision"], "cues": cues["cues"]},
        )
        assert saved.status_code == 200, saved.text
        exported = client.post(
            f"/jobs/{job_id}/exports", json={"revision": saved.json()["revision"]}
        )
        assert exported.status_code == 201, exported.text
        export_id = exported.json()["export_id"]
        assert (
            "Manual API edit."
            in client.get(f"/jobs/{job_id}/exports/{export_id}/subtitles.en.srt").text
        )
        assert (
            client.get(
                f"/jobs/{job_id}/media", headers={"Range": "bytes=0-15"}
            ).status_code
            == 206
        )
    with live_server(root, media) as (client, app):
        assert client.get(f"/jobs/{job_id}").json()["state"] == "completed"
        assert (
            client.get(f"/jobs/{job_id}/cues").json()["cues"][0]["text"]
            == "Manual API edit."
        )
        assert client.get(f"/jobs/{queued}").json()["state"] == "cancelled"
    root.mkdir(parents=True, exist_ok=True)
    (root / "http-test-summary.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "crash_restarts": 1,
                "checkpoint_preserved": True,
                "health_samples_during_processing": len(latencies),
                "max_health_latency_seconds": max(latencies),
                "cue_count": state["cue_count"],
                "server_restart_preserved_edits": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
