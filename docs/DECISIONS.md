# Decisions

- Implement and merge Phase 0 separately, then wait for the user's next-phase
  confirmation. No Phase 1 inference, UI, API, or subtitle dependency yet.
- Python 3.11.9 on Windows is the initial verified environment. Freeze resolved
  runtime and development dependencies into requirements.lock; installation of
  the project itself uses editable mode with --no-deps after the lock.
- Use TOML configuration via the Python standard library, with Pydantic validation.
  CLI flags override file fields; file fields override defaults.
- Validate language codes against the pinned faster-whisper tokenizer metadata;
  Babel supplies display names. This private backend metadata dependency is
  covered by tests and should be checked when upgrading faster-whisper.
- Restrict models to known multilingual Whisper variants, excluding English-only
  and turbo models. Per-model language capabilities (notably Cantonese support)
  must be enforced against a loaded model in Phase 1 before inference.
- Models are only downloaded by the explicit preparation command. Offline checks
  use local_files_only. No media leaves the machine.
- Preserve the user's ignored plan directory. Generated media, outputs, virtual
  environments, and Python caches remain outside source control.
- Checked upstream faster-whisper and CTranslate2 installation documentation.
  CPU is the tested path; CUDA discovery and DLL/model execution are distinct.

## Phase 1

- Shared media/inference/jobs/subtitles services implement generation; CLI is an
  adapter. SRT serialization and round-trip validation use srt 3.5.3.
- Models are prepared explicitly. Generation resolves only local cached snapshots
  and checks tokenizer presence to prevent the backend's tokenizer download fallback.
- Small was explicitly downloaded for a CPU smoke test. Medium remains the default
  quality baseline, not a tested quality claim on this hardware.
- Use full SHA-256 input fingerprints and snapshot revisions for reproducibility.
  Language-resolution cache keys include track, range, model, backend versions,
  settings, and policy. Effective language is resolved before inference identity.
- Detection uses up to three original contiguous 30-second speech-starting windows,
  accepting a top score of at least 0.7. This is heuristic; unresolved cases fail.
  Diagnostic sample intervals stay on the movie timeline, including on failure.
- Extraction normalizes original audio PTS by the container start and uses resampling
  to pad leading gaps, then trims by movie-relative time. Sample extraction decodes
  from the beginning; efficient seeking is deferred pending correctness tests.
- Keep raw segment fields and diagnostics intact. Derived cues clip out-of-range
  model timings with flags; empty/nonpositive cues are skipped with warnings.
- Always create a new UUID job directory. No regeneration overwrites user edits.
  Full decoded audio is held in memory for this baseline; bounded-memory chunking
  and interruption/resume are Phase 2, not implied by saved partial raw results.
- User-provided media, model weights, transcripts, and generated subtitles remain
  ignored locally. Commit only code, dependencies, and measured review notes.

## Phase 2

- Keep the Phase 1 service as an explicit `--single-pass` comparison path. Default
  CLI generation now uses the chunked service, with schema-2 job manifests.
- Decode the selected range to PCM16 WAV on disk once, then read bounded context
  windows. This bounds audio arrays independently of movie length, at the cost of
  about 32 KB/s of disk audio. Extraction still decodes from the beginning.
- Default ownership target is 300 seconds with 5 seconds of context on each side.
  Prefer quiet 200 ms frames within 2 seconds of each cut using an RMS heuristic;
  do not treat low energy as proof of silence. Ownership and context are separate.
- Resolve source language once from the first speech-containing chunk; earlier
  silent chunks can checkpoint without a model. Reuse the loaded model throughout
  the job. Explicit source language and English transcription routing are retained.
- Preserve checkpoints by settings/content hash, verify their file hashes, and
  atomically replace the manifest only after a checkpoint is durable. Incomplete
  files cannot count as completed chunks. Changed inference settings retain
  compatible extraction; changed media/track/range invalidate extraction too.
- Each export has a new revision and reproducibility manifest snapshot. Attempt
  snapshots preserve prior settings before invalidation. No user edits are merged
  or overwritten automatically.
- Reconcile only adjacent chunks with temporal overlap plus normalized text
  similarity. Ownership midpoint chooses candidates; conflicting or possibly
  truncated boundary text is flagged and raw alternatives are retained. These
  heuristics cannot guarantee no omitted dialogue; human review remains required.
