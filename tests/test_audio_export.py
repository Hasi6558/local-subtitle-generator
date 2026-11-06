import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from local_subs.audio_export import export_audio
from local_subs.cli import app
from local_subs.jobs import fingerprint


@pytest.mark.parametrize("audio_format", ["flac", "wav"])
def test_export_track_delay_offset_formats_and_immutable_bundle(tmp_path, audio_format):
    from faster_whisper.audio import decode_audio

    source = tmp_path / "日本語 delayed video.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=32x32:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=4",
            "-itsoffset",
            "1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=3",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            "-output_ts_offset",
            "7",
            str(source),
        ],
        check=True,
    )
    before = fingerprint(source)
    with pytest.raises(ValueError, match="Ambiguous"):
        export_audio(source, tmp_path / "out")
    directory, data = export_audio(
        source,
        tmp_path / "out",
        audio_stream=2,
        start_ms=500,
        duration_ms=2000,
        audio_format=audio_format,
    )
    samples = decode_audio(str(directory / data["audio_file"]), sampling_rate=16000)
    assert (
        data["timeline_offset_ms"] == 500 and abs(data["audio_duration_ms"] - 2000) <= 1
    )
    assert np.max(np.abs(samples[:6000])) < 0.0001  # Delayed start remains silence.
    tone = samples[16000:24000]
    dominant = np.argmax(np.abs(np.fft.rfft(tone))) * 16000 / len(tone)
    assert abs(dominant - 880) < 3  # Selected second track, not 440 Hz first track.
    with zipfile.ZipFile(directory / "audio-export.zip") as archive:
        assert set(archive.namelist()) == {f"audio.{audio_format}", "audio_export.json"}
        assert json.loads(archive.read("audio_export.json")) == data
        assert (
            archive.read(f"audio.{audio_format}")
            == (directory / data["audio_file"]).read_bytes()
        )
    again, _ = export_audio(source, tmp_path / "out", audio_stream=2, duration_ms=1000)
    assert directory != again and fingerprint(source) == before
    assert fingerprint(directory / data["audio_file"]) == data["audio_sha256"]


def test_export_cli_errors_and_failed_output_cleanup(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", str(source)],
        check=True,
    )
    before = source.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "extract-audio",
            str(source),
            "--start",
            "0.5",
            "--duration",
            "1",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "out").glob("*/audio.flac"))) == 1
    with pytest.raises(ValueError, match="outside media"):
        export_audio(source, tmp_path / "out", start_ms=5000)
    with pytest.raises(ValueError, match="Audio format"):
        export_audio(source, tmp_path / "out", audio_format="mp3")

    def fail(*args, **kwargs):
        Path(args[3]).write_bytes(b"partial")
        raise ValueError("Encoder failed")

    monkeypatch.setattr("local_subs.audio_export.extract_audio", fail)
    with pytest.raises(ValueError, match="Encoder failed"):
        export_audio(source, tmp_path / "failed")
    assert list((tmp_path / "failed").iterdir()) == [] and source.read_bytes() == before
