import json
import subprocess
from types import SimpleNamespace

import pytest

from local_subs.file_picker import pick_file


def test_picker_protocol_preserves_unicode_and_cancel(tmp_path, monkeypatch):
    selected = tmp_path / "日本語 video.mp4"

    def run(command, **kwargs):
        assert command[-1] == str(tmp_path)
        assert kwargs["encoding"] == "utf-8" and kwargs["timeout"] == 300
        return SimpleNamespace(returncode=0, stdout=json.dumps(str(selected)))

    monkeypatch.setattr(subprocess, "run", run)
    assert pick_file(tmp_path) == selected
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="null")
    )
    assert pick_file(tmp_path) is None


def test_picker_failure_and_timeout_are_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1)
    )
    with pytest.raises(ValueError, match="Enter path manually"):
        pick_file(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("picker", 300)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        pick_file(tmp_path)
