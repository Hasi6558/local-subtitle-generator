# Progress

## Phase 6: optional contextual translation implemented; human quality gate open

User requested direct Whisper translation remain available with a UI toggle for
testing. Added pinned portable llama.cpp
b12099 and official Qwen3-1.7B Q8_0 / Qwen3-4B Q4_K_M preparation (explicit
downloads, offline inference), source ASR, strict target-ID contextual batches,
translation checkpoints/glossary, sequential native unload, separate paired jobs
and UI comparison. Direct remains the default. No Ollama installation required.
Hardware: Ryzen 7 5700U, 16 GB RAM, integrated AMD graphics; CPU runtime selected.
Both official weights downloaded and checksummed. Exact identities, configured
pairs, noisy name/term flag limitations and measured evidence are in MODELS.md.

Verification on 4 November 2026:
- Python suite: 69 passed, 3 opt-in inference tests skipped. New coverage includes
  strict IDs/types, embedded instruction-like dialogue as data, context budgets,
  bounded retries, failed/partial checkpoints, glossary/model/source invalidation,
  unchanged ASR checkpoints, separate comparison metadata/edits, cancellable text
  requests and real subprocess cleanup on stop/pipe closure/parent disappearance.
- Ruff and pip checks passed; web build/type check and 9 unit tests passed. The
  final targeted English-skip/quality regression run passed all 26 tests.
- Five synthetic browser workflows passed (two real-inference tests deliberately
  skipped there), including both toggle options, unprepared-model gating, paired
  settings/glossary, source review and independent edits. Two separate real-video
  browser tests passed with cached Small speech and Qwen3-4B through the production
  queue worker: generate, source review, edits/reload, preview/seek, toggle and
  edited export. Desktop screenshots inspected; no human listening verdict.
- Same 36.177-second Japanese clip: direct produced 13 cues; contextual source
  produced 12, and both text candidates returned all IDs in three batches with no
  validation retries. Switching text models preserved all ASR checkpoint mtimes.
  Initial text-stage measurements: 1.7B 73.387 s / 2,534,510,592 native RSS bytes;
  4B 143.923 s / 5,113,933,824 native RSS bytes. Background activity uncontrolled.
- Clean real-browser paired run: direct about 15.3 s, contextual 4B 85.428 s total,
  including 11.533 s source inference and 71.551 s translation. Text native peak
  5,146,611,712 bytes. Separate direct benchmark: 16.610 s / 776,192,000 process RSS
  bytes. Memory scopes differ; no whole-app peak or full-movie extrapolation.
- Local evidence: outputs/phase6-evaluation/evaluation.json,
  outputs/phase6-live-acceptance.json, outputs/phase6-cli-comparison.json,
  outputs/phase6-baseline/benchmark-*/benchmark.json. Supplied media/transcripts,
  weights, native runtime and screenshots remain ignored by Git.
- Sandbox blocked localhost on the first text attempt and later asyncio's local
  test socketpair; approved runs outside it passed. A temporary-directory access
  failure was isolated using a fresh workspace test folder. These were environment
  limitations; source/checkpoint recovery worked without direct-mode fallback.

Both text models contain questionable wording, including interpretations affected
by source recognition errors. No model has won human semantic/name/omission/timing
review. Other configured pairs and long-video contextual generation remain
unevaluated. Keep this mode experimental and direct as default. Next: user review
and confirmation before Phase 7 timing refinement/selective recovery.

## Phase 5: review UI implemented; technical gates passed; human quality review open

Implemented: React/TypeScript/Vite review UI served by the local API; local session
connection; new jobs/track/language/model/sample selection; queue progress and
cancel/resume; video/cue seeking and active highlighting; text/timing autosave with
optimistic conflicts, best-effort draft recovery/download and undo; explicit
split/merge; search/QC filters/reasons; generated/edited revision exports; cached
remux/transcode previews; separate range proposals with explicit text acceptance.
CLI remains usable without frontend dependencies or a browser. No upload flow.

Verification on 4 November 2026:
- Full 7378.389-second Japanese movie completed: 25 chunks, 659 cues. Subsequent
  resume preserved all checkpoint mtimes, and SRT/VTT validation/export passed.
  Local summary: outputs/phase5-movie-gate.json; export under
  outputs/phase2-movie/8ae5ffa300624bc49e7429e07d34bbf2/exports/7675215416894d9c8d25e2fc004945bc.
- Recorded cumulative service time 941.396 seconds includes attempts and resume;
  it is not a clean wall-clock benchmark. The initial live schema upgrade stopped
  the older worker; six saved chunks were reused after restarting compatible code.
  An unfinished/unrecorded tail can be absent from cumulative timing. Keep schema
  stable during inference. Mid-run observed process peak: 1,069,432,832 bytes;
  this sample is not a guarantee of final/full-movie peak memory.
