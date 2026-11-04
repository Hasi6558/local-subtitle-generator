"""Temporal comparison of independent jobs; no automatic meaning verdict."""

from pathlib import Path


def compatible(first, second):
    def key(manifest):
        return (
            str(
                Path(
                    manifest.get("source_path") or manifest["source"]["path"]
                ).resolve()
            ),
            manifest["audio_stream"],
            manifest["sample_start_ms"],
            manifest["sample_duration_ms"],
        )

    if key(first) != key(second):
        raise ValueError(
            "Comparison requires the same media, audio track and sample range"
        )


def compare(first, second, first_cues, second_cues):
    compatible(first, second)

    def summary(job):
        return {
            k: job.get(k)
            for k in (
                "job_id",
                "settings",
                "elapsed_seconds",
                "stage_seconds",
                "qc_summary",
                "resolved_source_language",
            )
        }

    return {
        "first": summary(first),
        "second": summary(second),
        "human_meaning": "unverified",
        "rows": [
            {
                "cue": cue,
                "matches": [
                    other
                    for other in second_cues
                    if min(cue["end_ms"], other["end_ms"])
                    > max(cue["start_ms"], other["start_ms"])
                ],
            }
            for cue in first_cues
        ],
        "unmatched_second": [
            other
            for other in second_cues
            if not any(
                min(cue["end_ms"], other["end_ms"])
                > max(cue["start_ms"], other["start_ms"])
                for cue in first_cues
            )
        ],
    }
