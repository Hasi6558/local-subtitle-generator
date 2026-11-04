import copy
import json
import sqlite3
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from local_subs.api import create_app
from local_subs.api_worker import work_once
from local_subs.jobs import write_json
from local_subs.repository import JobRepository
from local_subs.resumable import read_manifest


@pytest.fixture
def api(tmp_path):
    media_root = tmp_path / "media"
    media_root.mkdir()
    media = media_root / "sample.wav"
    with wave.open(str(media), "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0" * 16000)
    root = tmp_path / "outputs"
    app = create_app(root, [media_root], token="test-local-token", start_worker=False)
    with TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        headers={"Authorization": "Bearer test-local-token"},
    ) as client:
        yield client, app, root, media


def create_job(api):
    client, app, root, media = api
    response = client.post(
        "/jobs",
        json={
            "path": str(media),
            "settings": {"source_language": "ja", "speech_model": "small"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def complete_job(api):
    client, app, root, media = api
    manifest = create_job(api)
    directory = root / manifest["job_id"]
    cues = [
        {
            "id": "cue1",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Hello world.",
            "origin": "model",
            "edit_version": 0,
        }
    ]
    write_json(directory / "generated_cues.json", cues)
    manifest.update(
        state="completed",
        artifacts={"generated_cues.json": str(directory / "generated_cues.json")},
    )
    write_json(directory / "manifest.json", manifest)
    return manifest, cues


def test_auth_origin_host_and_path_restrictions(api, tmp_path):
    client, app, root, media = api
    assert client.get("/health").status_code == 200
    assert client.get("/jobs", headers={"Authorization": ""}).status_code == 401
    assert (
        client.post(
            "/jobs",
            json={"path": str(media)},
            headers={"Origin": "https://unwanted.example"},
        ).status_code
        == 403
    )
    assert client.get("/jobs", headers={"Host": "unwanted.example"}).status_code == 400
    assert (
        client.post(
            "/media/inspect", json={"path": str(tmp_path / "outside.wav")}
        ).status_code
        == 403
    )
    assert client.get("/jobs/not-a-job").status_code == 404
    assert client.get("/media", params={"path": str(media)}).status_code == 404
    assert (
        client.post(
            "/jobs", json={"path": str(media), "settings": {"target_language": "fr"}}
        ).status_code
        == 422
    )
    assert (
        client.post("/session", headers={"Origin": "http://127.0.0.1:8765"}).status_code
        == 200
    )
    assert (
        client.get("/jobs", headers={"Authorization": ""}).status_code == 200
    )  # strict session cookie


def test_registered_media_ranges_and_progress(api):
    client, app, root, media = api
    manifest = create_job(api)
    job_id = manifest["job_id"]
    response = client.get(f"/jobs/{job_id}/media", headers={"Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content == media.read_bytes()[:16]
    assert response.headers["content-range"].startswith("bytes 0-15/")
    assert (
        client.get(
            f"/jobs/{job_id}/media", headers={"Range": "bytes=9999999-"}
        ).status_code
        == 416
    )
    assert client.head(f"/jobs/{job_id}/media").content == b""
    assert client.get(f"/jobs/{job_id}/progress").json()["state"] == "queued"
    assert client.get("/languages").json()["target_language"] == "en"
    assert (
        client.post("/media/inspect", json={"path": str(media)}).json()["streams"][0][
            "codec_type"
        ]
        == "audio"
    )


def test_concurrent_edit_conflict_and_revision_export(api):
    client, app, root, media = api
    manifest, cues = complete_job(api)
    job_id = manifest["job_id"]
    assert client.get(f"/jobs/{job_id}/cues").json()["revision"] == 0
    first, second = copy.deepcopy(cues), copy.deepcopy(cues)
    first[0]["text"], second[0]["text"] = "First manual edit.", "Second manual edit."

    def save(data):
        return client.put(
            f"/jobs/{job_id}/cues", json={"expected_revision": 0, "cues": data}
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(save, [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    latest = client.get(f"/jobs/{job_id}/cues").json()
    assert latest["revision"] == 1
    assert latest["cues"][0]["origin"] == "manual"
    export = client.post(f"/jobs/{job_id}/exports", json={"revision": 1})
    assert export.status_code == 201, export.text
    export_id = export.json()["export_id"]
    result = client.get(f"/jobs/{job_id}/exports/{export_id}/subtitles.en.srt")
    assert latest["cues"][0]["text"] in result.text
    assert (
        client.get(f"/jobs/{job_id}/exports/{export_id}/manifest.json").status_code
        == 404
    )
    original = client.get(f"/jobs/{job_id}/cues?revision=0").json()
    assert original["cues"][0]["text"] == "Hello world."
    invalid = copy.deepcopy(latest["cues"])
    invalid[0]["end_ms"] = -1
    assert (
        client.put(
            f"/jobs/{job_id}/cues", json={"expected_revision": 1, "cues": invalid}
        ).status_code
        == 422
    )


def test_queue_cancellation_retry_and_silent_worker(api):
    client, app, root, media = api
    manifest = create_job(api)
    job_id = manifest["job_id"]
    assert client.post(f"/jobs/{job_id}/cancel").json()["state"] == "cancelled"
    assert client.post(f"/jobs/{job_id}/retry").json()["state"] == "queued"

    def never_load(*args):
        pytest.fail("Silent audio must not load a model")

    assert work_once(root, [media.parent], model_loader=never_load)
    assert client.get(f"/jobs/{job_id}").json()["state"] == "completed"
    assert client.post(f"/jobs/{job_id}/retry").status_code == 409
    assert client.post(f"/jobs/{job_id}/cancel").status_code == 409


def test_repository_authority_migration_and_recovery(tmp_path, monkeypatch):
    root = tmp_path / "jobs"
    repository = JobRepository(root)
    job_id = "a" * 32
    manifest = {
        "job_id": job_id,
        "state": "queued",
        "execution_mode": "queued",
        "settings": {},
    }
    write_json(root / job_id / "manifest.json", manifest)
    claimed = repository.claim()
    assert claimed["state"] == "preparing"
    monkeypatch.setattr("local_subs.worker.process_alive", lambda pid: False)
    assert repository.recover() == [job_id]
    assert repository.get(job_id)["state"] == "queued"
    (root / job_id / "manifest.json").write_text(
        json.dumps(manifest | {"state": "failed"})
    )
    assert (
        read_manifest(root / job_id)["state"] == "queued"
    )  # snapshot cannot override DB
    repository.request_cancel(job_id)
    assert JobRepository(root).get(job_id)["state"] == "cancelled"
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3


def test_worker_failure_preserves_job(api, monkeypatch):
    client, app, root, media = api
    manifest = create_job(api)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated worker dispatch failure")

    monkeypatch.setattr("local_subs.api_worker.run", fail)
    work_once(root, [media.parent])
    result = client.get(f"/jobs/{manifest['job_id']}").json()
    assert result["state"] == "failed"
    assert "simulated worker" in result["error"]["message"]
    assert client.post(f"/jobs/{manifest['job_id']}/retry").status_code == 202


def test_schema_one_upgrade_and_pending_queue_restart(tmp_path):
    root = tmp_path / "legacy"
    root.mkdir()
    path = root / "jobs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY,state TEXT NOT NULL,manifest TEXT NOT NULL,updated_at TEXT NOT NULL)"
        )
        connection.execute("PRAGMA user_version=1")
    repository = JobRepository(root)
    job_id = "b" * 32
    repository.save({"job_id": job_id, "state": "queued", "execution_mode": "queued"})
    reopened = JobRepository(root)
    assert reopened.get(job_id)["state"] == "queued"
    assert reopened.claim()["job_id"] == job_id
    assert reopened.cues(job_id, baseline=[])["revision"] == 0


def test_api_cancels_active_inference_without_lost_control_flag(api, monkeypatch):
    from dataclasses import dataclass

    client, app, root, media = api
    manifest = create_job(api)
    job_id = manifest["job_id"]
    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps",
        lambda audio: [{"start": 0, "end": len(audio)}],
    )

    @dataclass
    class Segment:
        start: float = 0
        end: float = 1
        text: str = "Hello."

    class Model:
        supported_languages = ["ja"]

        def transcribe(self, audio, **kwargs):
            assert client.post(f"/jobs/{job_id}/cancel").status_code == 202
            return iter([Segment()]), None

    def loader(*args):
        return Model(), {
            "device": "cpu",
            "compute_type": "int8",
            "model_revision": "test",
        }

    work_once(root, [media.parent], model_loader=loader)
    result = client.get(f"/jobs/{job_id}").json()
    assert result["state"] == "cancelled"
    assert result["cancel_requested"] is True
    assert client.post(f"/jobs/{job_id}/retry").json()["cancel_requested"] is False


def test_proposal_job_keeps_parent_edits(api):
    client, app, root, media = api
    manifest, cues = complete_job(api)
    parent = manifest["job_id"]
    baseline = client.get(f"/jobs/{parent}/cues").json()
    baseline["cues"][0]["text"] = "Keep my correction."
    assert (
        client.put(
            f"/jobs/{parent}/cues",
            json={"expected_revision": 0, "cues": baseline["cues"]},
        ).status_code
        == 200
    )
    proposed = client.post(
        "/jobs",
        json={
            "path": str(media),
            "parent_job_id": parent,
            "start_ms": 0,
            "duration_ms": 1000,
        },
    )
    assert proposed.status_code == 201
    assert proposed.json()["parent_job_id"] == parent
    assert (
        client.get(f"/jobs/{parent}/cues").json()["cues"][0]["text"]
        == "Keep my correction."
    )
    assert client.get(f"/jobs/{parent}/cue-revisions").json()[0]["revision"] == 1


def test_public_bundle_does_not_expose_private_routes(api, tmp_path):
    client, original, root, media = api
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<html>Review fixture</html>")
    (bundle / "assets" / "style.css").write_text("body { color: black }")
    app = create_app(
        root,
        [media.parent],
        token="static-test-token",
        start_worker=False,
        web_dir=bundle,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as public:
        assert public.get("/").status_code == 200
        assert public.get("/assets/style.css").status_code == 200
        assert public.get("/jobs").status_code == 401
        response = public.get("/assets/%2e%2e/jobs.sqlite3")
        assert response.status_code in (401, 404)
        assert not response.content.startswith(b"SQLite format")


def test_quality_recomputes_stale_derived_flags(api):
    client, app, root, media = api
    manifest, cues = complete_job(api)
    cues[0]["flags"] = ["reading_speed"]
    write_json(root / manifest["job_id"] / "generated_cues.json", cues)
    report = client.get(f"/jobs/{manifest['job_id']}/qc").json()
    assert "reading_speed" not in report["issue_counts"]


def test_shutdown_cancels_active_keeps_queue_and_releases_lock(tmp_path, monkeypatch):
    import asyncio
    import subprocess
    from local_subs.service import WorkerManager
    from local_subs.worker import worker_lock

    root = tmp_path / "jobs"
    manager = WorkerManager(root, [tmp_path])
    active, queued = "c" * 32, "d" * 32
    manager.repository.save(
        {"job_id": active, "state": "queued", "execution_mode": "queued"}
    )
    assert manager.repository.claim()["job_id"] == active
    manager.repository.save(
        {"job_id": queued, "state": "queued", "execution_mode": "queued"}
    )
    monkeypatch.setattr("local_subs.worker.process_alive", lambda pid: False)

    class Process:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def wait(self, timeout=None):
            if not self.stopped:
                raise subprocess.TimeoutExpired("test worker", timeout)
            return 0

        def terminate(self):
            self.stopped = True

    manager.process = Process()
    manager.lock = worker_lock(root / ".service", "test-server")
    manager.lock.__enter__()

    async def stop():
        manager.monitor = asyncio.create_task(asyncio.sleep(60))
        await manager.stop()

    asyncio.run(stop())
    assert manager.repository.get(active)["state"] == "cancelled"
    assert manager.repository.get(queued)["state"] == "queued"
    assert not (root / ".service" / ".worker.lock").exists()
