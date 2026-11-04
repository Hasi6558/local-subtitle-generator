import json
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np
import pytest

from local_subs.config import Settings
from local_subs.inference import resolve_language
from local_subs.jobs import atomic_text, generate
from local_subs.media import (
    extract_audio,
    inspect_media,
    milliseconds,
    parse_time,
    select_track,
)
from local_subs.subtitles import compose


def tracks(*tags):
    return {
        "streams": [
            {"index": i + 1, "codec_type": "audio", "tags": {"language": tag}}
            for i, tag in enumerate(tags)
        ]
    }


def test_selection():
    assert select_track(tracks("jpn", "eng"), "ja")["index"] == 1
    assert select_track(tracks("und"), "auto")["index"] == 1
    assert select_track(tracks("fra", "eng"), "fr")["index"] == 1
    assert select_track(tracks("jpn", "eng"), "auto", 2)["index"] == 2
    for info, language, index in [
        (tracks("jpn", "eng"), "auto", None),
        (tracks("jpn", "jpn"), "ja", None),
        (tracks("und", "und"), "ja", None),
        (tracks("jpn"), "ja", 0),
        (tracks(), "ja", None),
    ]:
        with pytest.raises(ValueError):
            select_track(info, language, index)


class Model:
    supported_languages = ["ja", "en", "fr"]

    def __init__(self, language="ja", score=0.95):
        self.language, self.score = language, score
        self.detect_calls = []
        self.transcribe_calls = []

    def detect_language(self, **kwargs):
        self.detect_calls.append(kwargs)
        return self.language, self.score, [(self.language, self.score)]

    def transcribe(self, audio, **kwargs):
        self.transcribe_calls.append(kwargs)

        @dataclass
        class Segment:
            start: float
            end: float
            text: str

        return iter([Segment(0.0015, 0.9, " Hello! ")]), None


def test_detection_skips_leading_silence_and_explicit_wins():
    model = Model()
    audio = np.zeros(80 * 16000, dtype=np.float32)
    speech = [{"start": 10 * 16000, "end": 75 * 16000}]
    language, diagnostic = resolve_language(model, audio, Settings(), 600000, speech)
    assert language == "ja"
    assert diagnostic["samples"][0]["start_ms"] == 610000
    assert diagnostic["samples"][0]["end_ms"] == 640000
    assert len(model.detect_calls[0]["audio"]) == 30 * 16000
    model.detect_calls.clear()
    assert (
        resolve_language(model, audio, Settings(source_language="en"), 0, speech)[0]
        == "en"
    )
    assert model.detect_calls == []


def test_ambiguous_and_no_speech_fail():
    model = Model(score=0.4)
    with pytest.raises(ValueError, match="--source-language"):
        resolve_language(
            model,
            np.zeros(100 * 16000),
            Settings(),
            0,
            [{"start": 0, "end": 100 * 16000}],
        )
    assert len(model.detect_calls) == 3
    with pytest.raises(ValueError, match="--source-language"):
        resolve_language(Model(), np.zeros(16000), Settings(), 0, [])
    with pytest.raises(ValueError, match="unsupported"):
        resolve_language(
            Model(), np.zeros(16000), Settings(source_language="ko"), 0, []
        )


def test_srt_and_rounding():
    assert milliseconds(1.2345) == 1235
    assert parse_time("00:10:00.125") == 600125
    assert parse_time("1.5") == 1500
    for value in ("-1", "NaN", "00:61:00", "00:00"):
        with pytest.raises(ValueError):
            parse_time(value)
    text = compose(
        [{"id": "cue", "start_ms": 600001, "end_ms": 601234, "text": "Hello!"}], 700000
    )
    assert "00:10:00,001 --> 00:10:01,234" in text
    assert compose([], 10) == ""
    with pytest.raises(ValueError):
        compose([{"id": "cue", "start_ms": 3, "end_ms": 2, "text": "bad"}], 10)


@pytest.fixture
def silence(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "silence \u65e5 space.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "3",
            str(path),
        ],
        check=True,
    )
    return path


