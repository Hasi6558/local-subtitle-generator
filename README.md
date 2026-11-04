# Local subtitle generator

Offline multilingual-to-English movie subtitles, built one phase at a time.
Phase 4 adds an authenticated localhost API, durable SQLite queue, a separate
inference worker, versioned cue editing, and registered-media streaming to the
existing CLI, subtitle exports/QC, checkpoints/resume and local benchmarks.
A 10-minute Japanese dialogue test passed; human translation/timing review and
full-movie inference acceptance remain pending.

Windows setup (Python 3.11, 64-bit): install FFmpeg and put its `bin` directory on
PATH, then open PowerShell in this repository:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\local-subs --help
.venv\Scripts\local-subs doctor
.venv\Scripts\local-subs inspect "D:\Movies\movie.mkv"
.venv\Scripts\local-subs languages
```

The lock records the tested Windows/Python 3.11 dependency set, including development
tools. Other operating systems have not yet been validated. Windows also requires
the Microsoft Visual C++ runtime for CTranslate2.

Model preparation is an explicit network operation; medium is a large download:

```powershell
.venv\Scripts\local-subs models download medium
.venv\Scripts\local-subs models download medium --local-files-only
```

Use `--model-cache` to choose another cache directory. Help, doctor, languages,
and inspect never download models. Offline checking fails if files are unavailable;
it never substitutes a hosted model. Generation always loads cached files only.

Configuration uses TOML. Pass `--config settings.toml` to doctor or models download.
Precedence is command flags > config > defaults; unknown fields are rejected.

```toml
source_language = "auto"
target_language = "en"
speech_model = "medium"
output_dir = "outputs"
# model_cache = 'D:\Models\local-subs'
```

English is the only output language. Supported language codes come from the installed
backend; Japanese has a short-clip inference test with human review pending. English-only and
turbo models are rejected for the planned direct translation pipeline.

CPU diagnostic smoke test: run `local-subs doctor`; a supported int8 compute type
confirms backend discovery, not inference. This machine reported CPU int8,
int8_float32 and float32, with no CUDA device. CUDA is optional. Consult the
[faster-whisper installation requirements](https://github.com/SYSTRAN/faster-whisper#requirements)
for the pinned backend's CUDA/cuDNN requirements before configuring a GPU.
Doctor discovery does not prove that all GPU runtime DLLs load during inference.

Checks:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m pip check
```

Progress and outstanding acceptance gates are in `docs/PROGRESS.md`;
implementation decisions are in `docs/DECISIONS.md`.

Generate English subtitles (prepare the chosen model explicitly first):

```powershell
.venv\Scripts\local-subs models download medium
.venv\Scripts\local-subs generate "D:\Movies\movie.mkv" --audio-stream 1 --source-language ja --model medium --device cpu --compute-type int8 --start 00:10:00 --duration 00:05:00 --output-dir outputs
```

Omit `--audio-stream` only for a sole audio track or a unique matching language-tagged
track with an explicit language. Indexes are global ffprobe indexes, not audio-only
indexes. `--source-language auto` requires a sole track unless a track is explicit.
Auto detection samples up to three contiguous 30-second windows starting at VAD
speech regions; leading silence is skipped. The default 0.7 detection threshold is
a heuristic, not calibrated accuracy; use `--detection-threshold` to change it.
Ambiguous detection fails with an instruction to choose an explicit language.
The language is resolved once and cached with input/model/track/sample/settings
identity. Mixed-language films are not reliably handled. English input uses
transcription; other languages use Whisper's direct English translation task.

Each run creates a new job directory with `manifest.json`, disk-backed prepared
WAV, and immutable `chunks/` checkpoints. Each export gets a new `exports/` revision
containing raw segments, generated cues, SRT, boundary review report, and manifest
snapshot. Earlier exports and user edits are never overwritten. JSON/SRT writes
are atomic. Inputs with no VAD speech complete with `result: empty` and an empty SRT.
`--no-vad` disables filtering for explicit-language inference; auto detection still
requires VAD to identify speech-containing samples. VAD can miss quiet speech.

