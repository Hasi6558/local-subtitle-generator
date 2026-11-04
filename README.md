# Local subtitle generator

Offline multilingual-to-English movie subtitles, built one phase at a time.
Phase 1 provides offline English SRT generation, environment checks, audio-track
inspection, validated settings, and explicit model preparation. Real short-clip
inference works; human translation/timing review and a 5–10 minute test are pending.

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

Each run creates a new job directory with `manifest.json`, `audio.wav`,
`raw_segments.json`, `generated_cues.json`, and `subtitles.en.srt`. Earlier jobs
and user edits are never overwritten. JSON/SRT writes are atomic. Empty VAD
results produce empty SRT with a visible warning, not invented dialogue.
`--no-vad` disables filtering for explicit-language inference; auto detection still
requires VAD to identify speech-containing samples. VAD can miss quiet speech.

Sample SRT keeps its original movie offset: a sample starting at ten minutes
exports cues at or after ten minutes, for playback beside the original movie.
Extraction maps timestamps relative to the container presentation start, pads a
delayed audio track with silence, and trims without concatenating speech. This
correctness-first implementation decodes from the beginning even for later samples.
Raw times/text are preserved; exported cues are bounded to the playable sample,
with clipping flags. Milliseconds round half up.

Phase 1 loads the selected audio into memory. Full-movie bounded memory, chunk
resume, formatting improvements, and QC reports belong to later phases. Ctrl+C
preserves partial raw results but cannot resume inference. Model scores are review
hints. Review meaning and timing in a media player before relying on the output.

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
