# Progress

## Phase 3: implemented; measured short-clip benchmark; acceptance gates open

Implemented: configurable wrapping/readability targets; structural and review QC;
preserved boundary flags; heuristic VAD coverage/missing-region checks; strict VTT
round-trip export; validate/export/benchmark commands; immutable formatting-only
revisions; formatting excluded from inference invalidation; stage performance
timers; isolated serial benchmarks with cold/warm model instances and peak RSS.

Verification on 4 November 2026:
- Default suite: 34 tests passed, 2 opt-in inference tests skipped. Includes text
  and timing preservation, unbreakable words, policy changes, invalid timing/IDs,
  overlap/repetition, speech without cues, Unicode/entity VTT round trips, strict
  malformed VTT handling, immutable exports without inference, benchmark failure
  recording, and unchanged inference reuse after formatting changes.
- Ruff, pip check and git diff --check passed. No cloud APIs or model downloads.
- Re-exported the existing 650.540-second Japanese dialogue result without model
  inference: 171 cues, zero structural errors, 70 review issues. New local revision:
  `outputs/phase2-dialogue/68bdb01e6e15497f8588b941e7b8ef62/exports/8f9b9432e25e4570a1cf1ad3579bc6ce`.
  Standalone VTT validation against duration passed. Prior raw/generated cues and
  exports remain unchanged. QC issues are retained for human review.
- Real short-clip benchmark: small/CPU/int8 on the same 36-second Japanese sample,
  beam 1 and 5, two repetitions each. Cold/warm total seconds: beam 1 10.757/8.635;
  beam 5 13.512/12.158. About 775 MB worker peak RSS; zero structural/readability
  issues on this short sample. Human ratings unverified. Detailed measured stage
  times, cache/memory scope, model revision and provisional preset are recorded in
  docs/BENCHMARKS.md and the local machine-readable report.
- Validated supplied full-movie reference SRT: 886 cues, zero structural errors,
  319 review warnings. This validates the reference, not generated movie subtitles.

Open gates: full-movie inference/resume/validate/export with human synchronization
review; semantic accuracy; representative whispers/music/overlap/dialects; medium,
GPU and a second source language. No quality winner or universal runtime estimate
is claimed. Keep v0.2 acceptance pending; QC cannot establish movie readiness.

Next action: user review and confirmation before Phase 4 local API/persistent worker.
Keep the plan's real-movie gate before a review UI; no UI/API work started here.

## Phase 2: implemented; real dialogue resume verified; movie inference pending

Implemented: disk-backed audio with bounded ownership/context chunks; quiet-cut
heuristic; chunk checkpoints and hash validation; immutable raw alternatives and
export revisions; boundary reconciliation/review report; durable states, failure
stages and retry hints; cancellation; local worker lock; jobs list/show, resume,
cancel and prepared-audio cleanup. Phase 1 remains available with --single-pass.

Verification on 4 November 2026:
- Deterministic/service suite: 23 tests passed. Optional inference tests are
  separately enabled with LOCAL_SUBS_TEST_MEDIA and LOCAL_SUBS_MODEL_CACHE.
  Default run skips 2 opt-in tests. The new real chunked cancel/resume test passed
  separately on the 36-second clip (1 passed, 1 deselected, 18.85 seconds).
- Covered interruption/resume without rewriting finished chunks; cancellation;
  changed input, track, model, requested/resolved language invalidation; extraction
  reuse; corrupted checkpoints; simulated disk-full failure; active-worker lock;
  cleanup/re-extraction; edit preservation; adjacent-only overlap deduplication;
  repeated phrases retained and boundary conflicts flagged.
- Ruff, pip check, and git diff --check passed.
- Real Japanese dialogue video: 650.540 seconds, small snapshot
  536b0662742c02347bc0e980a01041f333bce120, CPU/int8, beam 5, auto language, VAD on,
  chunk target 120 seconds, overlap 5 seconds. Resolved ja once. Six chunks produced
  171 English cues in 267.835 cumulative service seconds including the cancelled
  attempt. The first completed checkpoint's modification time stayed unchanged
  after resume. No repeated inference of that chunk.
- Job: `68bdb01e6e15497f8588b941e7b8ef62`, root `outputs/phase2-dialogue`.
  Local verification log: `outputs/phase2-real-check.log`.
- Final-code CLI resume reused all six checkpoints and generated a new immutable
  export: `exports/966fccc8b8ea4b68bd6734e54cf726a4/subtitles.en.srt` under that job.
- At a mid-run sample Windows reported working set 838,602,752 bytes and process
  peak working set 1,062,469,632 bytes. This is one observed process measurement,
  not a full-movie memory guarantee or a hardware-wide benchmark.
- Compared all five boundaries against independent 20-second Phase 1 baseline
  runs, using one cached small model. Boundary times: 119900, 239800, 359700,
  479600, 601500 ms. Outputs differed in wording/segmentation and every boundary
  was flagged for review; four also flagged possible truncation. Text similarity
  is not semantic accuracy. Local results: outputs/phase2-boundary-comparison.json.
- Full movie preparation: 7,378.389 seconds; global audio stream 0; generated
  236,108,526-byte disk WAV and 25 bounded chunk intervals. Deliberately stopped
  before model inference. Job `8ae5ffa300624bc49e7429e07d34bbf2`, root
  `outputs/phase2-movie`. Reference English SRT remains local and was not used as
  an automatic translation-quality verdict.

