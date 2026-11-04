import type { Cue } from "./types";
export function clock(ms: number): string {
  const value = Math.max(0, Math.round(ms));
  return `${String(Math.floor(value / 3600000)).padStart(2, "0")}:${String(Math.floor(value / 60000) % 60).padStart(2, "0")}:${String(Math.floor(value / 1000) % 60).padStart(2, "0")}.${String(value % 1000).padStart(3, "0")}`;
}
export function parseClock(text: string): number {
  if (!text.trim()) return NaN;
  const parts = text.trim().split(":");
  if (!(
    (parts.length === 1 && /^\d+(\.\d+)?$/.test(parts[0])) ||
    (parts.length === 3 && /^\d+:\d{2}:\d{2}(\.\d{1,3})?$/.test(text))
  ))
    return NaN;
  const numbers = parts.map(Number);
  if (parts.length === 3 && (numbers[1] >= 60 || numbers[2] >= 60)) return NaN;
  const seconds = numbers.reduce((total, number) => total * 60 + number, 0);
  return Number.isFinite(seconds) ? Math.round(seconds * 1000) : NaN;
}
export function validateDraft(cues: Cue[]): string | null {
  let previous = -1;
  for (const cue of cues) {
    if (!cue.text.trim()) return "Subtitle text cannot be empty.";
    if (
      !Number.isInteger(cue.start_ms) ||
      !Number.isInteger(cue.end_ms) ||
      cue.start_ms < 0 ||
      cue.end_ms <= cue.start_ms
    )
      return "Set valid start and end times; the end must be after the start.";
    if (cue.start_ms < previous) return "Cue start times must stay in order.";
    previous = cue.start_ms;
  }
  return null;
}
export function wordBoundary(text: string): number {
  const spaces = [...text.matchAll(/\s+/g)]
    .map((item) => item.index!)
    .filter((index) => index > 0 && index < text.trimEnd().length);
  return (
    spaces.sort(
      (a, b) => Math.abs(a - text.length / 2) - Math.abs(b - text.length / 2),
    )[0] ?? -1
  );
}
export function splitCue(
  cues: Cue[],
  index: number,
  cursor: number,
  at: number,
): Cue[] {
  const cue = cues[index];
  if (!(cue.start_ms < at && at < cue.end_ms))
    throw new Error("Choose a split time inside this cue.");
  if (
    cursor <= 0 ||
    cursor >= cue.text.length ||
    (!/\s/.test(cue.text[cursor - 1]) && !/\s/.test(cue.text[cursor]))
  )
    throw new Error("Place the text cursor at a boundary between words.");
  const left = cue.text.slice(0, cursor).trim(),
    right = cue.text.slice(cursor).trim();
  if (!left || !right) throw new Error("Both split cues need text.");
  const flags = [...new Set([...(cue.flags || []), "manual_timing"])];
  return [
    ...cues.slice(0, index),
    { ...cue, text: left, end_ms: at, flags },
    {
      ...cue,
      id: `manual_${crypto.randomUUID()}`,
      text: right,
      start_ms: at,
      flags,
    },
    ...cues.slice(index + 1),
  ];
}
export function mergeCue(cues: Cue[], index: number): Cue[] {
  if (index < 0 || index + 1 >= cues.length)
    throw new Error("There is no next cue to merge.");
  const left = cues[index],
    right = cues[index + 1];
  return [
    ...cues.slice(0, index),
    {
      ...left,
      text: `${left.text.trim()} ${right.text.trim()}`,
      start_ms: Math.min(left.start_ms, right.start_ms),
      end_ms: Math.max(left.end_ms, right.end_ms),
      source_segment_ids: [
        ...new Set([
          ...(left.source_segment_ids || []),
          ...(right.source_segment_ids || []),
        ]),
      ],
      flags: [
        ...new Set([
          ...(left.flags || []),
          ...(right.flags || []),
          "manual_timing",
        ]),
      ],
    },
    ...cues.slice(index + 2),
  ];
}
export function sameEdits(a: Cue[], b: Cue[]): boolean {
  return (
    a.length === b.length &&
    a.every((cue, index) =>
      ["id", "start_ms", "end_ms", "text"].every(
        (key) => cue[key as keyof Cue] === b[index][key as keyof Cue],
      ),
    )
  );
}
