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
text_models = typer.Typer(no_args_is_help=True)
app.add_typer(text_models, name="text-models")
jobs = typer.Typer(no_args_is_help=True)
app.add_typer(jobs, name="jobs")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
console = Console(legacy_windows=False)


def read_glossary(path):
    import json

    return json.loads(path.read_text(encoding="utf-8-sig")) if path else None


@text_models.command("prepare")
def prepare_text_model(
    model: str = "qwen3-4b",
    model_cache: Path | None = None,
    local_files_only: bool = False,
):
    """Explicitly prepare pinned local text weights and portable Windows runtime."""
    from local_subs.text_models import prepare

    try:
        settings = load_settings(model_cache=model_cache)
        console.print_json(
            data=prepare(settings.model_cache, model, offline=local_files_only)
        )
    except Exception as exc:
        fail(exc)


@app.command("compare")
def compare_jobs(first: str, second: str, output_dir: Path = Path("outputs")):
    """Compare same-range pipeline jobs without assigning a semantic quality score."""
    from local_subs.comparison import compare
    from local_subs.resumable import job_directory, read_manifest
    from local_subs.quality import read_cues

    try:
        manifests = [
            read_manifest(job_directory(output_dir, identity))
            for identity in (first, second)
        ]
        cues = [
            read_cues(Path(m["artifacts"]["generated_cues.json"])) for m in manifests
        ]
        console.print_json(data=compare(*manifests, *cues))
    except Exception as exc:
        fail(exc)


def fail(exc):
    console.print(f"Error: {exc}", style="red", markup=False)
    raise typer.Exit(1)


@app.command()
def serve(
    output_dir: Path = Path("outputs"),
    media_root: list[Path] = typer.Option(None, "--media-root"),
    model_cache: Path | None = None,
    port: int = typer.Option(8765, min=1, max=65535),
):
    """Run the authenticated local API and one durable queue worker."""
    import uvicorn
    from local_subs.api import create_app

    try:
        application = create_app(
            output_dir, media_root or [Path.cwd()], model_cache=model_cache, port=port
        )
        console.print(f"Local API: http://127.0.0.1:{port}")
        console.print(
            f"Token file: {output_dir.resolve() / '.service' / 'token'}", markup=False
        )
        console.print(
            "Media registration is restricted to the configured media folders. Ctrl+C stops the server and checkpoints/cancels active work."
        )
        uvicorn.run(
            application,
            host="127.0.0.1",
            port=port,
            access_log=False,
            loop="asyncio:SelectorEventLoop"
            if platform.system() == "Windows"
            else "auto",
        )
    except Exception as exc:
        fail(exc)


def formatting_policy(
    config=None,
    line_width=None,
    max_lines=None,
    min_cue_seconds=None,
    max_cue_seconds=None,
    max_cps=None,
):
    from local_subs.policy import FormattingPolicy

    data = load_settings(config).formatting.model_dump()
    changes = {
        "line_width": line_width,
        "max_lines": max_lines,
        "min_duration_ms": round(min_cue_seconds * 1000)
        if min_cue_seconds is not None
        else None,
        "max_duration_ms": round(max_cue_seconds * 1000)
        if max_cue_seconds is not None
        else None,
        "max_cps": max_cps,
    }
    return FormattingPolicy.model_validate(
        data | {k: v for k, v in changes.items() if v is not None}
    )


@app.command("validate")
def validate_command(
    subtitles: Path,
    duration: str | None = None,
    config: Path | None = None,
    report: Path | None = None,
):
    """Validate SRT, VTT or cue JSON; exit 1 for structural errors, warnings remain review hints."""
    from local_subs.quality import read_cues, assess
    from local_subs.jobs import write_json

    try:
        policy = formatting_policy(config)
        try:
            result = assess(
                read_cues(subtitles), policy, parse_time(duration) if duration else None
            )
        except (ValueError, OSError) as exc:
            result = {
                "error_count": 1,
                "warning_count": 0,
                "issues": [
                    {"code": "parse_error", "severity": "error", "message": str(exc)}
                ],
            }
        if report:
            if report.exists():
                raise ValueError(
                    "Report file already exists; choose a new path to preserve it"
                )
            write_json(report, result)
        console.print_json(data=result)
    except Exception as exc:
        fail(exc)
    if result["error_count"]:
        raise typer.Exit(1)


