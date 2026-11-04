import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from local_subs.chunks import stitch
from local_subs.config import Settings
from local_subs.resumable import (
    Cancelled,
    cancel,
    cleanup,
    generate,
    job_directory,
    read_manifest,
    resume,
)
from local_subs.worker import worker_lock


@dataclass
class Segment:
    start: float = 0.5
    end: float = 2.0
    text: str = "Hello again."


class Model:
    supported_languages = ["ja", "en", "fr"]

    def __init__(self):
        self.calls = 0
        self.detects = 0

    def detect_language(self, **kwargs):
        self.detects += 1
        return "ja", 0.99, [("ja", 0.99)]

    def transcribe(self, audio, **kwargs):
        assert len(audio) <= 7 * 16000
        self.calls += 1
        return iter([Segment()]), None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    media = tmp_path / "input.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=11:sample_rate=16000",
            str(media),
        ],
        check=True,
    )
    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps",
        lambda audio: [{"start": 0, "end": len(audio)}],
    )
    settings = Settings(
        source_language="auto",
        output_dir=tmp_path / "jobs",
        chunk_seconds=5,
        overlap_seconds=1,
    )
    model = Model()

    def loader(*args):
        return model, {
            "device": "cpu",
            "compute_type": "int8",
            "model_revision": "fixed",
        }

    return media, settings, model, loader


def test_cancel_resume_and_invalidation(setup):
    media, settings, model, loader = setup

    def interrupt(message):
        if message.startswith("Checkpointed chunk_00000"):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        generate(media, settings, notify=interrupt, model_loader=loader)
    directory = next(settings.output_dir.glob("*/manifest.json")).parent
    first = read_manifest(directory)
    assert first["state"] == "cancelled"
    checkpoint = Path(first["chunks"][0]["path"])
    saved_time = checkpoint.stat().st_mtime_ns
    assert model.calls == 1
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert model.calls == 3
    assert model.detects == 1
    assert checkpoint.stat().st_mtime_ns == saved_time
    manifest = read_manifest(directory)
    assert manifest["state"] == "completed"
    audio_time = Path(manifest["prepared_audio"]["path"]).stat().st_mtime_ns
    old_export = Path(manifest["artifacts"]["subtitles.en.srt"])
    old_export.write_text("manual edit")
    resume(
        directory.name,
        settings.output_dir,
        {"source_language": "en"},
        model_loader=loader,
    )
    assert model.calls == 6
    assert (
        Path(read_manifest(directory)["prepared_audio"]["path"]).stat().st_mtime_ns
        == audio_time
    )
    assert old_export.read_text() == "manual edit"
    resume(
        directory.name,
        settings.output_dir,
        {"speech_model": "small"},
        model_loader=loader,
    )
    assert model.calls == 9
    assert checkpoint.exists()


def test_partial_checkpoint_cleanup_and_cancel(setup):
    media, settings, model, loader = setup
    directory = generate(media, settings, model_loader=loader)
    manifest = read_manifest(directory)
    Path(manifest["chunks"][1]["path"]).write_text("{partial")
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert model.calls == 4  # only the corrupt checkpoint was rerun
    assert cleanup(directory.name, settings.output_dir) > 0
    assert media.exists()
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert model.calls == 4  # extraction is rebuilt; valid inference remains reusable
    with pytest.raises(ValueError, match="already completed"):
        cancel(directory.name, settings.output_dir)


def test_cooperative_cancel_and_lock(setup):
    media, settings, model, loader = setup

    def request(message):
        if message.startswith("Checkpointed chunk_00000"):
            directory = next(settings.output_dir.glob("*/manifest.json")).parent
            cancel(directory.name, settings.output_dir)
            with pytest.raises(ValueError, match="active"):
                cleanup(directory.name, settings.output_dir)

    with pytest.raises(Cancelled):
        generate(media, settings, notify=request, model_loader=loader)
    directory = next(settings.output_dir.glob("*/manifest.json")).parent
    assert read_manifest(directory)["state"] == "cancelled"
    with worker_lock(settings.output_dir, directory.name):
        with pytest.raises(ValueError, match="already active"):
            resume(directory.name, settings.output_dir, model_loader=loader)
    with pytest.raises(ValueError, match="Invalid job"):
        job_directory(settings.output_dir, "../outside")


