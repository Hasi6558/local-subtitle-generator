"""Durable local queue worker, run in a process separate from HTTP."""

import json
import sys
import time
from pathlib import Path

from local_subs.config import Settings
from local_subs.inference import load_model
from local_subs.jobs import write_json
from local_subs.repository import JobRepository
from local_subs.resumable import Cancelled, run
from local_subs.worker import active_worker, process_alive


def allowed_media(path, roots, output_root=None):
    path = path.resolve()
    from local_subs.media_access import is_selected

    if not path.is_file() or not (
        any(path.is_relative_to(root.resolve()) for root in roots)
        or (output_root is not None and is_selected(output_root, path))
    ):
        raise PermissionError(
            "Choose this file using Choose video, or use a file under an approved media root"
        )
    return path


def work_once(root, roots, model_loader=load_model, parent_pid=None):
    repository = JobRepository(root)
    if active_worker(root):
        return False
    manifest = repository.claim()
    if not manifest:
        return False
    directory = root / manifest["job_id"]
    try:
        allowed_media(Path(manifest["source_path"]), roots, root)
        settings = Settings.model_validate(manifest["settings"])
        run(
            directory,
            manifest,
            settings,
            lambda message: print(message, flush=True),
            model_loader,
            reset_cancel=False,
            cancelled=lambda: (
                (root / ".service" / "stop.request").exists()
                or (parent_pid is not None and not process_alive(parent_pid))
            ),
        )
    except (Cancelled, KeyboardInterrupt):
        pass  # run persisted cancellation and checkpoints.
    except Exception as exc:
        current = repository.get(manifest["job_id"])
        if current["state"] not in ("failed", "cancelled"):
            current.update(
                state="failed",
                failure_stage="worker_dispatch",
                error={
                    "message": str(exc),
                    "type": type(exc).__name__,
                    "retry_hint": "Correct the error and explicitly retry this job",
                },
            )
            write_json(directory / "manifest.json", current)
        print(f"Job failed: {exc}", flush=True)
    return True


def main(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["output_root"])
    roots = [Path(path) for path in config["media_roots"]]
    repository = JobRepository(root)
    repository.recover()
    while not (root / ".service" / "stop.request").exists() and process_alive(
        config["parent_pid"]
    ):
        if not work_once(root, roots, parent_pid=config["parent_pid"]):
            time.sleep(0.25)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
