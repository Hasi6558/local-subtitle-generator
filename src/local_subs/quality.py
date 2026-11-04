"""Readability and coverage hints; no inferred English word alignment."""

import copy
import html
import json
import textwrap
from collections import Counter

import srt
import webvtt

from local_subs.chunks import normalized, read_audio, wav_info
from local_subs.policy import FormattingPolicy

READABILITY_FLAGS = {
    "short_duration",
    "long_duration",
    "too_many_lines",
    "long_line",
    "reading_speed",
    "timestamp_conflict",
    "suspicious_repetition",
}


def format_cues(cues, policy):
    output = copy.deepcopy(cues)
    for cue in output:
        text = cue.get("text")
        if isinstance(text, str):
            cue["text"] = "\n".join(
                textwrap.wrap(
                    " ".join(text.split()),
                    width=policy.line_width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
            # Never truncate to max_lines or invent split times for translated words.
        cue["flags"] = [
            flag for flag in cue.get("flags", []) if flag not in READABILITY_FLAGS
        ]
    return output


def assess(cues, policy=None, playable_end_ms=None, speech=None):
    policy = policy or FormattingPolicy()
    if not isinstance(cues, list):
        raise ValueError("Cue JSON must be a list of objects")
    issues, valid, ids = [], [], set()

    def add(code, message, cue_id=None, severity="warning", **details):
        issues.append(
            {
                "code": code,
                "severity": severity,
                "cue_id": cue_id,
                "message": message,
                **details,
            }
        )

    previous_start, previous_end, previous_id = -1, -1, None
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            add(
                "invalid_record",
                "Replace this entry with a cue object",
                str(index),
                "error",
            )
            continue
        identity = str(cue.get("id", index))
        if not isinstance(cue.get("id"), str) or not cue.get("id"):
            add("invalid_id", "Provide a nonempty string cue ID", identity, "error")
        if identity in ids:
            add("duplicate_id", "Assign a unique cue ID", identity, "error")
        ids.add(identity)
        start, end, text = cue.get("start_ms"), cue.get("end_ms"), cue.get("text")
        if type(start) is not int or type(end) is not int or not (0 <= start < end):
            add(
                "invalid_timing",
                "Set integer milliseconds with 0 <= start < end",
                identity,
                "error",
            )
            continue
        if playable_end_ms is not None and end > playable_end_ms:
            add(
                "outside_playable_range",
                "Move the cue inside the playable range",
                identity,
                "error",
            )
        if start < previous_start:
            add(
                "unordered_cue",
                "Order cues by their start timestamps",
                identity,
                "error",
            )
        if start < previous_end:
            add("timestamp_conflict", f"Review overlap with {previous_id}", identity)
        previous_start = start
        if end > previous_end:
            previous_end, previous_id = end, identity
        if not isinstance(text, str) or not text.strip():
            add("empty_text", "Provide nonempty subtitle text", identity, "error")
            continue
        valid.append(cue)
        duration = end - start
        if duration < policy.min_duration_ms:
            add(
                "short_duration",
                "Review this short display duration",
                identity,
                duration_ms=duration,
            )
        if duration > policy.max_duration_ms:
            add(
                "long_duration",
                "Review timing; translated English words have no exact acoustic alignment",
                identity,
                duration_ms=duration,
            )
        lines = text.splitlines()
        if len(lines) > policy.max_lines:
            add(
                "too_many_lines",
                "Review or split this cue manually; text and timings were retained",
                identity,
                line_count=len(lines),
            )
        if any(len(line) > policy.line_width for line in lines):
            add(
                "long_line",
                "Review this long line or unbreakable word; text was retained",
                identity,
            )
        cps = len(" ".join(text.split())) / (duration / 1000)
        if cps > policy.max_cps:
            add(
                "reading_speed",
                "Review text density or timing",
                identity,
                characters_per_second=round(cps, 2),
            )
        flags = cue.get("flags", [])
        if not isinstance(flags, list) or any(
            not isinstance(flag, str) for flag in flags
        ):
            add("invalid_flags", "Flags must be a list of strings", identity, "error")
        else:
            for flag in sorted(set(flags)):
                if not any(
                    issue["cue_id"] == identity and issue["code"] == flag
                    for issue in issues
                ):
                    explanation = {
                        "unresolved_name_or_term": "Check this possible name/term against the source; the katakana heuristic also flags ordinary loanwords and misses some names",
                        "glossary_review": "A supplied glossary rendering was not found in the translation; review terminology against the source",
                    }.get(flag, "Review the preserved inference/boundary flag")
                    add(flag, explanation, identity)
    for index, cue in enumerate(valid):
        text = normalized(cue["text"])
        if text and any(
            normalized(p["text"]) == text
            and 0 <= cue["start_ms"] - p["end_ms"] <= 30000
            for p in valid[max(0, index - 3) : index]
        ):
            add(
                "suspicious_repetition",
                "Repeated nearby text can be legitimate; compare against the audio",
                str(cue.get("id", index)),
            )
    coverage = {
        "status": "unavailable",
        "reason": "No speech regions supplied; not a completeness verdict",
    }
    if speech is not None:
        speech_ms, covered_ms = 0, 0
        for region in speech:
            start, end = region["start_ms"], region["end_ms"]
            speech_ms += end - start
            intervals = sorted(
                (max(start, c["start_ms"]), min(end, c["end_ms"]))
                for c in valid
                if c["end_ms"] > start and c["start_ms"] < end
            )
            position = start
            for a, b in intervals:
                covered_ms += max(0, b - max(a, position))
                position = max(position, b)
            if not intervals and end - start >= 500:
                add(
                    "speech_without_output",
                    "VAD speech region has no cue; listen for missing dialogue",
                    start_ms=start,
                    end_ms=end,
                )
        coverage = {
            "status": "heuristic",
            "speech_ms": speech_ms,
            "covered_speech_ms": covered_ms,
            "coverage_ratio": round(covered_ms / speech_ms, 4) if speech_ms else None,
            "note": "VAD and temporal overlap cannot prove dialogue completeness or translation accuracy",
        }
    counts = Counter(issue["code"] for issue in issues)
    errors = sum(i["severity"] == "error" for i in issues)
    return {
        "schema_version": 1,
        "policy": policy.model_dump(),
        "cue_count": len(cues),
        "error_count": errors,
        "warning_count": len(issues) - errors,
        "issue_counts": dict(counts),
        "issues": issues,
        "coverage": coverage,
        "human_review": {
            "meaning": "unverified",
            "timing": "unverified",
            "readability": "unverified",
        },
    }


def speech_regions(audio_path, offset_ms=0):
    from faster_whisper.vad import get_speech_timestamps

    regions = []
    duration = wav_info(audio_path)
    for start in range(0, duration, 300000):
        audio = read_audio(audio_path, start, min(duration, start + 300000))
        for region in get_speech_timestamps(audio):
            a, b = (
                offset_ms + start + region["start"] // 16,
                offset_ms + start + region["end"] // 16,
            )
            if regions and a <= regions[-1]["end_ms"]:
                regions[-1]["end_ms"] = max(regions[-1]["end_ms"], b)
            else:
                regions.append({"start_ms": a, "end_ms": b})
    return regions


def read_cues(path):
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        cues = json.loads(text)
        if not isinstance(cues, list):
            raise ValueError("Cue JSON must be a list")
        return cues
    if path.suffix.lower() == ".srt":
        return [
            {
                "id": str(c.index),
                "start_ms": round(c.start.total_seconds() * 1000),
                "end_ms": round(c.end.total_seconds() * 1000),
                "text": c.content,
            }
            for c in srt.parse(text)
        ]
    if path.suffix.lower() == ".vtt":
        captions = webvtt.from_string(text, strict=True)
        from local_subs.media import parse_time

        return [
            {
                "id": c.identifier or str(i),
                "start_ms": parse_time(c.start),
                "end_ms": parse_time(c.end),
                "text": html.unescape(c.raw_text),
            }
            for i, c in enumerate(captions)
        ]
    raise ValueError("Expected .srt, .vtt or cue-list .json")


def vtt_time(value):
    hours, remainder = divmod(value, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, ms = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{ms:03}"


def compose_vtt(cues, playable_end_ms):
    from local_subs.subtitles import compose

    compose(cues, playable_end_ms)  # Same structural and ordering contract as SRT.
    blocks = ["WEBVTT"]
    for index, cue in enumerate(cues, 1):
        blocks.append(
            f"{index}\n{vtt_time(cue['start_ms'])} --> {vtt_time(cue['end_ms'])}\n{html.escape(cue['text'], quote=False)}"
        )
    result = "\n\n".join(blocks) + "\n\n"
    restored = list(webvtt.from_string(result, strict=True))
    if len(restored) != len(cues):
        raise ValueError("VTT round-trip lost cues")
    for original, parsed in zip(cues, restored):
        if (
            vtt_time(original["start_ms"]),
            vtt_time(original["end_ms"]),
            original["text"],
        ) != (parsed.start, parsed.end, html.unescape(parsed.raw_text)):
            raise ValueError("VTT round-trip changed cue data")
    return result
