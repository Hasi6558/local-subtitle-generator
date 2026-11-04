export type Cue = {
  id: string;
  start_ms: number;
  end_ms: number;
  text: string;
  flags?: string[];
  source_segment_ids?: string[];
  origin?: string;
  edit_version?: number;
};
export type Settings = {
  source_language: string;
  speech_model: string;
  device: string;
  compute_type?: string | null;
  vad?: boolean;
  chunk_seconds?: number;
  overlap_seconds?: number;
};
export type Job = {
  job_id: string;
  state: string;
  stage?: string;
  source_path?: string;
  source?: { path: string };
  settings: Settings;
  audio_stream: number;
  parent_job_id?: string | null;
  sample_start_ms: number;
  sample_duration_ms: number;
  resolved_source_language?: string | null;
  elapsed_seconds?: number;
  cue_count?: number;
  chunks?: { state?: string; owner_end_ms: number }[];
  error?: string | { message: string; retry_hint?: string };
};
export type Issue = {
  code: string;
  cue_id?: string | null;
  severity: string;
  message: string;
};
export type QC = {
  issues: Issue[];
  error_count: number;
  warning_count: number;
};
export type Preview = {
  state: string;
  cache_key: string;
  mode: string;
  error?: string;
};
export type Seed = {
  path: string;
  settings: Settings;
  audio_stream: number;
  start_ms: number;
  duration_ms: number;
  parent_job_id?: string;
};
export const sourcePath = (job: Job) =>
  job.source_path || job.source?.path || "";
export const fileName = (path: string) => path.split(/[\\/]/).pop() || path;
