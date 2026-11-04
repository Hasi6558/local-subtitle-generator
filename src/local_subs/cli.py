import platform
import shutil
import tempfile
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from local_subs.config import languages as supported_languages, load_settings
from local_subs.media import inspect_media

app = typer.Typer(no_args_is_help=True)
models = typer.Typer(no_args_is_help=True)
app.add_typer(models, name="models")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
console = Console(legacy_windows=False)


def fail(exc):
    console.print(f"Error: {exc}", style="red", markup=False)
    raise typer.Exit(1)


@app.command()
def languages():
    """List backend-supported languages (project evaluation is separate)."""
    table = Table("Code", "Language", "Project evaluation")
    for code, name in supported_languages().items():
        table.add_row(code, name, "Not evaluated")
    console.print(table)


@app.command("inspect")
def inspect_command(media: Path):
    """List audio tracks with global stream indexes."""
    try:
        info = inspect_media(media)
        table = Table(
            "Global index",
            "Language",
            "Title",
            "Codec",
            "Channels",
            "Duration (s)",
            "Default",
        )
        for stream in info.get("streams", []):
            if stream.get("codec_type") != "audio":
                continue
            tags = stream.get("tags", {})
            table.add_row(
                str(stream["index"]),
                tags.get("language", "unknown"),
                tags.get("title", ""),
                stream.get("codec_name", "unknown"),
                str(stream.get("channels", "unknown")),
                str(
                    stream.get(
                        "duration", info.get("format", {}).get("duration", "unknown")
                    )
                ),
                str(bool(stream.get("disposition", {}).get("default", 0))),
            )
        console.print(table)
        if not table.row_count:
            console.print("No audio streams found.")
    except (ValueError, OSError) as exc:
        fail(exc)


@app.command()
def doctor(
    config: Path | None = None,
    output_dir: Path | None = None,
    model_cache: Path | None = None,
):
    """Check prerequisites without loading or downloading models."""
    try:
        import ctranslate2

        settings = load_settings(config, output_dir=output_dir, model_cache=model_cache)
        console.print(f"Python: {platform.python_version()}")
        missing = False
        for tool in ("ffmpeg", "ffprobe"):
            location = shutil.which(tool)
            console.print(
                f"{tool}: {location or 'MISSING: install FFmpeg and add bin to PATH'}"
            )
            missing |= location is None
        console.print(f"CTranslate2: {ctranslate2.__version__}")
        console.print(
            f"CPU compute types: {sorted(ctranslate2.get_supported_compute_types('cpu'))}"
        )
        try:
            count = ctranslate2.get_cuda_device_count()
            console.print(f"CUDA devices: {count}")
            if count:
                console.print(
                    f"CUDA compute types: {sorted(ctranslate2.get_supported_compute_types('cuda'))}"
                )
            else:
                console.print(
                    "CPU available. CUDA needs a compatible NVIDIA GPU, driver, CUDA and cuDNN."
                )
        except RuntimeError as exc:
            console.print(
                f"CUDA unavailable: {exc}. Use CPU or check driver/CUDA/cuDNN compatibility."
            )
        console.print(
            "Discovery does not verify model execution or runtime DLL loading."
        )
        console.print(
            f"Model cache: {settings.model_cache.resolve()} (explicit downloads only)"
        )
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=settings.output_dir):
            pass
        console.print(f"Writable output: {settings.output_dir.resolve()}")
        console.print(
            f"Language: {settings.source_language} -> {settings.target_language}; model: {settings.speech_model}"
        )
        if missing:
            raise typer.Exit(1)
    except (ValueError, OSError, RuntimeError) as exc:
        fail(exc)


@models.command("download")
def download(
    model: str | None = typer.Argument(None),
    config: Path | None = None,
    model_cache: Path | None = None,
    local_files_only: bool = False,
):
    """Explicitly download a model, or verify availability offline."""
    try:
        from faster_whisper.utils import download_model

        settings = load_settings(config, speech_model=model, model_cache=model_cache)
        console.print(
            f"{'Cache only' if local_files_only else 'Network download'}: {settings.speech_model}; cache: {settings.model_cache.resolve()}"
        )
        path = download_model(
            settings.speech_model,
            cache_dir=str(settings.model_cache),
            local_files_only=local_files_only,
        )
        console.print(f"Model ready: {path}")
    except Exception as exc:
        fail(exc)
