import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from local_subs.benchmark import benchmark
from local_subs.cli import app
from local_subs.config import Settings
from local_subs.exports import export_job, write_quality_artifacts
from local_subs.jobs import fingerprint, write_json
from local_subs.policy import FormattingPolicy
from local_subs.quality import assess, compose_vtt, format_cues, read_cues


def cue(text="Hello, world!", start=1000, end=3000, identity="cue1"):
    return {"id": identity, "start_ms": start, "end_ms": end, "text": text, "flags": []}


def test_format_preserves_words_times_and_inputs():
    text = "A long sentence, with punctuation. " * 5 + "unbreakableword" * 5
    original = [cue(text)]
    result = format_cues(original, FormattingPolicy(line_width=20))
    assert result[0]["text"].split() == text.split()
    assert result[0]["start_ms"] == 1000
    assert result[0]["end_ms"] == 3000
    assert original[0]["text"] == text
    report = assess(result, FormattingPolicy(line_width=20))
    assert {"long_line", "too_many_lines", "reading_speed"} <= report[
        "issue_counts"
    ].keys()
    assert report["human_review"]["meaning"] == "unverified"


def test_structural_errors_conflicts_and_repetition():
    cues = [
        cue(start=0, end=8000),
        cue(start=7000, end=9000, identity="cue2"),
        cue(start=9500, end=9800, identity="cue3"),
        cue(start=-1, identity="bad"),
    ]
    report = assess(cues, playable_end_ms=9700)
    assert report["error_count"] == 2
    assert {
        "timestamp_conflict",
        "suspicious_repetition",
        "long_duration",
        "short_duration",
        "invalid_timing",
        "outside_playable_range",
    } <= report["issue_counts"].keys()
    malformed = assess(
        [
            {"start_ms": True, "end_ms": 2000, "text": "bad"},
            cue(identity="x"),
            cue(identity="x"),
        ]
    )
    assert {"invalid_id", "invalid_timing", "duplicate_id"} <= malformed[
        "issue_counts"
    ].keys()


def test_coverage_is_heuristic_and_flags_missing_regions():
    report = assess(
        [cue(start=0, end=1000)],
        speech=[{"start_ms": 0, "end_ms": 2000}, {"start_ms": 3000, "end_ms": 4000}],
    )
    assert report["coverage"]["covered_speech_ms"] == 1000
    assert report["coverage"]["status"] == "heuristic"
    assert report["issue_counts"]["speech_without_output"] == 1
    assert assess([])["coverage"]["status"] == "unavailable"


def test_vtt_roundtrip_unicode_entities_and_offsets(tmp_path):
    original = [cue("A < B & 日本語 --> &amp;\nSecond line.", 3600001, 3602500)]
    text = compose_vtt(original, 4000000)
    path = tmp_path / "captions.vtt"
    path.write_text(text, encoding="utf-8")
    assert "01:00:00.001 --> 01:00:02.500" in text
    restored = read_cues(path)
    assert restored[0]["text"] == original[0]["text"]
    assert restored[0]["start_ms"] == original[0]["start_ms"]
    assert compose_vtt([], 1).startswith("WEBVTT")


def test_validate_cli_malformed_and_warnings(tmp_path):
    runner = CliRunner()
    path = tmp_path / "bad.vtt"
    path.write_text("WEBVTT\n\n00:00:bad --> 00:00:03.000\nWords\n")
    report = tmp_path / "report.json"
    assert (
        runner.invoke(app, ["validate", str(path), "--report", str(report)]).exit_code
        == 1
    )
    assert json.loads(report.read_text())["issues"][0]["code"] == "parse_error"
    path = tmp_path / "valid.json"
    write_json(path, [cue("Words " * 20, end=1100)])
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 0  # readability warnings are not structural errors
    assert "reading_speed" in result.stdout


def test_export_preserves_input_and_edits_without_inference(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "local_subs.inference.load_model",
        lambda *args: pytest.fail("Export must not infer"),
    )
    job_id = "a" * 32
    directory = tmp_path / job_id
    directory.mkdir()
    source = directory / "generated_cues.json"
    write_json(source, [cue("A sentence with many words to wrap across lines. " * 3)])
    write_json(
        directory / "manifest.json",
        {
            "job_id": job_id,
            "state": "completed",
            "sample_start_ms": 0,
            "sample_duration_ms": 10000,
            "artifacts": {"generated_cues.json": str(source)},
        },
    )
    before = fingerprint(source)
    first, report = export_job(
        job_id, tmp_path, policy=FormattingPolicy(line_width=20), check_coverage=False
    )
    assert (first / "subtitles.en.vtt").exists()
    assert report["error_count"] == 0
    (first / "subtitles.en.srt").write_text("manual edits")
    second, _ = export_job(
        job_id, tmp_path, policy=FormattingPolicy(line_width=30), check_coverage=False
    )
    assert second != first
    assert (first / "subtitles.en.srt").read_text() == "manual edits"
    assert fingerprint(source) == before
    assert (
        json.loads((second / "export_manifest.json").read_text())["source_sha256"]
        == before
    )


def test_export_reports_structural_errors(tmp_path):
    with pytest.raises(ValueError, match="Structural cue errors"):
        write_quality_artifacts(tmp_path, [cue(start=3, end=2)], 100)
    assert json.loads((tmp_path / "qc.json").read_text())["error_count"] == 1
    assert not (tmp_path / "subtitles.en.srt").exists()


def test_policy_validation():
    with pytest.raises(ValueError):
        FormattingPolicy(min_duration_ms=8000, max_duration_ms=1000)
    assert (
        Settings.model_validate(
            {"formatting": {"line_width": 30}}
        ).formatting.line_width
        == 30
    )


def test_benchmark_is_serial_and_records_failures(tmp_path):
    media = tmp_path / "clip.mp4"
    media.touch()
    requests = []

    def run(arguments, **kwargs):
        assert isinstance(arguments, list)
        assert kwargs.get("check") is False
        request = json.loads(Path(arguments[-1]).read_text())
        requests.append(request)
        write_json(
            Path(request["response"]),
            [{"status": "failed", "error": "model not cached"}],
        )
        return SimpleNamespace(returncode=0)

    directory, report = benchmark(
        media,
        Settings(output_dir=tmp_path / "out"),
        ["small"],
        ["cpu"],
        [1, 5],
        runner=run,
    )
    assert len(requests) == 2
    assert [r["settings"]["beam_size"] for r in requests] == [1, 5]
    assert all(row["status"] == "failed" for row in report["results"])
    assert (directory / "benchmark.json").exists()


def test_new_policy_recomputes_old_quality_flags():
    original = [cue("Words " * 15)]
    original[0]["flags"] = ["too_many_lines", "boundary_review"]
    formatted = format_cues(original, FormattingPolicy(line_width=42, max_lines=10))
    report = assess(formatted, FormattingPolicy(max_lines=10))
    assert "too_many_lines" not in report["issue_counts"]
    assert "boundary_review" in report["issue_counts"]
