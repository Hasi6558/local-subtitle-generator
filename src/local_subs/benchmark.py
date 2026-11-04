"""Isolated local benchmarks; no downloads and no automatic quality verdict."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from local_subs.config import Settings
from local_subs.jobs import write_json


def peak_memory():
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                ] + [
                    (name, ctypes.c_size_t)
                    for name in (
                        "PeakWorkingSetSize",
                        "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage",
                        "PagefileUsage",
                        "PeakPagefileUsage",
                    )
                ]

            kernel = ctypes.windll.kernel32
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            function = ctypes.windll.psapi.GetProcessMemoryInfo
            function.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(Counters),
                wintypes.DWORD,
            ]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if function(
                kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return counters.PeakWorkingSetSize
        else:
            import resource

            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(value * (1 if sys.platform == "darwin" else 1024))
    except (ImportError, OSError, AttributeError):
        pass
    return None


def worker(request_path):
    from local_subs.inference import load_model
    from local_subs.resumable import generate, read_manifest

    request = json.loads(request_path.read_text(encoding="utf-8"))
    settings = Settings.model_validate(request["settings"])
    model, runtime = None, None

    def loader(config, notify):
        nonlocal model, runtime
        if model is None:
            model, runtime = load_model(config, notify)
        return model, runtime

    results = []
    for repetition in range(request["runs"]):
        started = time.perf_counter()
        result = {
            "settings": settings.model_dump(mode="json"),
            "repetition": repetition + 1,
            "cache": {
                "weights": "prepared local cache only",
                "model_instance": "cold" if repetition == 0 else "warm",
                "inference_results": "new job; no checkpoint reuse",
                "os_cache": "uncontrolled",
            },
            "human_review": {
                "meaning": "unverified",
                "timing": "unverified",
                "readability": "unverified",
            },
        }
        try:
            directory = generate(
                Path(request["media"]),
                settings,
                request["audio_stream"],
                request["start_ms"],
                request["duration_ms"],
                notify=lambda message: print(message, flush=True),
                model_loader=loader,
            )
            manifest = read_manifest(directory)
            duration = manifest["sample_duration_ms"] / 1000
            result.update(
                status="measured",
                job_id=directory.name,
                job_directory=str(directory),
                resolved_source_language=manifest["resolved_source_language"],
                model_runtime=manifest.get("runtime"),
                audio_seconds=duration,
                stage_seconds=manifest.get("stage_seconds", {}),
                qc=manifest.get("qc_summary", {}),
            )
            result["total_seconds"] = round(time.perf_counter() - started, 6)
            result["real_time_factor"] = round(result["total_seconds"] / duration, 6)
        except Exception as exc:
            result.update(
                status="failed",
                error=str(exc),
                total_seconds=round(time.perf_counter() - started, 6),
            )
        result["peak_process_rss_bytes"] = peak_memory()
        if model is None:
            result["cache"]["model_instance"] = "not_loaded"
        result["memory_scope"] = (
            "preset worker process lifetime peak so far; includes earlier repetitions"
        )
        result["peak_gpu_memory_bytes"] = None
        results.append(result)
        write_json(Path(request["response"]), results)
        if result["status"] == "failed":
            break  # Do not repeat missing dependencies or failed inference automatically.


def benchmark(
    media,
    settings,
    models,
    devices,
    beams,
    runs=2,
    start_ms=0,
    duration_ms=30000,
    audio_stream=None,
    notify=lambda _: None,
    runner=subprocess.run,
):
    from local_subs.worker import worker_lock

    if not models or not devices or not beams or not 1 <= runs <= 5:
        raise ValueError("Choose at least one model/device/beam and 1–5 repetitions")
    if duration_ms <= 0:
        raise ValueError("Benchmark duration must be positive")
    if not media.is_file():
        raise ValueError(f"Media does not exist: {media}")
    root = settings.output_dir.resolve()
    directory = root / f"benchmark-{uuid4().hex}"
    directory.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "source_path": str(media.resolve()),
        "requested_start_ms": start_ms,
        "requested_duration_ms": duration_ms,
        "runs_per_preset": runs,
        "measurement_notes": [
            "No speed extrapolations or automatic translation-quality ratings",
            "Fresh worker per preset; weights cached; first model instance cold, later repetitions warm",
            "OS disk cache uncontrolled; total excludes worker startup",
            "Peak memory is process RSS, not GPU VRAM, and is cumulative within each preset worker",
        ],
        "results": [],
    }
    with worker_lock(root, directory.name):
        for model in models:
            for device in devices:
                for beam in beams:
                    preset = Settings.model_validate(
                        settings.model_dump()
                        | {
                            "speech_model": model,
                            "device": device,
                            "beam_size": beam,
                            "output_dir": directory / "jobs",
                        }
                    )
                    run_id = uuid4().hex
                    request, response = (
                        directory / f"{run_id}-request.json",
                        directory / f"{run_id}-result.json",
                    )
                    write_json(
                        request,
                        {
                            "settings": preset.model_dump(mode="json"),
                            "media": str(media.resolve()),
                            "runs": runs,
                            "start_ms": start_ms,
                            "duration_ms": duration_ms,
                            "audio_stream": audio_stream,
                            "response": str(response),
                        },
                    )
                    notify(
                        f"Benchmarking cached {model}/{device}, beam {beam}; {runs} repetition(s)"
                    )
                    with (directory / f"{run_id}.log").open(
                        "w", encoding="utf-8"
                    ) as log:
                        process = runner(
                            [
                                sys.executable,
                                "-m",
                                "local_subs.benchmark",
                                str(request),
                            ],
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            check=False,
                        )
                    if response.is_file():
                        report["results"].extend(
                            json.loads(response.read_text(encoding="utf-8"))
                        )
                    else:
                        report["results"].append(
                            {
                                "status": "failed",
                                "settings": preset.model_dump(mode="json"),
                                "error": f"Worker exited {process.returncode} without a response; see {log.name}",
                            }
                        )
                    write_json(directory / "benchmark.json", report)
    return directory, report


if __name__ == "__main__":
    worker(Path(sys.argv[1]))