def test_real_silence_exports_without_model(silence, tmp_path):
    def never_load(*args):
        pytest.fail("Silent input must not require a speech model")

    directory = generate(
        silence, Settings(output_dir=tmp_path / "out"), model_loader=never_load
    )
    assert (directory / "subtitles.en.srt").read_text() == ""
    assert json.loads((directory / "manifest.json").read_text())["state"] == "empty"


@pytest.mark.parametrize(
    "requested,resolved,task",
    [
        ("ja", "ja", "translate"),
        ("en", "en", "transcribe"),
        ("auto", "en", "transcribe"),
    ],
)
def test_service_routing_offsets_and_new_jobs(
    silence, tmp_path, monkeypatch, requested, resolved, task
):
    monkeypatch.setattr(
        "faster_whisper.vad.get_speech_timestamps",
        lambda audio: [{"start": 0, "end": len(audio)}],
    )
    model = Model(language=resolved)
    settings = Settings(output_dir=tmp_path / "out", source_language=requested)

    def loader(*args):
        return (
            model,
            {"device": "cpu", "compute_type": "int8", "model_revision": "test"},
        )

    first = generate(
        silence, settings, start_ms=1000, duration_ms=1000, model_loader=loader
    )
    subtitle = first / "subtitles.en.srt"
    assert "00:00:01,002 --> 00:00:01,900" in subtitle.read_text()
    assert model.transcribe_calls[-1]["task"] == task
    assert model.transcribe_calls[-1]["language"] == resolved
    atomic_text(subtitle, "manual edit")
    second = generate(
        silence, settings, start_ms=1000, duration_ms=1000, model_loader=loader
    )
    assert second != first
    assert subtitle.read_text() == "manual edit"
    assert len(model.detect_calls) == (1 if requested == "auto" else 0)


def test_delayed_audio_timeline(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    from faster_whisper.audio import decode_audio

    source = tmp_path / "delayed.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=16x16:duration=5",
            "-itsoffset",
            "2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=16000",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    info = inspect_media(source)
    track = select_track(info, "auto")
    assert float(track["start_time"]) == 2
    full = tmp_path / "full.wav"
    sample = tmp_path / "sample.wav"
    extract_audio(source, track, info, full)
    extract_audio(source, track, info, sample, 1000, 2500)
    audio = decode_audio(str(full))
    clip = decode_audio(str(sample))
    assert np.max(np.abs(audio[:31000])) == 0
    assert np.max(np.abs(audio[33000:])) > 0.01
    np.testing.assert_allclose(clip, audio[16000:56000], atol=0.0001)


def test_nonzero_container_origin(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    from faster_whisper.audio import decode_audio

    source = tmp_path / "origin.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=16000",
            "-c:a",
            "pcm_s16le",
            "-output_ts_offset",
            "7",
            str(source),
        ],
        check=True,
    )
    info = inspect_media(source)
    assert float(info["format"]["start_time"]) == 7
    destination = tmp_path / "sample.wav"
    extract_audio(source, select_track(info, "auto"), info, destination, 500, 1000)
    audio = decode_audio(str(destination))
    assert len(audio) == 16000
    assert np.max(np.abs(audio[:1000])) > 0.01


def test_offline_loader_and_device_validation(tmp_path, monkeypatch):
    from local_subs.inference import load_model

    calls = []

    def cached(*args, **kwargs):
        calls.append(kwargs)
        return str(tmp_path)

    monkeypatch.setattr("faster_whisper.utils.download_model", cached)
    with pytest.raises(ValueError, match="missing model.bin"):
        load_model(Settings(), lambda _: None)
    assert calls[0]["local_files_only"] is True
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / name).touch()
    monkeypatch.setattr(
        "ctranslate2.get_supported_compute_types", lambda device: {"int8"}
    )
    with pytest.raises(ValueError, match="unsupported"):
        load_model(Settings(device="cpu", compute_type="float16"), lambda _: None)


def test_atomic_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "artifact.json"
    path.write_text("previous")

    def fail_replace(*args):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("local_subs.jobs.os.replace", fail_replace)
    with pytest.raises(OSError):
        atomic_text(path, "new")
    assert path.read_text() == "previous"
