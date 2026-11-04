"""One local worker per output root; stale process locks are recoverable."""

import ctypes
import json
import os
from contextlib import contextmanager


def process_alive(pid):
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.GetLastError() == 5
        code = wintypes.DWORD()
        try:
            return (
                bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
                and code.value == 259
            )
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def active_worker(root):
    lock = root / ".worker.lock"
    try:
        data = json.loads(lock.read_text())
        return data if process_alive(data["pid"]) else None
    except FileNotFoundError:
        return None
    except (ValueError, KeyError):
        raise ValueError(
            "Worker lock is incomplete; ensure no worker is starting before retrying"
        )


@contextmanager
def worker_lock(root, job_id):
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".worker.lock"
    if lock.exists():
        active = active_worker(root)
        if active:
            raise ValueError(
                f"Worker already active for job {active['job_id']}; wait or cancel it"
            )
        lock.unlink(missing_ok=True)
    try:
        handle = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise ValueError("Another worker started; retry when it finishes") from exc
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump({"pid": os.getpid(), "job_id": job_id}, stream)
        yield
    finally:
        lock.unlink(missing_ok=True)
