"""Formatting-only exports reuse stored inference and never overwrite edits."""

from pathlib import Path
from uuid import uuid4

from local_subs.jobs import atomic_text, fingerprint, write_json
from local_subs.policy import FormattingPolicy
from local_subs.quality import (
    assess,
    compose_vtt,
    format_cues,
    read_cues,
    speech_regions,
)
from local_subs.subtitles import compose


def write_quality_artifacts(revision, cues, playable_end_ms, policy=None, speech=None):
    policy = policy or FormattingPolicy()
    revision.mkdir(parents=True, exist_ok=True)
    original_report = assess(cues, policy, playable_end_ms)
    if original_report["error_count"]:
        write_json(revision / "qc.json", original_report)
        raise ValueError(
            f"Structural cue errors prevent export; see {revision / 'qc.json'}"
        )
    formatted = format_cues(cues, policy)
    report = assess(formatted, policy, playable_end_ms, speech)
    for cue in formatted:
        flags = [
            issue["code"]
            for issue in report["issues"]
            if issue["cue_id"] == str(cue["id"])
        ]
        cue["flags"] = sorted(set(cue.get("flags", []) + flags))
    srt_text, vtt_text = (
        compose(formatted, playable_end_ms),
        compose_vtt(formatted, playable_end_ms),
    )
    write_json(revision / "formatted_cues.json", formatted)
    write_json(revision / "qc.json", report)
    atomic_text(revision / "subtitles.en.srt", srt_text)
    atomic_text(revision / "subtitles.en.vtt", vtt_text)
    return report


def export_job(job_id, root, cues_path=None, policy=None, check_coverage=True):
    from local_subs.resumable import job_directory, read_manifest
    from local_subs.worker import worker_lock

    directory = job_directory(root, job_id)
    with worker_lock(root, job_id):
        manifest = read_manifest(directory)
        if manifest["state"] not in ("completed", "empty"):
            raise ValueError("Complete or resume this job before exporting")
        source = cues_path or Path(manifest["artifacts"]["generated_cues.json"])
        cues = read_cues(source)
        audio = manifest.get("prepared_audio", {}).get("path") or manifest.get(
            "artifacts", {}
        ).get("audio.wav")
        speech = None
        if check_coverage and audio and Path(audio).is_file():
            speech = speech_regions(Path(audio), manifest["sample_start_ms"])
        end = manifest["sample_start_ms"] + manifest["sample_duration_ms"]
        revision = directory / "exports" / uuid4().hex
        revision.mkdir(parents=True)
        write_json(revision / "input_cues.json", cues)
        report = write_quality_artifacts(revision, cues, end, policy, speech)
        write_json(
            revision / "export_manifest.json",
            {
                "schema_version": 1,
                "job_manifest": manifest,
                "source_cues": str(source.resolve()),
                "source_sha256": fingerprint(source),
                "policy": report["policy"],
                "timing_policy": "original segment timings retained; no translated word alignment",
                "coverage_requested": check_coverage,
            },
        )
        return revision, report