- QC preserved issues including 195 long durations, 49 reading-speed flags,
  boundary conflicts and 11 VAD speech regions without output. Structure/seek
  arithmetic does not establish semantic accuracy or viewed synchronization.
- Python suite: 50 passed, 3 optional inference tests skipped. Covers previous CLI/
  API behavior plus preview codecs, offsets, source preservation, cache hashes,
  selected-track protection, static asset isolation and preserved parent edits.
- Web build/type check passed; 8 editor/unit tests passed, including in-flight
  saves, conflict recovery, unavailable browser storage and word/time preservation.
- Four browser workflows passed on Windows Chrome: edit/autosave/reload,
  split/merge/undo, original/preview seeking and keyboard controls, edited SRT
  download, conflict draft recovery, unsupported codec fallback, queue cancellation
  and explicit proposal acceptance. Desktop/mobile screenshots visually inspected;
  mobile has no horizontal overflow. Fixtures are synthetic and never run models.
- Separate real browser/model flow passed twice with the user's 36-second clip
  and cached small/CPU/int8 model: UI-created job produced 13 cues, saved edit
  survived reload, compatible preview sought correctly, edited SRT downloaded.
  Final run: 1 passed / 4 fixture tests intentionally skipped, 28.5 seconds total.
  Local log: outputs/phase5-live-browser-final.log; image: outputs/phase5-real-review.png.
- Ruff, pip check, build and whitespace checks passed. Node/npm packages locked;
  compiled assets, media, weights, screenshots and test libraries remain ignored.

Human meaning and viewed synchronization remain unverified, along with medium/GPU
and a second source language. Proposal acceptance changes text only, not original
timing; automatic selective re-alignment/reconciliation remains Phase 7. Browser
coverage is Windows Chrome; no universal codec/playback claims. No quality-release
readiness is inferred from structural/browser success.

Next: user review and confirmation before Phase 6 optional contextual local
translation. Evaluate hardware/model/language-pair fit before adding a text model;
keep direct Whisper translation as the baseline. No Phase 6 work started.

## Phase 4: local API and persistent worker implemented and verified on CPU

Implemented: loopback FastAPI/Uvicorn server; shared authoritative SQLite job
repository with migrations; durable queue and worker process; bounded crash
recovery; cancellation/retry/shutdown; local token/session and origin/host checks;
approved-root registration/inspection; byte-range media; language/progress routes;
validated optimistic cue edits and revision-based SRT/VTT/QC export. CLI remains
available and uses the same job-state repository. JSON manifests are snapshots.

Verification on 4 November 2026:
- Default suite: 43 tests passed, 3 optional model/HTTP inference tests skipped.
  New checks cover rejected authorization/origins/hosts/paths, invalid settings,
  registered range/HEAD/416 responses, concurrent edit conflict, revision exports,
  queued and active cancellation, retry, silent worker, worker dispatch failure,
  canonical DB vs stale snapshot, schema-1 upgrade, durable pending queues and
  active-job shutdown/lock cleanup. Earlier CLI/timestamp/cache/QC checks pass.
- Ruff, pip check and git diff --check passed. Dependencies locked on Windows/
  Python 3.11.9: FastAPI 0.162.0, Starlette 1.10.0, Uvicorn 0.54.0; httpx 0.28.1
  is used for HTTP tests. No model downloads or hosted services.
- Opt-in real HTTP test passed twice. Final run: 1 passed in 24.65 seconds. A real
  loopback server queued cached small/CPU/int8 inference on the 36-second Japanese
  clip, 15-second ownership targets/2-second overlap. Terminated only the owned
  worker after checkpoint 1; supervisor restarted once and preserved checkpoint
  mtime, then completed three chunks/13 cues. Manual editing/export, a registered
  media range request, queued cancellation and full server restart succeeded.
- Final run made 172 health requests during processing, max 0.063 seconds;
  this is an observed local test, not a universal HTTP latency guarantee.
- Local summary: `outputs/phase4-http-final/http-test-summary.json`; job
  `f282972ef0814ba7a32693c246944ee4`; worker logs and all media/transcripts remain
  ignored. Test servers/workers were stopped after verification.

Limitations/open gates: full-movie generated-output acceptance, human source-language
meaning/synchronization review, medium/GPU and other languages. Native inference
and extraction cancellation is cooperative, not immediate. API export deliberately
does not rerun coverage VAD. No review UI, upload flow, SSE or browser preview yet.

Next: user review and confirmation. Phase 5 is the review UI; satisfy the plan's
real-movie generate/resume/validate/export and human timing gate before building it.
Do not treat Phase 4 CPU/API success as v0.2/full-movie acceptance.

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