@app.command("export")
def export_command(
    job_id: str,
    output_dir: Path = Path("outputs"),
    cues: Path | None = None,
    config: Path | None = None,
    line_width: int | None = None,
    max_lines: int | None = None,
    min_cue_seconds: float | None = None,
    max_cue_seconds: float | None = None,
    max_cps: float | None = None,
    check_coverage: bool = True,
):
    """Create a new formatted SRT/VTT/QC revision without speech-model inference."""
    from local_subs.exports import export_job

    try:
        policy = formatting_policy(
            config, line_width, max_lines, min_cue_seconds, max_cue_seconds, max_cps
        )
        revision, report = export_job(job_id, output_dir, cues, policy, check_coverage)
        console.print(
            f"Export: {revision}; {report['cue_count']} cues, {report['warning_count']} review issues",
            markup=False,
        )
        console.print(
            "Timings retained. Review qc.json; no automatic meaning or timing accuracy verdict."
        )
    except Exception as exc:
        fail(exc)


@app.command("benchmark")
def benchmark_command(
    media: Path,
    models: str = "small",
    devices: str = "cpu",
    beam_sizes: str = "1,5",
    runs: int = 2,
    start: str = "0",
    duration: str = "30",
    source_language: str = "auto",
    audio_stream: int | None = None,
    model_cache: Path | None = None,
    output_dir: Path = Path("outputs"),
    compute_type: str | None = None,
):
    """Measure cached model/device presets on the same local sample, serially."""
    from local_subs.benchmark import benchmark

    try:
        settings = load_settings(
            source_language=source_language,
            model_cache=model_cache,
            output_dir=output_dir,
            compute_type=compute_type,
        )
        directory, report = benchmark(
            media,
            settings,
            [x.strip() for x in models.split(",") if x.strip()],
            [x.strip() for x in devices.split(",") if x.strip()],
            [int(x.strip()) for x in beam_sizes.split(",") if x.strip()],
            runs,
            parse_time(start),
            parse_time(duration),
            audio_stream,
            notify=lambda message: console.print(message, markup=False),
        )
        console.print(f"Measured results: {directory / 'benchmark.json'}", markup=False)
        console.print(
            "Human meaning/timing/readability ratings remain unverified; OS disk cache is uncontrolled."
        )
    except Exception as exc:
        fail(exc)
    if any(row["status"] == "failed" for row in report["results"]):
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
    pipeline: str | None = None,
    text_model: str | None = None,
    glossary: Path | None = None,
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
            pipeline=pipeline,
            text_model=text_model,
            glossary=read_glossary(glossary),
        )
        if single_pass and settings.pipeline != "direct":
            raise ValueError(
                "Contextual translation requires the default chunked pipeline; omit --single-pass"
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
    pipeline: str | None = None,
    text_model: str | None = None,
    glossary: Path | None = None,
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
                "pipeline": pipeline,
                "text_model": text_model,
                "glossary": read_glossary(glossary),
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
    from local_subs.repository import JobRepository

    table = Table()
    table.add_column("Job ID", no_wrap=True)
    for title in ("State", "Completed chunks", "Source"):
        table.add_column(title)
    repository = JobRepository(output_dir)
    repository.import_snapshots()
    for data in repository.list():
        chunks = data.get("chunks", [])
        table.add_row(
            data["job_id"],
            data["state"],
            f"{sum(c.get('state') == 'completed' for c in chunks)}/{len(chunks)}",
            data.get("source_path", data.get("source", {}).get("path", "")),
        )
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