- Cooperative cancellation is checked at segment/chunk boundaries. FFmpeg
  extraction finishes before honoring an external cancel request. Ctrl+C or a
  process crash can restart the current chunk; no token-level resume is promised.
- One worker lock per output root avoids concurrent chunked inference by default.
  Different roots are independent. Stale process locks can be recovered on resume;
  job control is local, with no background daemon, queue scheduler, or HTTP service.
- Cleanup deletes generated prepared audio, never source media, checkpoints or
  exported/user-edited artifacts. Resuming reconstructs missing prepared audio.
- Keep the user's complete test-video directory ignored, including reference SRT.
  Full-movie preparation is tested, but full-movie model inference and human
  timing/meaning acceptance remain explicitly unverified.

## Phase 3

- Apply word-boundary wrapping without deleting text or changing model timings.
  Keep more than two lines or long unbreakable words when necessary and flag them.
  Long translated segments are flagged for manual review; automatic timing splits
  would imply unsupported English alignment precision.
- Store formatting policy separately from inference identity. Re-export stored
  cues with new thresholds without loading a speech model; preserve generated/raw
  inputs, boundary flags, earlier exports and manual edits. Recompute derived
  readability flags rather than retaining stale threshold results.
- Use webvtt-py 0.7.0 for strict VTT parsing/round-trip verification, alongside the
  existing SRT serializer. Escape plain-text markup characters in generated VTT.
- QC structural errors prevent export; warnings flag review needs without dropping
  cues. A new export revision captures selected cues, input hash and original job
  manifest. No user report file is overwritten automatically.
- Coverage uses bounded local Silero VAD and temporal overlap. Report missing
  audio/coverage explicitly, never infer missing dialogue or semantic accuracy from
  a numerical coverage score alone. Repetition is also a heuristic flag only.
- Benchmark each preset in an isolated worker process; reuse one model for warm
  repetitions. Record actual stage/total timings, RTF, model revision, process peak
  RSS where supported, cache conditions, errors and unverified human ratings.
  OS cache is uncontrolled; process peak is cumulative, and GPU memory is unmeasured.
- Measurements support a provisional CPU test preset, not a quality winner.
  Full-movie generated-output and human meaning/synchronization gates remain open;
  do not claim v0.2 release readiness or proceed to a UI based on QC success alone.

## Phase 4

- Use one SQLite repository for CLI and API job state, queue claims, cancellation,
  immutable cue revisions and registered exports. WAL and short transactions support
  concurrent reads. User-version migrations create schema 1 then schema 2. Legacy
  snapshots import only when a DB entry is absent; JSON remains a snapshot, not a
  second authority. Cancellation control merges transactionally with worker saves.
- Split job preparation from execution. API preparation persists queued jobs; a
  separate local process claims and runs the existing chunked service. Foreground
  CLI work is explicitly excluded from automatic queue claims. One root lock
  serializes inference, and a service lock prevents duplicate supervisors.
- Supervise process crashes with at most three restarts. Reconcile stale claims
  against checkpoints; ordinary inference failures remain failed until explicit
  retry. Graceful shutdown cancels active work, preserves pending queue entries,
  and terminates only the owned worker after a five-second grace period.
- Bind only to loopback. Require a persistent local bearer/session token, reject
  unknown browser origins/hosts, and expose registered media only under approved
  roots. Use Starlette FileResponse's verified range implementation. No arbitrary
  file route, wildcard CORS, hosted API, uploads, CDN-backed docs or review UI.
- Store generated cue revision 0 immutably. Use transactional compare-and-swap
  edit revisions, return 409 on stale writes, and export selected revisions into
  new folders. Manual edits are preserved through retries/regeneration.
- API exports share core formatting/validation but skip VAD for predictable request
  latency and explicitly mark coverage unavailable. CLI export can still run VAD.
- Test real loopback HTTP while a separate process performs CPU inference, crash
  the test-owned worker after a durable checkpoint, then verify recovery, byte
  ranges, edit persistence and server restart. CPU success does not verify GPU or
  full-movie timing/meaning; the pre-UI real-movie gate remains open.
