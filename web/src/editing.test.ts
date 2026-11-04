import { describe, expect, it } from "vitest";
import {
  clock,
  mergeCue,
  parseClock,
  splitCue,
  validateDraft,
  wordBoundary,
} from "./editing";
import type { Cue } from "./types";
const cue: Cue = {
  id: "one",
  start_ms: 1000,
  end_ms: 5000,
  text: "Hello world again.",
  source_segment_ids: ["seg1"],
};
describe("manual subtitle operations", () => {
  it("preserves original offsets and rejects malformed clocks", () => {
    expect(clock(600123)).toBe("00:10:00.123");
    expect(parseClock("00:10:00.123")).toBe(600123);
    expect(parseClock("1.2345")).toBe(1235);
    for (const value of ["", "-1", "NaN", "00:60:00", "00:00", "0x10"])
      expect(parseClock(value)).toBeNaN();
  });
  it("splits only at an explicit valid word/time boundary, preserving all words and provenance", () => {
    const result = splitCue([cue], 0, 5, 3000);
    expect(result.map((item) => item.text).join(" ")).toBe(cue.text);
    expect(result[0].end_ms).toBe(3000);
    expect(result[1].start_ms).toBe(3000);
    expect(result[1].source_segment_ids).toEqual(["seg1"]);
    expect(cue.end_ms).toBe(5000);
    expect(() => splitCue([cue], 0, 2, 3000)).toThrow("word");
    expect(() => splitCue([cue], 0, 5, 6000)).toThrow("time");
  });
  it("merges without deleting repeated text and retains source links", () => {
    const next = {
      ...cue,
      id: "two",
      start_ms: 6000,
      end_ms: 8000,
      source_segment_ids: ["seg2"],
    };
    const result = mergeCue([cue, next], 0);
    expect(result[0].text).toBe(`${cue.text} ${cue.text}`);
    expect(result[0].end_ms).toBe(8000);
    expect(result[0].source_segment_ids).toEqual(["seg1", "seg2"]);
  });
  it("flags invalid drafts instead of discarding text", () => {
    expect(validateDraft([{ ...cue, text: "" }])).toContain("empty");
    expect(validateDraft([{ ...cue, end_ms: 900 }])).toContain("end");
    expect(wordBoundary("singleword")).toBe(-1);
  });
  it("retains source text across manual splits and merges without inventing word alignment", () => {
    const source = { ...cue, source_text: "元の会話", source_language: "ja" };
    const split = splitCue([source], 0, 5, 3000);
    expect(split[1].source_text).toBe(source.source_text);
    expect(mergeCue(split, 0)[0].source_text).toBe(source.source_text);
    const next = {
      ...source,
      id: "two",
      source_text: "次の会話",
      source_segment_ids: ["seg2"],
      start_ms: 6000,
      end_ms: 8000,
    };
    expect(mergeCue([source, next], 0)[0].source_text).toBe(
      "元の会話\n次の会話",
    );
  });
});