Sample SRT keeps its original movie offset: a sample starting at ten minutes
exports cues at or after ten minutes, for playback beside the original movie.
Extraction maps timestamps relative to the container presentation start, pads a
delayed audio track with silence, and trims without concatenating speech. This
correctness-first implementation decodes from the beginning even for later samples.
Raw times/text are preserved; exported cues are bounded to the playable sample,
with clipping flags. Milliseconds round half up.

The default pipeline reads bounded overlapping chunks from prepared PCM audio on
disk. Defaults: 300-second ownership targets and 5 seconds of context per side;
cuts may move up to 2 seconds toward low-energy audio. Logical ownership remains
separate from context. Only temporally overlapping similar phrases from adjacent
chunks are deduplicated. Raw alternatives remain available, and uncertain merges,
conflicts, possible truncation and omissions are flagged in `boundaries.json`.
These checks are heuristics and cannot prove completeness or exact synchronization.

Ctrl+C and `cancel` preserve completed chunks; resume restarts the unfinished chunk.
Cancellation during extraction waits for FFmpeg to finish, and model generation
checks requests when each segment arrives. One chunked worker is allowed per
output root. Use the same output root to serialize inference; different roots
have independent locks. Model scores are review hints. Review meaning and timing
in a media player before relying on the output.

Job commands:

```powershell
.venv\Scripts\local-subs jobs list --output-dir outputs
.venv\Scripts\local-subs jobs show JOB_ID --output-dir outputs
.venv\Scripts\local-subs cancel JOB_ID --output-dir outputs
.venv\Scripts\local-subs resume JOB_ID --output-dir outputs
.venv\Scripts\local-subs jobs cleanup JOB_ID --output-dir outputs
```

Cleanup removes generated prepared audio only, preserving source media, checkpoints,
exports and edits. Resume re-extracts missing/corrupt audio. Source fingerprints,
track, sample, model snapshot, requested/resolved language, backend versions and
inference settings protect against stale checkpoint reuse. Changes invalidate
affected inference while preserving compatible extraction. Prior attempt manifests
and immutable result files retain history. No automatic retry loops are used.
Disk space is checked before extraction; allow approximately 32 KB per second of
mono PCM plus 64 MiB working space. Corrupt/missing media, missing cached model,
disk errors and model errors leave actionable failure records when disk permits.

Use `--chunk-seconds 120 --overlap-seconds 5` to exercise more boundaries. Keep the
Phase 1 baseline with `generate ... --single-pass` for comparison. That baseline
loads the entire selection into memory and does not support checkpoint resume.
Phase 1 job IDs cannot be resumed by the chunked pipeline; create a new job.
Default generation also writes `formatted_cues.json`, `subtitles.en.vtt`, and
`qc.json`. `generated_cues.json` and raw segments remain unformatted inputs.

Readability targets are configurable review defaults: 42 characters per line,
two lines, 1–7 seconds per cue, and 17 characters/second. Wrapping preserves all
words; an unbreakable word or a cue requiring more lines is retained and flagged.
Long translated segments retain their original timing and are flagged for manual
review; no English word alignment or proportional split timings are invented.
VTT escapes plain-text markup characters and is round-trip checked with webvtt-py.

Validation and inference-free re-export:

```powershell
.venv\Scripts\local-subs validate "D:\Subtitles\subtitles.en.srt" --duration 02:03:00 --report outputs/validation.json
.venv\Scripts\local-subs export JOB_ID --output-dir outputs --line-width 40 --max-lines 2 --max-cps 17
.venv\Scripts\local-subs export JOB_ID --output-dir outputs --cues "D:\Subtitles\edited_cues.json" --no-check-coverage
```

`validate` accepts SRT, strict VTT, or a JSON cue list. Each JSON cue needs a string
`id`, integer `start_ms`/`end_ms`, and nonempty `text`. Structural errors return
exit code 1; readability/overlap/repetition warnings remain review hints. Supply
duration to check the playable upper bound. Validation reports are not overwritten;
choose a new report path for another run.

