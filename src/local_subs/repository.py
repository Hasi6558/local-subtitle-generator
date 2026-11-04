"""SQLite is authoritative; JSON manifests are reproducibility snapshots."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(c in "0123456789abcdef" for c in value)
    )


class JobRepository:
    def __init__(self, root):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "jobs.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            schema = connection.execute("PRAGMA user_version").fetchone()[0]
            if schema > 2:
                raise ValueError("Job database is newer than this application")
            if schema < 1:
                connection.execute(
                    "CREATE TABLE jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, manifest TEXT NOT NULL, updated_at TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version=1")
            if schema < 2:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN mode TEXT NOT NULL DEFAULT 'foreground'"
                )
                connection.execute("ALTER TABLE jobs ADD COLUMN owner_pid INTEGER")
                connection.execute(
                    "CREATE TABLE cue_revisions (job_id TEXT NOT NULL REFERENCES jobs(id), revision INTEGER NOT NULL, cues TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(job_id, revision))"
                )
                connection.execute(
                    "CREATE TABLE exports (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), cue_revision INTEGER NOT NULL, directory TEXT NOT NULL, created_at TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def get(self, job_id):
        if not valid_id(job_id):
            raise KeyError("Invalid job ID")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT manifest FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        if not row:
            raise KeyError("Job not found")
        return json.loads(row["manifest"])

    def save(self, manifest):
        job_id = manifest["job_id"]
        if not valid_id(job_id):
            raise ValueError("Invalid job ID")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT manifest,owner_pid FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            data = dict(manifest)
            if row and json.loads(row["manifest"]).get("cancel_requested"):
                data["cancel_requested"] = True
            data["updated_at"] = data.get("updated_at") or now()
            owner = row["owner_pid"] if row else None
            if data["state"] in ("completed", "failed", "cancelled", "empty"):
                owner = None
            connection.execute(
                "INSERT INTO jobs(id,state,manifest,updated_at,mode,owner_pid) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,manifest=excluded.manifest,updated_at=excluded.updated_at,mode=excluded.mode,owner_pid=excluded.owner_pid",
                (
                    job_id,
                    data["state"],
                    json.dumps(data, ensure_ascii=False, default=str),
                    data["updated_at"],
                    data.get("execution_mode", "foreground"),
                    owner,
                ),
            )
        return data

    def import_snapshots(self):
        imported = 0
        for path in self.root.glob("*/manifest.json"):
            if not valid_id(path.parent.name):
                continue
            try:
                self.get(path.parent.name)
            except KeyError:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("job_id") == path.parent.name:
                    self.save(data)
                    imported += 1
        return imported

    def list(self):
        with self.connect() as connection:
            return [
                json.loads(row["manifest"])
                for row in connection.execute(
                    "SELECT manifest FROM jobs ORDER BY updated_at DESC"
                )
            ]

    def clear_cancel(self, job_id):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            data = json.loads(
                connection.execute(
                    "SELECT manifest FROM jobs WHERE id=?", (job_id,)
                ).fetchone()[0]
            )
            data["cancel_requested"] = False
            connection.execute(
                "UPDATE jobs SET manifest=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), job_id),
            )

    def request_cancel(self, job_id):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT manifest FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError("Job not found")
            data = json.loads(row[0])
            if data["state"] in ("completed", "empty"):
                raise Conflict("Job has already completed")
            data["cancel_requested"] = True
            data["updated_at"] = now()
            if data["state"] in ("queued", "failed", "cancelled"):
                data["state"] = "cancelled"
            connection.execute(
                "UPDATE jobs SET state=?,manifest=?,updated_at=? WHERE id=?",
                (data["state"], json.dumps(data, ensure_ascii=False), now(), job_id),
            )
        return data

    def requeue(self, job_id):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT manifest FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError("Job not found")
            data = json.loads(row[0])
            if data["state"] not in ("failed", "cancelled"):
                raise Conflict("Only failed or cancelled jobs can be retried")
            data.update(
                state="queued",
                execution_mode="queued",
                cancel_requested=False,
                stage="queued",
            )
            data["updated_at"] = now()
            if "error" in data:
                data["last_error"] = data.pop("error")
            data.pop("failure_stage", None)
            connection.execute(
                "UPDATE jobs SET state='queued',mode='queued',owner_pid=NULL,manifest=?,updated_at=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), now(), job_id),
            )
        return data

    def claim(self):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,manifest FROM jobs WHERE state='queued' AND mode='queued' ORDER BY updated_at,id LIMIT 1"
            ).fetchone()
            if not row:
                return None
            data = json.loads(row["manifest"])
            data.update(state="preparing", stage="dispatch")
            data["updated_at"] = now()
            connection.execute(
                "UPDATE jobs SET state='preparing',owner_pid=?,manifest=? WHERE id=?",
                (os.getpid(), json.dumps(data, ensure_ascii=False), row["id"]),
            )
            return data

    def recover(self):
        from local_subs.worker import process_alive

        recovered = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM jobs WHERE mode='queued' AND state IN ('preparing','processing','exporting')"
            ).fetchall()
            for row in rows:
                if row["owner_pid"] and process_alive(row["owner_pid"]):
                    continue
                data = json.loads(row["manifest"])
                state = "cancelled" if data.get("cancel_requested") else "queued"
                data.update(
                    state=state,
                    stage="recovered",
                    recovery_note="Previous worker stopped; matching durable chunks will be resumed",
                )
                connection.execute(
                    "UPDATE jobs SET state=?,owner_pid=NULL,manifest=?,updated_at=? WHERE id=?",
                    (state, json.dumps(data, ensure_ascii=False), now(), row["id"]),
                )
                recovered.append(row["id"])
        return recovered

    def cues(self, job_id, baseline=None, revision=None):
        with self.connect() as connection:
            if baseline is not None:
                connection.execute(
                    "INSERT OR IGNORE INTO cue_revisions VALUES(?,?,?,?)",
                    (job_id, 0, json.dumps(baseline, ensure_ascii=False), now()),
                )
            if revision is None:
                row = connection.execute(
                    "SELECT revision,cues FROM cue_revisions WHERE job_id=? ORDER BY revision DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT revision,cues FROM cue_revisions WHERE job_id=? AND revision=?",
                    (job_id, revision),
                ).fetchone()
            if not row:
                raise KeyError("Cue revision not found")
            return {"revision": row["revision"], "cues": json.loads(row["cues"])}

    def edit_cues(self, job_id, expected, cues):
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT MAX(revision) FROM cue_revisions WHERE job_id=?", (job_id,)
            ).fetchone()
            current = row[0]
            if current is None or current != expected:
                raise Conflict(
                    f"Edit conflict: expected {expected}, current revision is {current}; reload cues"
                )
            revision = current + 1
            connection.execute(
                "INSERT INTO cue_revisions VALUES(?,?,?,?)",
                (job_id, revision, json.dumps(cues, ensure_ascii=False), now()),
            )
        return {"revision": revision, "cues": cues}

    def record_export(self, export_id, job_id, revision, directory):
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO exports VALUES(?,?,?,?,?)",
                (export_id, job_id, revision, str(directory), now()),
            )

    def export(self, job_id, export_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM exports WHERE id=? AND job_id=?", (export_id, job_id)
            ).fetchone()
            if not row:
                raise KeyError("Export not found")
            return dict(row)
