"""Isolated browser fixture server; no model inference and no public test routes."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import uvicorn

from local_subs.api import create_app
from local_subs.config import Settings
from local_subs.jobs import write_json
from local_subs.resumable import prepare, read_manifest

PROJECT = Path(__file__).resolve().parents[2]

root = PROJECT / "outputs" / f"phase5-browser-{uuid4().hex}"
root.mkdir(parents=True)
source = root / "sample.mp4"
unsupported = root / "unsupported.mkv"
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=24:duration=12",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=12",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(source),
    ],
    check=True,
)
subprocess.run(
    [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(source),
        "-c:v",
        "ffv1",
        "-c:a",
        "copy",
        str(unsupported),
    ],
    check=True,
)
app = create_app(root, [root], token="ui-test-key", port=8767, start_worker=False)
# Synthetic model availability is test-only; the fixture never claims/executes jobs.
app.router.routes[:] = [
    route for route in app.router.routes if getattr(route, "path", None) != "/models"
]


@app.get("/models")
def models():
    return {
        "models": [
            {"id": "small", "prepared": True},
            {"id": "medium", "prepared": False},
        ],
        "model_cache": str(PROJECT / "models"),
    }


def finish(identifier, text=None):
    directory = root / identifier
    manifest = read_manifest(directory)
    cues = [
        {
            "id": "cue1",
            "start_ms": 500,
            "end_ms": 2500,
            "text": text or "Hello there, welcome to this conversation.",
            "flags": [],
            "origin": "model",
            "edit_version": 0,
        },
        {
            "id": "cue2",
            "start_ms": 3000,
            "end_ms": 5000,
            "text": "Could I have a coffee, please?",
            "flags": [],
            "origin": "model",
            "edit_version": 0,
        },
        {
            "id": "cue3",
            "start_ms": 6000,
            "end_ms": 8000,
            "text": "Thank you very much.",
            "flags": [],
            "origin": "model",
            "edit_version": 0,
        },
    ]
    write_json(directory / "generated_cues.json", cues)
    manifest.update(
        state="completed",
        resolved_source_language="ja",
        cue_count=len(cues),
        artifacts={"generated_cues.json": str(directory / "generated_cues.json")},
    )
    write_json(directory / "manifest.json", manifest)
    return manifest


@app.post("/__test/job")
def fixture(data: dict):
    path = unsupported if data.get("unsupported") else source
    directory, manifest = prepare(
        path,
        Settings(source_language="ja", speech_model="small", output_dir=root),
        duration_ms=12000,
    )
    manifest = finish(directory.name)
    return manifest


@app.post("/__test/finish/{identifier}")
def finish_proposal(identifier: str):
    return finish(identifier, "Proposed replacement text.")


write_json(
    PROJECT / "outputs" / "phase5-browser-fixture.json",
    {"output_root": str(root), "source": str(source)},
)
uvicorn.run(
    app,
    host="127.0.0.1",
    port=8767,
    access_log=False,
    log_level="warning",
    loop="asyncio:SelectorEventLoop" if os.name == "nt" else "auto",
)
