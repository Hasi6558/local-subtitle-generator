"""Authenticated loopback API over the shared core and authoritative job repository."""

import copy
import hmac
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from local_subs.api_worker import allowed_media
from local_subs.config import Settings, languages
from local_subs.exports import write_quality_artifacts
from local_subs.jobs import atomic_text, write_json
from local_subs.media import inspect_media
from local_subs.policy import FormattingPolicy
from local_subs.quality import assess, read_cues
from local_subs.repository import Conflict, JobRepository
from local_subs.resumable import prepare
from local_subs.service import WorkerManager


class CreateJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path
    settings: Settings = Field(default_factory=Settings)
    audio_stream: int | None = Field(default=None, ge=0)
    start_ms: int = Field(default=0, ge=0, strict=True)
    duration_ms: int | None = Field(default=None, gt=0, strict=True)


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: Path


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    cues: list[dict]


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int | None = Field(default=None, ge=0)
    formatting: FormattingPolicy | None = None


def create_app(
    output_root, media_roots, model_cache=None, token=None, port=8765, start_worker=True
):
    root = Path(output_root).resolve()
    roots = [Path(path).resolve() for path in media_roots]
    if not roots or any(not path.is_dir() for path in roots):
        raise ValueError("Configure at least one existing approved media folder")
    repository = JobRepository(root)
    repository.import_snapshots()
    cache = Path(model_cache or Settings().model_cache).resolve()
    token_path = root / ".service" / "token"
    if token is None:
        if token_path.is_file():
            token = token_path.read_text(encoding="utf-8").strip()
        else:
            token = secrets.token_urlsafe(32)
            atomic_text(token_path, token)
    if not token:
        raise ValueError("Local API token cannot be empty")
    origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @asynccontextmanager
    async def lifespan(app):
        manager = WorkerManager(root, roots) if start_worker else None
        app.state.manager = manager
        if manager:
            await manager.start()
        try:
            yield
        finally:
            if manager:
                await manager.stop()

    app = FastAPI(
        title="Local Subtitles API",
        version="0.1.0.dev0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.repository = repository
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_session(request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in origins:
            return JSONResponse({"detail": "Origin is not approved"}, status_code=403)
        if request.url.path != "/health":
            authorization = request.headers.get("authorization", "")
            supplied = (
                authorization[7:]
                if authorization.startswith("Bearer ")
                else request.cookies.get("local_subs_session", "")
            )
            if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                return JSONResponse(
                    {"detail": "A local API token is required"}, status_code=401
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PermissionError)
    async def forbidden_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(ValueError)
    async def invalid_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def job(job_id):
        return repository.get(job_id)

    def safe_output(path, directory):
        path = Path(path).resolve()
        if (
            not directory.resolve().is_relative_to(root)
            or not path.is_relative_to(directory.resolve())
            or not path.is_file()
        ):
            raise HTTPException(404, "Artifact is unavailable")
        return path

    def cue_revision(job_id, revision=None):
        manifest = job(job_id)
        try:
            return repository.cues(job_id, revision=revision)
        except KeyError:
            if manifest["state"] not in ("completed", "empty"):
                raise Conflict("Cues are available after successful completion")
            artifacts = manifest.get("artifacts", {})
            path = artifacts.get("formatted_cues.json") or artifacts.get(
                "generated_cues.json"
            )
            if not path:
                raise Conflict("No generated cues available")
            baseline = read_cues(safe_output(path, root / job_id))
            repository.cues(job_id, baseline=baseline)
            return repository.cues(job_id, revision=revision)

    @app.get("/health")
    def health():
        manager = getattr(app.state, "manager", None)
        return {
            "status": "ok",
            "worker": manager.status()
            if manager
            else {"running": False, "disabled": True},
        }

    @app.post("/session")
    def session():
        response = JSONResponse({"status": "authenticated"})
        response.set_cookie(
            "local_subs_session", token, httponly=True, samesite="strict"
        )
        return response

    @app.delete("/session")
    def end_session():
        response = Response(status_code=204)
        response.delete_cookie("local_subs_session")
        return response

    @app.get("/languages")
    def supported_languages():
        return {
            "target_language": "en",
            "languages": [
                {
                    "code": code,
                    "name": name,
                    "evaluation": "Japanese CPU clips; human review pending"
                    if code == "ja"
                    else "not evaluated",
                }
                for code, name in languages().items()
            ],
        }

    @app.post("/media/inspect")
    def inspect(request: InspectRequest):
        return inspect_media(allowed_media(request.path, roots))

    @app.post("/jobs", status_code=201)
    def create(request: CreateJob):
        media = allowed_media(request.path, roots)
        settings = Settings.model_validate(
            request.settings.model_dump() | {"output_dir": root, "model_cache": cache}
        )
        directory, manifest = prepare(
            media,
            settings,
            request.audio_stream,
            request.start_ms,
            request.duration_ms,
            queued=True,
        )
        return repository.get(directory.name)

    @app.get("/jobs")
    def list_jobs():
        return repository.list()

    @app.get("/jobs/{job_id}")
    def show(job_id: str):
        return job(job_id)

    @app.get("/jobs/{job_id}/progress")
    def progress(job_id: str):
        manifest = job(job_id)
        chunks = manifest.get("chunks", [])
        return {
            "job_id": job_id,
            "state": manifest["state"],
            "stage": manifest.get("stage"),
            "elapsed_seconds": manifest.get("elapsed_seconds"),
            "completed_chunks": sum(c.get("state") == "completed" for c in chunks),
            "total_chunks": len(chunks),
            "requested_source_language": manifest.get(
                "requested_source_language", manifest["settings"]["source_language"]
            ),
            "resolved_source_language": manifest.get("resolved_source_language"),
            "cancel_requested": manifest.get("cancel_requested", False),
            "error": manifest.get("error"),
        }

    @app.post("/jobs/{job_id}/cancel", status_code=202)
    def cancel(job_id: str):
        job(job_id)
        return repository.request_cancel(job_id)

    @app.post("/jobs/{job_id}/retry", status_code=202)
    @app.post("/jobs/{job_id}/resume", status_code=202)
    def retry(job_id: str):
        job(job_id)
        return repository.requeue(job_id)

    @app.get("/jobs/{job_id}/cues")
    def get_cues(job_id: str, revision: int | None = None):
        return cue_revision(job_id, revision)

    @app.put("/jobs/{job_id}/cues")
    def edit(job_id: str, request: EditRequest):
        manifest = job(job_id)
        previous = cue_revision(job_id)
        if previous["revision"] != request.expected_revision:
            raise Conflict("Cue revision changed; reload before saving")
        end = manifest["sample_start_ms"] + manifest["sample_duration_ms"]
        report = assess(request.cues, playable_end_ms=end)
        if report["error_count"]:
            raise HTTPException(422, detail=report)
        cues = copy.deepcopy(request.cues)
        old = {cue["id"]: cue for cue in previous["cues"]}
        for cue in cues:
            source = old.get(cue["id"], {})
            changed = any(
                cue.get(key) != source.get(key)
                for key in ("text", "start_ms", "end_ms")
            )
            cue["edit_version"] = source.get("edit_version", 0) + int(changed)
            cue["origin"] = "manual" if changed else source.get("origin", "model")
        return repository.edit_cues(job_id, request.expected_revision, cues)

    @app.post("/jobs/{job_id}/exports", status_code=201)
    def export(job_id: str, request: ExportRequest):
        manifest = job(job_id)
        selected = cue_revision(job_id, request.revision)
        identifier = uuid4().hex
        directory = root / job_id / "exports" / identifier
        policy = (
            request.formatting
            or Settings.model_validate(manifest["settings"]).formatting
        )
        report = write_quality_artifacts(
            directory,
            selected["cues"],
            manifest["sample_start_ms"] + manifest["sample_duration_ms"],
            policy,
        )
        write_json(
            directory / "export_manifest.json",
            {
                "job_manifest": manifest,
                "cue_revision": selected["revision"],
                "policy": policy.model_dump(),
                "coverage": "unavailable: API export does not rerun VAD",
            },
        )
        repository.record_export(identifier, job_id, selected["revision"], directory)
        return {
            "export_id": identifier,
            "cue_revision": selected["revision"],
            "qc": report,
            "artifacts": [
                "subtitles.en.srt",
                "subtitles.en.vtt",
                "qc.json",
                "formatted_cues.json",
            ],
        }

    @app.get("/jobs/{job_id}/exports/{export_id}/{artifact}")
    def download(job_id: str, export_id: str, artifact: str):
        job(job_id)
        if artifact not in (
            "subtitles.en.srt",
            "subtitles.en.vtt",
            "qc.json",
            "formatted_cues.json",
        ):
            raise HTTPException(404, "Unknown artifact")
        metadata = repository.export(job_id, export_id)
        directory = root / job_id / "exports" / export_id
        if Path(metadata["directory"]).resolve() != directory.resolve():
            raise HTTPException(404, "Artifact is unavailable")
        return FileResponse(
            safe_output(directory / artifact, directory), filename=artifact
        )

    @app.get("/jobs/{job_id}/media")
    @app.head("/jobs/{job_id}/media")
    def media(job_id: str):
        manifest = job(job_id)
        source = manifest.get("source_path") or manifest.get("source", {}).get("path")
        return FileResponse(allowed_media(Path(source), roots))

    return app
