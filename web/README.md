# Local subtitle review

React + TypeScript + Vite assets are served by the existing local API, without
hosted assets or frontend runtime services. Tested on Windows with Node 24.19.0 /
npm 11.17.0. Dependencies are pinned. Install the Python project first, then:

```powershell
npm --prefix web ci
npm --prefix web run build
.venv\Scripts\local-subs serve --output-dir outputs/phase2-movie --media-root test-video --model-cache models
```

Open http://127.0.0.1:8765. Paste the key from the token file printed by the server
to connect; it becomes an HttpOnly local session cookie. Keys are not stored in
browser storage or URL parameters. Choose the same output root as existing jobs;
other roots have separate libraries. Approve other media folders with repeated
`--media-root`. The CLI works without Node, built assets or a browser.

- New subtitles: enter a local path, inspect tracks, select language/model and an
  optional sample. Prepared-model status prevents starting with uncached weights;
  refresh it after a CLI download. Files stay in place; there is no upload flow.
- Library: watch stage/chunk progress, cancel or resume/retry, and review completed
  results. Model loading has no fabricated exact completion percentage.
- Review: select a cue to seek, replay, edit text/times, search and filter QC flags.
  Arrows select cues, Space plays/pauses and R replays outside text fields. Selected
  and playing cues are highlighted; keyboard selection scrolls within the cue list.
- Autosave waits 700 ms after typing and shows unsaved/saving/saved/error state.
  Edits arriving during a save are subsequently saved. Conflicts retain the draft;
  download a copy or explicitly reload the server version. Browser draft recovery
  is best-effort; storage failures do not block server saves. Undo creates a new
  revision. Invalid content/times block saves/exports with feedback.
- Split requires an explicit word boundary/time; the suggested midpoint is not
  acoustic alignment. Merge keeps both texts and source links. Earlier server
  revisions remain available. QC flags are review hints, not accuracy scores.
- Export chooses generated revision 0 or a saved edited revision and prepares new
  SRT/VTT downloads. Browser settings choose the destination. “Edited” does not
  claim reviewed meaning or synchronization.

Reprocess selection creates a separate range job linked to its parent. Original
corrections stay intact. Compare a completed proposal and explicitly apply its
text to a selected cue; original timing stays unchanged. This manual proposal
workflow does not claim Phase 7 automatic selective stitching/alignment.

Request a compatible preview for unsupported browser codecs/containers. Selecting
an audio track other than the container default requires a selected-track preview
to avoid reviewing against the wrong audio. H.264/AAC are remuxed when possible;
other codecs are transcoded. A forced retry encodes both streams. Preview files
preserve the movie timeline, are hash-verified/source-track-keyed and never modify
the original. One encoder runs at a time, asynchronously to HTTP. Interrupted
previews can be requested again. Local API/inference behavior remains independent.

Tests from the project root:

```powershell
npm --prefix web run build
npm --prefix web test
npm --prefix web run test:e2e
.venv\Scripts\python -m pytest -q
```

Default browser checks use isolated synthetic media/cues and test-only prepared
model metadata; they never download or run inference. Windows browser tests use
installed Chrome for codec support. The Python venv must be at `.venv`; other
OS/browser combinations are unverified. Fixture routes exist only in the test
server, not the production API. Reports/screenshots/data remain ignored locally.

Optional real-media/model browser acceptance (prepared small model in `models/`):

```powershell
$env:LOCAL_SUBS_UI_LIVE = '1'
$env:LOCAL_SUBS_TEST_MEDIA = (Get-ChildItem test-video -Filter *.mp4 | Where-Object Length -lt 1000000 | Select-Object -First 1).FullName
npm --prefix web run test:e2e
Remove-Item Env:LOCAL_SUBS_UI_LIVE
```

This creates a real job through the UI, waits for inference, edits/reloads,
prepares a preview, seeks and downloads the edited SRT. `npm --prefix web run dev`
watches production assets; reload the API-served page after changes.