def test_disk_failure_retains_checkpoint(setup, monkeypatch):
    import local_subs.resumable as service

    media, settings, model, loader = setup
    original = service.write_json

    def fail_checkpoint(path, data):
        if path.parent.name == "chunks" and path.name.startswith("chunk_00001"):
            raise OSError(28, "simulated disk full")
        return original(path, data)

    monkeypatch.setattr(service, "write_json", fail_checkpoint)
    with pytest.raises(OSError):
        generate(media, settings, model_loader=loader)
    directory = next(settings.output_dir.glob("*/manifest.json")).parent
    manifest = read_manifest(directory)
    assert manifest["state"] == "failed"
    assert manifest["chunks"][0]["state"] == "completed"
    assert Path(manifest["chunks"][0]["path"]).is_file()
    assert "Free disk" in manifest["error"]["retry_hint"]
    monkeypatch.setattr(service, "write_json", original)
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert model.calls == 4


def test_input_change_invalidates_extraction(setup):
    media, settings, model, loader = setup
    directory = generate(media, settings, model_loader=loader)
    before = read_manifest(directory)["prepared_audio"]["key"]
    # Append an ignored RIFF trailing byte to change the content identity.
    with media.open("ab") as handle:
        handle.write(b"0")
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert read_manifest(directory)["prepared_audio"]["key"] != before
    assert model.calls == 6


def test_stitch_only_local_duplicates_and_preserves_alternatives():
    chunks = [
        {
            "id": "a",
            "owner_start_ms": 0,
            "owner_end_ms": 2000,
            "context_start_ms": 0,
            "context_end_ms": 3000,
        },
        {
            "id": "b",
            "owner_start_ms": 2000,
            "owner_end_ms": 5000,
            "context_start_ms": 1000,
            "context_end_ms": 5000,
        },
    ]

    def segment(identity, chunk, start, end, text="Hello"):
        return {
            "id": identity,
            "source_chunk": chunk,
            "start_ms": start,
            "end_ms": end,
            "text": text,
        }

    alternatives = [
        [segment("a1", "a", 1400, 2400)],
        [segment("b1", "b", 1600, 2600), segment("b2", "b", 3500, 4000)],
    ]
    raw, cues, report = stitch(chunks, alternatives, 0, 5000)
    assert len(raw) == 3
    assert len(cues) == 2  # later repeated phrase is kept
    assert cues[0]["source_segment_ids"] == ["a1", "b1"]
    assert report[0]["issue"] == "boundary_duplicate"
    alternatives[1][0]["text"] = "Completely different"
    _, cues, report = stitch(chunks, alternatives, 0, 5000)
    assert "boundary_conflict" in report[-1]["issues"]


def test_track_change_and_resolved_language_invalidate(setup):
    media, settings, model, loader = setup
    multi = media.with_suffix(".mkv")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(media),
            "-map",
            "0:a",
            "-map",
            "0:a",
            "-c:a",
            "pcm_s16le",
            str(multi),
        ],
        check=True,
    )
    directory = generate(multi, settings, audio_stream=0, model_loader=loader)
    before = read_manifest(directory)["prepared_audio"]["key"]
    resume(directory.name, settings.output_dir, audio_stream=1, model_loader=loader)
    assert model.calls == 6
    manifest = read_manifest(directory)
    assert manifest["prepared_audio"]["key"] != before
    manifest["resolved_source_language"] = "en"
    from local_subs.jobs import write_json

    write_json(directory / "manifest.json", manifest)
    resume(directory.name, settings.output_dir, model_loader=loader)
    assert model.calls == 9
    assert read_manifest(directory)["task"] == "transcribe"


def test_formatting_change_reuses_inference(setup):
    media, settings, model, loader = setup
    directory = generate(media, settings, model_loader=loader)
    assert model.calls == 3
    resume(
        directory.name,
        settings.output_dir,
        {"formatting": {"line_width": 20}},
        model_loader=loader,
    )
    assert model.calls == 3
    manifest = read_manifest(directory)
    assert Path(manifest["artifacts"]["qc.json"]).is_file()
    assert Path(manifest["artifacts"]["subtitles.en.vtt"]).is_file()
