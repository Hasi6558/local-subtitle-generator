"""Manage a single queue process with bounded crash recovery and clean shutdown."""

import asyncio
import os
import subprocess
import sys

from local_subs.jobs import atomic_text, write_json
from local_subs.repository import Conflict, JobRepository
from local_subs.worker import worker_lock


class WorkerManager:
    def __init__(self, root, media_roots):
        self.root = root
        self.roots = media_roots
        self.repository = JobRepository(root)
        self.process = None
        self.restarts = 0
        self.stopping = False
        self.error = None

    def spawn(self):
        folder = self.root / ".service"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "stop.request").unlink(missing_ok=True)
        path = folder / "worker-config.json"
        write_json(
            path,
            {
                "output_root": str(self.root),
                "media_roots": [str(root) for root in self.roots],
                "parent_pid": os.getpid(),
            },
        )
        with (folder / "worker.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "local_subs.api_worker", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

    async def start(self):
        self.lock = worker_lock(self.root / ".service", "api-server")
        self.lock.__enter__()
        try:
            self.repository.import_snapshots()
            self.repository.recover()
            self.spawn()
            self.monitor = asyncio.create_task(self.watch())
        except BaseException:
            self.lock.__exit__(None, None, None)
            raise

    async def watch(self):
        while not self.stopping:
            await asyncio.sleep(0.5)
            if self.process.poll() is None:
                continue
            self.repository.recover()
            if self.restarts >= 3:
                self.error = "Worker stopped repeatedly; inspect .service/worker.log and restart the server"
                return
            self.restarts += 1
            self.spawn()

    async def stop(self):
        try:
            await self._stop_worker()
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                await asyncio.to_thread(self.process.wait)
            self.lock.__exit__(None, None, None)

    async def _stop_worker(self):
        self.stopping = True
        self.monitor.cancel()
        try:
            await self.monitor
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.error = f"Worker monitor stopped: {exc}"
        atomic_text(self.root / ".service" / "stop.request", "stop")
        for manifest in self.repository.list():
            if manifest.get("execution_mode") == "queued" and manifest["state"] in (
                "preparing",
                "processing",
                "exporting",
            ):
                try:
                    self.repository.request_cancel(manifest["job_id"])
                except Conflict:
                    pass
        if self.process.poll() is None:
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                await asyncio.to_thread(self.process.wait)
        self.repository.recover()

    def status(self):
        return {
            "running": self.process is not None and self.process.poll() is None,
            "pid": self.process.pid if self.process else None,
            "restarts": self.restarts,
            "error": self.error,
        }
