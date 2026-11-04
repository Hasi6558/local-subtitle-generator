"""Persist access to individual files explicitly selected in the native picker."""

import json
from pathlib import Path

from local_subs.jobs import write_json


def selections(root):
    path = root / ".service" / "selected-media.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def identity(path):
    stat = path.stat()
    return {"path": str(path), "device": stat.st_dev, "inode": stat.st_ino}


def allow_selected_file(root, path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose an existing media file")
    entries = [entry for entry in selections(root) if Path(entry["path"]) != path]
    write_json(root / ".service" / "selected-media.json", entries + [identity(path)])
    return path


def is_selected(root, path):
    current = identity(path)
    return any(
        Path(entry["path"]) == path
        and entry["device"] == current["device"]
        and entry["inode"] == current["inode"]
        for entry in selections(root)
    )
