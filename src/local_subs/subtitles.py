"""Structural validation and SRT serialization, independent of inference."""

from datetime import timedelta

import srt


def compose(cues, playable_end_ms):
    previous = -1
    subtitles = []
    for index, cue in enumerate(cues, 1):
        start, end = cue["start_ms"], cue["end_ms"]
        if not (0 <= start < end <= playable_end_ms) or start < previous:
            raise ValueError(f"Invalid cue timing: {cue['id']}")
        previous = start
        if not cue["text"].strip():
            raise ValueError(f"Empty cue text: {cue['id']}")
        subtitles.append(
            srt.Subtitle(
                index,
                timedelta(milliseconds=start),
                timedelta(milliseconds=end),
                cue["text"],
            )
        )
    output = srt.compose(subtitles, reindex=False)
    restored = list(srt.parse(output))
    if len(restored) != len(cues):
        raise ValueError("SRT round-trip lost cues")
    for original, parsed in zip(subtitles, restored):
        if (original.start, original.end, srt.make_legal_content(original.content)) != (
            parsed.start,
            parsed.end,
            parsed.content,
        ):
            raise ValueError("SRT round-trip changed subtitle data")
    return output
