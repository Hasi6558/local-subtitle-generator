# Local API

Start in PowerShell from the project directory:

```powershell
.venv\Scripts\local-subs serve --output-dir outputs --media-root test-video --model-cache models
```

Binding is fixed to 127.0.0.1; the default port is 8765. The native picker can
select an existing file anywhere on the server PC. Selection grants persistent
access to that individual file for this output library, including queued workers,
playback and previews. Manual paths must refer to a selected file or an approved
root. Repeat `--media-root` to approve entire folders. The
server controls the output root and model cache; request settings cannot change
these locations. Models must already be explicitly prepared. There is no upload
endpoint, account system, hosted inference or public file server. Phase 5 serves
the built review interface at `/`; only the HTML and hashed `/assets/` files are
public. Job/media/edit/export routes still require a local session/token.

Use a second PowerShell terminal for requests:

```powershell
$api = 'http://127.0.0.1:8765'
$headers = @{ Authorization = 'Bearer ' + (Get-Content outputs/.service/token -Raw).Trim() }
$clip = Get-ChildItem test-video -Filter *.mp4 | Where-Object Length -lt 1000000 | Select-Object -First 1
$body = @{ path = $clip.FullName; settings = @{ source_language = 'ja'; speech_model = 'small'; device = 'cpu'; compute_type = 'int8' } } | ConvertTo-Json -Depth 10
$job = Invoke-RestMethod "$api/jobs" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
Invoke-RestMethod "$api/jobs/$($job.job_id)/progress" -Headers $headers
```

All routes except `/health` require the bearer token or an established local
session cookie. Unapproved Origin headers are rejected, including `null`; Host
headers are restricted to localhost/127.0.0.1. Allowed browser origins match the
configured localhost port. No wildcard CORS is enabled. `POST /session` with bearer
authorization sets an HttpOnly, SameSite=Strict session cookie for local browser
clients; `DELETE /session` clears it. Tokens are not accepted in URL parameters.
The API schema at `/openapi.json` is authenticated; CDN-backed docs are disabled.

| Route | Behavior |
|---|---|
| GET /health | Worker health, PID, bounded restart count and monitor error |
| GET /languages | Backend codes/names, English-only target and evaluation status |
| POST /media/inspect | Inspect a selected file or a path under approved roots; body `{ "path": "..." }` |
| POST /media/pick | Open a native picker anywhere on the server PC and remember the selected file; returns `{ "path": "..." }` or `{ "path": null }` on cancellation |
| POST /jobs | Register a local path and enqueue a durable job |
| GET /jobs | List indexed CLI/API jobs in this output root |
| GET /jobs/{id} | Shared settings, requested/resolved language, checkpoints, state and artifacts |
| GET /jobs/{id}/progress | Poll stage, elapsed time, completed/total chunks, language and errors |
| POST /jobs/{id}/cancel | Request cooperative cancellation; queued work cancels immediately |
| POST /jobs/{id}/retry or /resume | Requeue a failed/cancelled job with its saved settings/checkpoints |
| GET /jobs/{id}/cues?revision=N | Read a cue revision; omitted N selects latest |
| PUT /jobs/{id}/cues | Save validated cues with `expected_revision` and `cues` |
| POST /jobs/{id}/exports | Export a selected cue revision as SRT/VTT/QC |
| GET /jobs/{id}/exports/{export_id}/{artifact} | Download a registered export's allowlisted artifact |
| GET or HEAD /jobs/{id}/media | Stream only that registered job's source, with byte-range support |

Job creation accepts `path`, shared `settings`, optional global `audio_stream`,
integer `start_ms` and positive `duration_ms`. Track/language/model validation and
English transcription routing use the CLI core. Invalid settings/media return
422; unselected paths outside approved roots return 403. Missing jobs/revisions/artifacts
return 404. Model loading is deferred to the worker, so a missing cached model
produces a durable failed job with actionable diagnostics rather than a download.

Selected-file grants live in `.service/selected-media.json` under the output root.
They identify the resolved path and filesystem identity rather than granting a
whole parent folder. Replacing an external selected file with a different file
requires picking it again. Include this metadata when backing up a library.

Cue editing example after completion:

```powershell
$current = Invoke-RestMethod "$api/jobs/$($job.job_id)/cues" -Headers $headers
$current.cues[0].text = 'Corrected English text.'
$edit = @{ expected_revision = $current.revision; cues = $current.cues } | ConvertTo-Json -Depth 20
$saved = Invoke-RestMethod "$api/jobs/$($job.job_id)/cues" -Method Put -Headers $headers -ContentType 'application/json' -Body $edit
$exportBody = @{ revision = $saved.revision } | ConvertTo-Json
$export = Invoke-RestMethod "$api/jobs/$($job.job_id)/exports" -Method Post -Headers $headers -ContentType 'application/json' -Body $exportBody
Invoke-WebRequest "$api/jobs/$($job.job_id)/exports/$($export.export_id)/subtitles.en.srt" -Headers $headers -OutFile "outputs/reviewed-$($export.export_id).srt"
```

Revision 0 is an immutable snapshot of generated cues. Successful saves create new
revisions, mark changed cues as manual, and advance edit versions. Concurrent saves
are checked transactionally: a stale expected revision returns 409 and requires
reload. Structural errors return 422 with actionable QC issues. Deletions/splits
can be represented by an explicitly edited cue list; interactive editing tools are
Phase 5. The backend does not silently replace manual edits after regeneration.

Exports accept `{ "revision": N }` and optional `formatting` review thresholds;
an empty object selects the latest cue revision and saved formatting defaults.
Every export has a new ID and manifest snapshot. Allowed downloads are SRT, VTT,
QC JSON and formatted cue JSON; there is no arbitrary path-download endpoint.
API exports do not rerun coverage VAD. Missing coverage is explicitly reported;
QC success never establishes translation meaning or exact synchronization.

SQLite schema migrations use `PRAGMA user_version` (currently 3). Job manifests,
queue claims/cancellation, cue revisions and export registration share one
repository. On first indexing, unseen legacy manifests are imported. Later JSON
snapshots cannot override authoritative DB state. CLI inference/queue work share
the root lock; one API server and one queue worker own each output root. Polling
comes first; no SSE, distributed queue or background inference in HTTP handlers.

An unexpectedly terminated worker's stale claim is reconciled against durable
chunks and requeued; the supervisor allows at most three crash restarts per server
session, then exposes an error in `/health` and stops restarting. Ordinary model,
media or disk failures are recorded as failed jobs and require explicit retry.
Queued jobs survive server restart. Foreground CLI jobs are not auto-claimed.

Ctrl+C stops new queue work and requests cancellation of active queue inference.
The server allows five seconds for safe shutdown, then terminates its own worker
if necessary. Finished chunks remain durable; the unfinished chunk can restart.
Pending queued jobs remain queued. Cancelled work requires retry/resume. A worker
also detects a dead parent and stops at a safe cancellation check. Native calls
and FFmpeg do not promise immediate interruption. Keep the output database and job
folders together; do not edit/delete SQLite to repair a job.

Verification: real localhost HTTP requests remained responsive during cached
small/CPU/int8 inference. A deliberate worker crash after the first checkpoint
was recovered without rewriting that checkpoint, producing 13 cues. Edits and
cancellation state survived a full server restart. Phase 5 subsequently completed
the full-movie CLI generate/resume/validate/export technical gate before UI work.
GPU and human translation/timing acceptance remain unverified.

Phase 5 adds GET `/models` (cache-only prepared model metadata), GET
`/jobs/{id}/cue-revisions`, GET `/jobs/{id}/qc?revision=N`, and GET
`/jobs/{id}/playback` (selected/default audio metadata). A different selected audio
track requires a preview before browser playback. Create a preview with POST
`/jobs/{id}/preview`, body `{ "force_transcode": false }`; poll GET of the same
route with its `key`, then stream GET `/jobs/{id}/preview/media?key=...`.
Preview state is separate in SQLite schema 3 and never overwrites inference state.
One owned encoder runs asynchronously; completed files are content-hash checked.

POST `/jobs` additionally accepts optional `parent_job_id` for a replacement
proposal. The parent must reference the same source file. Parent cues/edits stay
unchanged; the UI requires explicit proposed-text acceptance. No generic path/file
download, browser upload or automatic replacement of manual corrections was added.
