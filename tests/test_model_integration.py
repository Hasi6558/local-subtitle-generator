"""Opt-in real inference; never downloads a model or bundles movie fixtures."""

import json
import os
from pathlib import Path

import pytest

from local_subs.config import Settings
from local_subs.jobs import generate


@pytest.mark.skipif(
    not os.getenv("LOCAL_SUBS_TEST_MEDIA"),
    reason="Set LOCAL_SUBS_TEST_MEDIA to opt into real CPU inference",
)
def test_real_japanese_clip(tmp_path):
    settings = Settings(
        source_language="auto",
        speech_model="small",
        device="cpu",
        compute_type="int8",
        model_cache=Path(os.environ.get("LOCAL_SUBS_MODEL_CACHE", "models")),
        output_dir=tmp_path,
    )
    directory = generate(Path(os.environ["LOCAL_SUBS_TEST_MEDIA"]), settings)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["resolved_source_language"] == "ja"
    assert manifest["task"] == "translate"
    assert manifest["cue_count"] > 0
    # Passing confirms execution/structure only, never semantic accuracy.


@pytest.mark.skipif(
    not os.getenv("LOCAL_SUBS_TEST_MEDIA"),
    reason="Set LOCAL_SUBS_TEST_MEDIA to opt into real CPU inference",
)
def test_chunked_real_cancel_resume(tmp_path):
    from local_subs.resumable import generate as chunked_generate, resume, read_manifest

    settings = Settings(
        source_language="ja",
        speech_model="small",
        device="cpu",
        compute_type="int8",
        model_cache=Path(os.environ.get("LOCAL_SUBS_MODEL_CACHE", "models")),
        output_dir=tmp_path,
        chunk_seconds=15,
        overlap_seconds=2,
    )

    def interrupt(message):
        if message.startswith("Checkpointed chunk_00000"):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        chunked_generate(
            Path(os.environ["LOCAL_SUBS_TEST_MEDIA"]), settings, notify=interrupt
        )
    directory = next(tmp_path.glob("*/manifest.json")).parent
    manifest = read_manifest(directory)
    checkpoint = Path(manifest["chunks"][0]["path"])
    before = checkpoint.stat().st_mtime_ns
    resume(directory.name, tmp_path)
    assert checkpoint.stat().st_mtime_ns == before
    assert read_manifest(directory)["state"] == "completed"
