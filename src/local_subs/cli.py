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
from local_subs.media import parse_time

app = typer.Typer(no_args_is_help=True)
models = typer.Typer(no_args_is_help=True)
app.add_typer(models, name="models")
jobs = typer.Typer(no_args_is_help=True)
app.add_typer(jobs, name="jobs")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
console = Console(legacy_windows=False)


def fail(exc):
    console.print(f"Error: {exc}", style="red", markup=False)
    raise typer.Exit(1)


@app.command()
def generate(
    media: Path,
    config: Path | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    audio_stream: int | None = None,
    model: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    output_dir: Path | None = None,
    model_cache: Path | None = None,
    start: str = "0",
    duration: str | None = None,
    vad: bool | None = typer.Option(None, "--vad/--no-vad"),
    detection_threshold: float | None = None,
    chunk_seconds: int | None = None,
    overlap_seconds: int | None = None,
    single_pass: bool = False,
):
    """Generate English SRT offline, retaining the original movie timeline."""
    from local_subs.resumable import generate as generate_job
    from local_subs.resumable import Cancelled

    if single_pass:
        from local_subs.jobs import generate as generate_job

    try:
        settings = load_settings(
            config,
            source_language=source_language,
            target_language=target_language,
            speech_model=model,
            device=device,
            compute_type=compute_type,
            output_dir=output_dir,
            model_cache=model_cache,
            vad=vad,
            detection_threshold=detection_threshold,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )
        console.print(f"Settings: {settings.model_dump(mode='json')}", markup=False)
        console.print(
            "Sample timestamps remain relative to the original movie. Mixed-language dialogue requires review."
        )
        directory = generate_job(
            media,
            settings,
            audio_stream,
            parse_time(start),
            parse_time(duration) if duration else None,
            notify=lambda message: console.print(message, markup=False),
        )
        console.print(f"Job artifacts: {directory}", markup=False)
    except (KeyboardInterrupt, Cancelled):
        console.print(
            "Cancelled; completed checkpoints preserved. Resume restarts any unfinished chunk."
        )
        raise typer.Exit(130)
    except Exception as exc:
        fail(exc)


@app.command()
def resume(
    job_id: str,
    output_dir: Path = Path("outputs"),
    source_language: str | None = None,
    model: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    audio_stream: int | None = None,
    chunk_seconds: int | None = None,
    overlap_seconds: int | None = None,
):
    """Resume matching completed chunks; changed inference settings invalidate stale results."""
    from local_subs.resumable import resume as resume_job, Cancelled

    try:
        resume_job(
            job_id,
            output_dir,
            {
                "source_language": source_language,
                "speech_model": model,
                "device": device,
                "compute_type": compute_type,
                "chunk_seconds": chunk_seconds,
                "overlap_seconds": overlap_seconds,
            },
            audio_stream,
            notify=lambda message: console.print(message, markup=False),
        )
    except (KeyboardInterrupt, Cancelled):
        raise typer.Exit(130)
    except Exception as exc:
        fail(exc)


@app.command()
def cancel(job_id: str, output_dir: Path = Path("outputs")):
    """Request cooperative cancellation of a local job."""
    from local_subs.resumable import cancel as cancel_job

    try:
        console.print(cancel_job(job_id, output_dir))
    except Exception as exc:
        fail(exc)


@jobs.command("list")
def jobs_list(output_dir: Path = Path("outputs")):
    from local_subs.resumable import read_manifest

    table = Table()
    table.add_column("Job ID", no_wrap=True)
    for title in ("State", "Completed chunks", "Source"):
        table.add_column(title)
    for path in sorted(output_dir.glob("*/manifest.json")):
        try:
            data = read_manifest(path.parent)
            chunks = data.get("chunks", [])
            table.add_row(
                data["job_id"],
                data["state"],
                f"{sum(c.get('state') == 'completed' for c in chunks)}/{len(chunks)}",
                data.get("source_path", data.get("source", {}).get("path", "")),
            )
        except (OSError, ValueError, KeyError):
            console.print(f"Skipping unreadable manifest: {path}", markup=False)
    console.print(table)


@jobs.command("show")
def jobs_show(job_id: str, output_dir: Path = Path("outputs")):
    from local_subs.resumable import job_directory, read_manifest

    try:
        console.print_json(data=read_manifest(job_directory(output_dir, job_id)))
    except Exception as exc:
        fail(exc)


@jobs.command("cleanup")
def jobs_cleanup(job_id: str, output_dir: Path = Path("outputs")):
    """Delete prepared WAVs only; preserve checkpoints, exports and edits."""
    from local_subs.resumable import cleanup

    try:
        console.print(
            f"Removed {cleanup(job_id, output_dir)} bytes of prepared audio. Resume can re-extract it."
        )
    except Exception as exc:
        fail(exc)


@app.command()
def languages():
    """List backend-supported languages (project evaluation is separate)."""
    table = Table("Code", "Language", "Project evaluation")
    for code, name in supported_languages().items():
        table.add_row(
            code,
            name,
            "Small/CPU clip run; human review pending"
            if code == "ja"
            else "Not evaluated",
        )
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