Open acceptance gates: full-length movie inference with observed memory and
human synchronization/no-drift review; source-language meaning review; boundary
conflicts/truncation review; medium/GPU and other-language evaluation. Do not
claim all Phase 2 acceptance checks passed or v0.2 ready. No media/reference
subtitles/transcripts/model weights were added to Git.

Next action: user review, then confirmation before Phase 3 readability, VTT,
validation/export commands and measured benchmarks. No Phase 3 implementation.

## Phase 1: CLI implementation delivered; human acceptance pending

Implemented: track selection using global indexes and normalized language tags;
mono 16 kHz extraction preserving movie/sample offsets; offline-only inference;
explicit/auto language resolution; English transcription routing; VAD control;
CPU/CUDA compute validation; atomic manifests, raw results, generated cues and
UTF-8 SRT; unique job directories; visible stages/positions/warnings.

Verification on 4 November 2026:
- `python -m pytest -q`: 16 passed, 1 optional inference test skipped by default.
  Covers track ambiguity, explicit/auto/English routing, leading silence and
  ambiguous detection, supported-language errors, silence with no model load,
  cached detection reuse, Unicode paths, offsets, half-up millisecond rounding,
  SRT round trips, delayed audio and nonzero container start, offline cache/device
  validation, atomic-write failure, and preservation of earlier user edits.
- `python -m ruff check src tests`, `python -m pip check`, `git diff --check`: passed.
- Opt-in `python -m pytest tests/test_model_integration.py -q` with
  LOCAL_SUBS_TEST_MEDIA and LOCAL_SUBS_MODEL_CACHE: 1 passed with real cached-model
  inference. An observed deprecated segment conversion was replaced with
  dataclasses.asdict before delivery.
- Model explicitly prepared with `local-subs models download small --model-cache models`.
  faster-whisper 1.2.1; CTranslate2 4.8.5; small snapshot
  `536b0662742c02347bc0e980a01041f333bce120`.
- User-provided Japanese coffee-ordering MP4: 36.177 seconds, global audio index 1,
  CPU/int8, beam size 5, VAD enabled. AMD Ryzen 7 5700U, 8 cores/16 logical CPUs;
  no CUDA device. Memory usage was not measured.
- Explicit Japanese: 13 cues, 19.376 seconds elapsed. Output:
  `outputs/phase1-explicit/0f61c2b7a41f4af3b071bed73ed9cecd/subtitles.en.srt`.
- Auto: resolved ja, top model score 0.998378 (not calibrated accuracy), detection
  interval 80–30080 ms, 13 cues, 21.380 seconds. SRT identical to explicit run.
  `outputs/phase1-auto/3a14fa6ab2cc471a9cf92353bfdf21e6/subtitles.en.srt`.
- Sample start 10s/duration 15s: 7 cues, 11.076 seconds. Exported range 10–25s;
  an overlong final model boundary was clipped and flagged, raw timing preserved.
  `outputs/phase1-offset/ab93408008254fb69b1817c5214296ec/subtitles.en.srt`.
- Timings include service extraction, VAD, model loading, inference and export;
  exclude initial download and Python startup. These are short-clip observations,
  not movie speed estimates or a quality benchmark.

Observed limitation: full-clip cue 7 says "No, I'd like some tekkou." This looks
suspect and needs source-language review; raw results were deliberately preserved.
Sample output also differs from full-clip wording, showing context sensitivity.

Unverified acceptance gates: semantic accuracy, synchronization viewed in a media
player, 5–10 minute Japanese sample, medium baseline, another source language,
GPU inference and full-movie memory/performance. The available clip is shorter
than the plan's acceptance sample. Do not mark all Phase 1 acceptance gates passed.

Next action: user listening/viewing review, then confirmation before starting
Phase 2 from updated develop. Phase 2 adds bounded chunks, interruption/resume,
and full-movie reliability; no Phase 2 work started here.

## Phase 0: environment and project foundation

Implemented: installable CLI; doctor; global-index audio inspection; explicit
model downloads and cache-only mode; TOML settings; language validation and
listing; Windows setup; Windows/Python 3.11 dependency snapshot.

Verification on 4 November 2026:
- `python -m pytest -q`: 4 passed, including real FFmpeg-generated multi-track
  media with Unicode/spaces in its path, missing ffprobe, invalid input, and
  settings precedence/unsupported settings.
- `python -m ruff check src tests`: passed.
- `python -m pip check`: passed.
- `local-subs doctor`: passed without downloading a model; Python 3.11.9,
  FFmpeg/ffprobe 9.0.1, CTranslate2 4.8.5, CPU float32/int8/int8_float32;
  zero CUDA devices. Output write probe passed.
- Language listing initially exposed a Windows console encoding failure; corrected
  with explicit UTF-8 output and modern Rich rendering.

Not verified: real model download, cached model integrity, actual CPU/GPU
inference, translation meaning, fresh-machine install. No movie or model supplied.
Doctor reports backend discovery, not successful inference. No language has been
evaluated for translation quality. The Phase 1 CPU inference smoke test remains
pending until a model is explicitly prepared.

Next: after user confirmation, branch from updated develop for Phase 1. Implement
track selection, extraction with timeline mapping, bounded language resolution,
offline inference, raw results and English SRT. Real sample and human review are
required acceptance gates; never treat synthetic tests as translation evidence.
