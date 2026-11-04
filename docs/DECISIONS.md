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