`export` creates a new UUID revision without loading a speech model. It defaults
to stored generated cues; `--cues` can explicitly select edited JSON/SRT/VTT.
It snapshots the selected input and formatting policy, preserving earlier exports
and edits. New policies recompute readability flags while preserving boundary flags.
It checks coverage using local VAD when prepared audio remains available; after
cleanup, coverage is reported unavailable. Coverage/repetition flags are heuristic
and cannot prove complete dialogue recovery or semantic accuracy.

Set generation/export review defaults in TOML:

```toml
[formatting]
line_width = 42
max_lines = 2
min_duration_ms = 1000
max_duration_ms = 7000
max_cps = 17
```

Pass `--config settings.toml` to generate, validate or export. Export's formatting
flags override the config. Formatting settings are excluded from inference cache
identity, so changed formatting reuses matching chunks. Existing Phase 1/2 jobs
can use `export` directly; no resume or model load is needed to reformat them.

Benchmark the same sample with explicitly prepared models:

```powershell
.venv\Scripts\local-subs benchmark "D:\Movies\sample.mp4" --models small --devices cpu --beam-sizes 1,5 --runs 2 --duration 30 --source-language ja --model-cache models --compute-type int8 --output-dir outputs
```

Comma-separated models/devices/beam sizes create a serial matrix. Each preset runs
in a fresh worker process, with the model reused for later repetitions. No model
downloads occur. `benchmark.json` records stage times, total seconds, real-time
factor, available process peak memory, QC flags, actual model/device/revision, and
unverified human ratings. A failed preset is recorded and not automatically retried;
the command returns nonzero if any preset fails. Weights are cached, OS disk cache
is uncontrolled, and reported peak memory is process-lifetime RSS, not GPU VRAM.
See `docs/BENCHMARKS.md` for measurements and the provisional CPU test preset.

Test the provided clip with the prepared `small` model:

```powershell
$clip = Get-ChildItem test-video -Filter *.mp4 | Select-Object -First 1
.venv\Scripts\local-subs generate $clip.FullName --source-language auto --model small --model-cache models --device cpu --compute-type int8 --output-dir outputs
```

Opt-in inference test (requires an already prepared small model; no download):

```powershell
$env:LOCAL_SUBS_TEST_MEDIA = $clip.FullName
$env:LOCAL_SUBS_MODEL_CACHE = "models"
.venv\Scripts\python -m pytest tests/test_model_integration.py -q
```

Local API (no browser UI yet):

```powershell
.venv\Scripts\local-subs serve --output-dir outputs --media-root test-video --model-cache models
```

The server binds to `127.0.0.1:8765`; `--port` changes the port. Repeat
`--media-root` to approve additional folders. Defaults approve only the current
working directory. A local bearer token is stored in `outputs/.service/token`;
the token is not printed or sent to a hosted service. See `docs/API.md` for
PowerShell requests, routes, cue revision conflicts and shutdown/recovery behavior.

CLI and API now use the same authoritative `jobs.sqlite3` in the output root.
Existing job manifest snapshots migrate automatically when indexed/read. JSON
manifests remain reproducibility snapshots; editing one no longer overrides a job
already in SQLite. Cue revisions and queue state live in SQLite; large artifacts
remain on disk. Keep the database and job folders together. Stop workers before
copying an output root for backup; include the database and any WAL/SHM companions.

The API queues inference in one separate process per output root. Foreground CLI
jobs use the same worker lock and are not automatically claimed by the queue.
API exports select a stored cue revision without inference; they do not rerun VAD,
so their coverage report says unavailable. CLI export can still perform VAD checks.

Opt-in real HTTP + inference/crash/restart test (uses the same prepared small model):

```powershell
$env:LOCAL_SUBS_TEST_MEDIA = $clip.FullName
$env:LOCAL_SUBS_MODEL_CACHE = "models"
.venv\Scripts\python -m pytest tests/test_api_integration.py -q
```

This test starts a temporary loopback server, kills only its own inference worker
after a checkpoint, verifies reuse and HTTP responsiveness, and restarts the server
to check durable edits. It never downloads a model or uploads sample media.
