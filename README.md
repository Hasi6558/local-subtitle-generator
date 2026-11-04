# Local subtitle generator

Offline multilingual-to-English movie subtitles, built one phase at a time.
Phase 0 provides environment checks, audio-track inspection, validated settings,
and explicit model preparation. Subtitle generation arrives in Phase 1.

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
it never substitutes a hosted model. Inference is not implemented yet.

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
backend; none have undergone project translation evaluation yet. English-only and
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
