# Progress

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
