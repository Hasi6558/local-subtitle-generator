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
