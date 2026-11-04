"""Stop an owned text server when its worker parent disappears."""

import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from local_subs.worker import process_alive
from local_subs.jobs import write_json


def peak_rss(process):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak",
                "current",
                "qpp",
                "qp",
                "qnpp",
                "qnp",
                "page",
                "peakpage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    function = ctypes.windll.psapi.GetProcessMemoryInfo
    function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    return (
        counters.peak
        if function(
            wintypes.HANDLE(int(process._handle)), ctypes.byref(counters), counters.cb
        )
        else None
    )


def main(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    stopped = threading.Event()
    if config.get("stdin_control"):

        def control():
            sys.stdin.buffer.read(1)
            stopped.set()  # A stop byte or parent pipe closure both stop native work.

        threading.Thread(target=control, daemon=True).start()
    environment = os.environ.copy()
    environment["HF_HUB_OFFLINE"] = "1"
    environment["PATH"] = (
        str(Path(config["command"][0]).parent)
        + os.pathsep
        + environment.get("PATH", "")
    )
    with Path(config["log_file"]).open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            config["command"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            peak = 0
            while (
                process.poll() is None
                and process_alive(config["parent_pid"])
                and not Path(config["stop_file"]).exists()
                and not stopped.is_set()
            ):
                peak = max(peak, peak_rss(process) or 0)
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            try:
                write_json(
                    config_path.with_suffix(".metrics.json"),
                    {
                        "pid": process.pid,
                        "peak_native_rss_bytes": peak or None,
                        "scope": "native text-server process working set sampled every 0.2s; excludes speech and parent",
                    },
                )
            except OSError:
                pass  # Diagnostics must never prevent native cleanup.


if __name__ == "__main__":
    main(Path(sys.argv[1]))
