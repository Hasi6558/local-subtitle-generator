"""Bounded WAV access, ownership intervals and conservative boundary reconciliation."""

import re
import wave
from difflib import SequenceMatcher

import numpy as np


def wav_info(path):
    with wave.open(str(path), "rb") as reader:
        if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) != (
            1,
            2,
            16000,
        ):
            raise ValueError("Prepared audio must be mono PCM16 at 16 kHz")
        return reader.getnframes() * 1000 // 16000


def read_audio(path, start_ms, end_ms):
    with wave.open(str(path), "rb") as reader:
        reader.setpos(min(start_ms * 16, reader.getnframes()))
        return (
            np.frombuffer(
                reader.readframes((end_ms - start_ms) * 16), dtype="<i2"
            ).astype(np.float32)
            / 32768
        )


def plan_chunks(path, start_ms, end_ms, chunk_ms, overlap_ms):
    """Prefer a quiet 200 ms frame within 2 s of a nominal cut."""
    boundaries = [start_ms]
    while boundaries[-1] + chunk_ms < end_ms:
        target = boundaries[-1] + chunk_ms
        left, right = (
            max(boundaries[-1] + 1000, target - 2000),
            min(end_ms - 1000, target + 2000),
        )
        cut = target
        if right > left:
            audio = read_audio(path, left - start_ms, right - start_ms)
            scores = [
                (
                    float(np.sqrt(np.mean(audio[i : i + 3200] ** 2))),
                    left + i // 16 + 100,
                )
                for i in range(0, max(0, len(audio) - 3199), 3200)
            ]
            quiet = [
                (abs(position - target), position)
                for score, position in scores
                if score < 0.003
            ]
            if quiet:
                cut = min(quiet)[1]
        boundaries.append(cut)
    boundaries.append(end_ms)
    return [
        {
            "id": f"chunk_{i:05d}",
            "owner_start_ms": a,
            "owner_end_ms": b,
            "context_start_ms": max(start_ms, a - overlap_ms),
            "context_end_ms": min(end_ms, b + overlap_ms),
        }
        for i, (a, b) in enumerate(zip(boundaries, boundaries[1:]))
    ]


def normalized(text):
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def stitch(chunks, results, start_ms, end_ms):
    """Select by ownership midpoint; deduplicate only overlapping adjacent chunks."""
    selected, report, raw = [], [], []
    chunk_order = {chunk["id"]: index for index, chunk in enumerate(chunks)}
    for chunk, segments in zip(chunks, results):
        for segment in segments:
            raw.append(segment)
            midpoint = (segment["start_ms"] + segment["end_ms"]) / 2
            if chunk["owner_start_ms"] <= midpoint < chunk["owner_end_ms"]:
                selected.append(dict(segment))
    selected.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
    cues = []
    for segment in selected:
        start, end = max(start_ms, segment["start_ms"]), min(end_ms, segment["end_ms"])
        if not segment["text"].strip() or start >= end:
            report.append(
                {"issue": "invalid_or_empty_segment", "segment_ids": [segment["id"]]}
            )
            continue
        duplicate = None
        for previous in reversed(cues):
            if previous["end_ms"] <= start:
                continue
            if (
                abs(
                    chunk_order[previous["source_chunk"]]
                    - chunk_order[segment["source_chunk"]]
                )
                != 1
            ):
                continue
            overlap = min(previous["end_ms"], end) - max(previous["start_ms"], start)
            if (
                overlap > 0
                and SequenceMatcher(
                    None, normalized(previous["text"]), normalized(segment["text"])
                ).ratio()
                >= 0.85
            ):
                duplicate = previous
                break
        if duplicate:
            duplicate["source_segment_ids"].append(segment["id"])
            duplicate["flags"].append("boundary_duplicate_reconciled")
            report.append(
                {
                    "issue": "boundary_duplicate",
                    "segment_ids": duplicate["source_segment_ids"][:],
                }
            )
            continue
        flags = (
            ["clipped_to_playable_range"]
            if (start, end) != (segment["start_ms"], segment["end_ms"])
            else []
        )
        cues.append(
            {
                "id": f"cue_{len(cues) + 1:06d}",
                "source_segment_ids": [segment["id"]],
                "source_chunk": segment["source_chunk"],
                "start_ms": start,
                "end_ms": end,
                "text": segment["text"].strip(),
                "flags": flags,
                "edit_version": 0,
                "origin": "model",
            }
        )
    for left, right in zip(chunks, chunks[1:]):
        boundary = left["owner_end_ms"]
        region_start, region_end = right["context_start_ms"], left["context_end_ms"]
        alternatives = [
            s
            for s in raw
            if s["source_chunk"] in (left["id"], right["id"])
            and s["end_ms"] >= region_start
            and s["start_ms"] <= region_end
        ]
        nearby = [
            c
            for c in cues
            if c["end_ms"] >= region_start and c["start_ms"] <= region_end
        ]
        issues = ["boundary_review"]
        if any(
            a["source_chunk"] != b["source_chunk"]
            and min(a["end_ms"], b["end_ms"]) > max(a["start_ms"], b["start_ms"])
            and SequenceMatcher(
                None, normalized(a["text"]), normalized(b["text"])
            ).ratio()
            < 0.6
            for i, a in enumerate(alternatives)
            for b in alternatives[i + 1 :]
        ):
            issues.append("boundary_conflict")
        if alternatives and not nearby:
            issues.append("suspected_boundary_omission")
        if any(
            abs(s["end_ms"] - left["context_end_ms"]) <= 100
            or abs(s["start_ms"] - right["context_start_ms"]) <= 100
            for s in alternatives
        ):
            issues.append("possible_truncated_phrase")
        for cue in nearby:
            cue["flags"].extend(issues)
        report.append(
            {
                "boundary_ms": boundary,
                "issues": issues,
                "alternative_segment_ids": [s["id"] for s in alternatives],
                "cue_ids": [c["id"] for c in nearby],
            }
        )
    return raw, cues, report
