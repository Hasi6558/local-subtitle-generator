# Progress

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
