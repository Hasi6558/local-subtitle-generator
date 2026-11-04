import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from local_subs.cli import app
from local_subs.config import load_settings
from local_subs.media import inspect_media


def test_config(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text('source_language="ja"\nspeech_model="small"\n')
    settings = load_settings(config, source_language=" FR ")
    assert settings.source_language == "fr"
    assert settings.speech_model == "small"
    for values in (
        {"target_language": "fr"},
        {"source_language": "invalid"},
        {"speech_model": "turbo"},
        {"speech_model": "small.en"},
    ):
        with pytest.raises(ValueError):
            load_settings(**values)


def test_help_and_invalid_path():
    runner = CliRunner()
    assert runner.invoke(app, ["--help"]).exit_code == 0
    result = runner.invoke(app, ["inspect", "missing movie.mkv"])
    assert result.exit_code == 1
    assert "does not exist" in result.stdout


def test_missing_probe(tmp_path, monkeypatch):
    path = tmp_path / "movie.mkv"
    path.touch()
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="ffprobe missing"):
        inspect_media(path)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_real_multitrack(tmp_path):
    path = tmp_path / "movie \u65e5\u672c\u8a9e space.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:duration=1",
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
            "ffv1",
            "-c:a",
            "pcm_s16le",
            "-metadata:s:a:0",
            "language=jpn",
            "-metadata:s:a:1",
            "language=eng",
            str(path),
        ],
        check=True,
    )
    tracks = [s for s in inspect_media(path)["streams"] if s["codec_type"] == "audio"]
    assert [s["index"] for s in tracks] == [1, 2]
    assert [s["tags"]["language"] for s in tracks] == ["jpn", "eng"]
    assert CliRunner().invoke(app, ["inspect", str(path)]).exit_code == 0
