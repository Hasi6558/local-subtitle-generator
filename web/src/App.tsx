import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, downloadDraft, post } from "./api";
import { clock, mergeCue, parseClock, splitCue, wordBoundary } from "./editing";
import { useEditor } from "./useEditor";
import {
  fileName,
  sourcePath,
  type Cue,
  type Job,
  type Preview,
  type QC,
  type Seed,
  type Settings,
} from "./types";

const label = (value: string) => value.replaceAll("_", " ");
const message = (err: unknown) => {
  if (err instanceof Error && err.name === "AbortError") return "";
  if (
    err instanceof Error &&
    ["NotAllowedError", "NotSupportedError"].includes(err.name)
  )
    return "Playback could not start. Use the player controls or prepare a compatible preview.";
  return err instanceof Error ? err.message : String(err);
};
const navigate = (path: string) => {
  location.hash = path;
};
const errorText = (job: Job) =>
  typeof job.error === "string" ? job.error : job.error?.message;
type Language = { code: string; name: string };
type ModelInfo = {
  models: { id: string; prepared: boolean }[];
  model_cache: string;
};

function Logo() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="2"
        y="3"
        width="24"
        height="20"
        rx="5"
        stroke="currentColor"
        strokeWidth="2"
      />
      <path
        d="M7 12h14M7 17h9M19 23l-3 3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function App() {
  const [auth, setAuth] = useState<boolean | null>(null),
    [key, setKey] = useState(""),
    [error, setError] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]),
    [languages, setLanguages] = useState<Language[]>([]),
    [models, setModels] = useState<ModelInfo>({ models: [], model_cache: "" });
  const [route, setRoute] = useState(location.hash.slice(1) || "/"),
    [seed, setSeed] = useState<Seed | null>(null),
    [proposal, setProposal] = useState<string | null>(null);
  const [worker, setWorker] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const [items, health] = await Promise.all([
        api<Job[]>("/jobs"),
        api<{ worker: { running: boolean } }>("/health"),
      ]);
      setJobs(items);
      setWorker(health.worker.running);
      setAuth(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setAuth(false);
      else setError(message(err));
    }
  }, []);
  useEffect(() => {
    void refresh();
    const change = () => setRoute(location.hash.slice(1) || "/");
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, [refresh]);
  useEffect(() => {
    if (!auth) return;
    void Promise.all([
      api<{ languages: Language[] }>("/languages"),
      api<ModelInfo>("/models"),
    ])
      .then(([data, prepared]) => {
        setLanguages(data.languages);
        setModels(prepared);
      })
      .catch((err) => setError(message(err)));
    const timer = setInterval(() => void refresh(), 2000);
    return () => clearInterval(timer);
  }, [auth, refresh]);
  const connect = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await api("/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${key.trim()}` },
      });
      setKey("");
      setError("");
      await refresh();
    } catch (err) {
      setError(message(err));
    }
  };
  const reprocess = (job: Job, cue?: Cue) => {
    setSeed({
      path: sourcePath(job),
      settings: {
        ...job.settings,
        source_language:
          job.resolved_source_language || job.settings.source_language,
      },
      audio_stream: job.audio_stream,
      start_ms: cue ? Math.max(0, cue.start_ms - 2000) : job.sample_start_ms,
      duration_ms: cue
        ? cue.end_ms - cue.start_ms + 4000
        : job.sample_duration_ms,
      parent_job_id: job.job_id,
    });
    navigate("/new");
  };
  const created = async (job: Job) => {
    await refresh();
    setSeed(null);
    if (job.parent_job_id) {
      setProposal(job.job_id);
      navigate(`/review/${job.parent_job_id}`);
    } else navigate("/");
  };
  const id = route.startsWith("/review/") ? route.split("/")[2] : null;
  const selected = jobs.find((job) => job.job_id === id);
  if (auth === null)
    return (
      <main className="connect">
        <Logo />
        <h1>Opening your local library…</h1>
        {error && <p role="alert">{error}</p>}
      </main>
    );
  if (!auth)
    return (
      <main className="connect">
        <div className="brand">
          <Logo /> Subline
        </div>
        <p className="eyebrow">LOCAL SUBTITLE STUDIO</p>
        <h1>
          A little closer
          <br />
          to every conversation.
        </h1>
        <p>
          Generate, listen, and refine English subtitles.
          <br />
          Your videos stay on this computer.
        </p>
        <form onSubmit={connect} className="connect-card">
          <h2>Connect to your local library</h2>
          <label>
            Local session key
            <input
              type="password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              autoComplete="off"
              required
            />
          </label>
          <p className="muted">
            Use the key in the token file printed by your local server. No
            account is needed.
          </p>
          <button className="primary" disabled={!key.trim()}>
            Connect
          </button>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
        </form>
      </main>
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <a href="#/" className="brand">
          <Logo /> Subline
        </a>
        <p className="sidebar-note">Local subtitle studio</p>
        <nav>
          <a className={route === "/" ? "nav-active" : ""} href="#/">
            ▤ <span>Library</span>
            <small>{jobs.length}</small>
          </a>
          <a
            className={route === "/new" ? "nav-active" : ""}
            href="#/new"
            onClick={() => setSeed(null)}
          >
            ＋ <span>New subtitles</span>
          </a>
        </nav>
        <div className="sidebar-bottom">
          <span className={`dot ${worker ? "ready" : ""}`} />{" "}
          {worker ? "Local worker ready" : "Worker offline"}
          <p>
            Private by default.
            <br />
            English output. Your review.
          </p>
          <button
            className="text-button"
            onClick={async () => {
              await api("/session", { method: "DELETE" });
              setAuth(false);
            }}
          >
            Disconnect
          </button>
        </div>
      </aside>
      <main className="workspace">
        {error && (
          <div className="notice error" role="alert">
            {error}
            <button
              onClick={() => setError("")}
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        )}
        {route === "/new" ? (
          <NewJob
            seed={seed}
            languages={languages}
            models={models}
            refreshModels={async () =>
              setModels(await api<ModelInfo>("/models"))
            }
            onCreated={created}
          />
        ) : selected ? (
          selected.state === "completed" || selected.state === "empty" ? (
            <Review
              key={selected.job_id}
              job={selected}
              jobs={jobs}
              proposalSeed={proposal}
              reprocess={reprocess}
            />
          ) : (
            <>
              <header className="page-header">
                <div>
                  <p className="eyebrow">JOB DETAILS</p>
                  <h1>{fileName(sourcePath(selected))}</h1>
                </div>
                <a href="#/" className="button">
                  Back to library
                </a>
              </header>
              <JobRow job={selected} refresh={refresh} />
            </>
          )
        ) : id ? (
          <p role="status">
            Loading job… <a href="#/">Back to library</a>
          </p>
        ) : (
          <Library jobs={jobs} refresh={refresh} />
        )}
      </main>
    </div>
  );
}

function Library({
  jobs,
  refresh,
}: {
  jobs: Job[];
  refresh: () => Promise<void>;
}) {
  const [filter, setFilter] = useState("all");
  const list = jobs.filter(
    (job) =>
      filter === "all" ||
      (filter === "ready"
        ? ["completed", "empty"].includes(job.state)
        : !["completed", "empty"].includes(job.state)),
  );
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">YOUR WORKSPACE</p>
          <h1>Subtitle library</h1>
          <p className="muted">From a local video to words worth reviewing.</p>
        </div>
        <a className="button primary" href="#/new">
          ＋ New subtitles
        </a>
      </header>
      <div className="summary-grid">
        <div>
          <span>{jobs.length}</span> videos in your library
        </div>
        <div>
          <span>{jobs.filter((job) => job.state === "completed").length}</span>{" "}
          ready to review
        </div>
        <div>
          <span>
            {
              jobs.filter((job) =>
                ["preparing", "processing", "exporting", "queued"].includes(
                  job.state,
                ),
              ).length
            }
          </span>{" "}
          in progress
        </div>
      </div>
      <div className="section-heading">
        <h2>Recent videos</h2>
        <label className="inline">
          Show
          <select
            aria-label="Filter jobs"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All jobs</option>
            <option value="ready">Ready to review</option>
            <option value="active">In progress / needs attention</option>
          </select>
        </label>
      </div>
      <div className="job-list">
        {list.map((job) => (
          <JobRow key={job.job_id} job={job} refresh={refresh} />
        ))}
        {!list.length && (
          <div className="empty">
            <Logo />
            <h2>Your next conversation starts here.</h2>
            <p>Add a local video to create English subtitles.</p>
            <a href="#/new" className="button primary">
              New subtitles
            </a>
          </div>
        )}
      </div>
      <p className="footnote">
        Generated subtitles are a starting point. Listen for missing dialogue,
        meaning, and timing.
      </p>
    </>
  );
}

function JobRow({ job, refresh }: { job: Job; refresh: () => Promise<void> }) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const completed =
    job.chunks?.filter((chunk) => chunk.state === "completed").length || 0;
  const active = ["preparing", "processing", "exporting", "queued"].includes(
    job.state,
  );
  const act = async (action: string) => {
    setBusy(true);
    try {
      await post(`/jobs/${job.job_id}/${action}`);
      await refresh();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="job-row">
      <div className="film-icon" aria-hidden="true">
        ▸
      </div>
      <div className="job-info">
        <h3>{fileName(sourcePath(job))}</h3>
        <p>
          {job.resolved_source_language || job.settings.source_language} →
          English <span>·</span> {job.settings.speech_model} <span>·</span>{" "}
          {job.cue_count !== undefined
            ? `${job.cue_count} cues`
            : "Awaiting output"}
          {job.parent_job_id && <span> · Replacement proposal</span>}
        </p>
        {active && (
          <>
            <progress
              aria-label="Completed chunks"
              max={job.chunks?.length || undefined}
              value={job.chunks?.length ? completed : undefined}
            />
            <p className="muted">
              {label(job.stage || job.state)}
              {job.chunks?.length
                ? ` · ${completed}/${job.chunks.length} chunks`
                : ""}
              {job.elapsed_seconds
                ? ` · ${Math.round(job.elapsed_seconds)}s elapsed`
                : ""}
            </p>
          </>
        )}
        {errorText(job) && (
          <details>
            <summary className="error">Processing needs attention</summary>
            <p className="error">{errorText(job)}</p>
            {typeof job.error === "object" && <p>{job.error.retry_hint}</p>}
          </details>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="job-actions">
        <span className={`badge ${job.state}`}>{label(job.state)}</span>
        {["completed", "empty"].includes(job.state) ? (
          <a className="button" href={`#/review/${job.job_id}`}>
            Review subtitles →
          </a>
        ) : active ? (
          <button disabled={busy} onClick={() => void act("cancel")}>
            Cancel
          </button>
        ) : (
          <button disabled={busy} onClick={() => void act("resume")}>
            Resume / retry
          </button>
        )}
      </div>
    </article>
  );
}

function NewJob({
  seed,
  languages,
  models,
  refreshModels,
  onCreated,
}: {
  seed: Seed | null;
  languages: Language[];
  models: ModelInfo;
  refreshModels: () => Promise<void>;
  onCreated: (job: Job) => Promise<void>;
}) {
  const [path, setPath] = useState(seed?.path || ""),
    [info, setInfo] = useState<{
      streams: {
        index: number;
        codec_type: string;
        codec_name: string;
        channels?: number;
        tags?: { language?: string; title?: string };
      }[];
    } | null>(null);
  const [track, setTrack] = useState(seed ? String(seed.audio_stream) : ""),
    [language, setLanguage] = useState(
      seed?.settings.source_language || "auto",
    ),
    [model, setModel] = useState(seed?.settings.speech_model || "small");
  const [device, setDevice] = useState(seed?.settings.device || "cpu"),
    [start, setStart] = useState(clock(seed?.start_ms || 0)),
    [duration, setDuration] = useState(seed ? clock(seed.duration_ms) : "");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [vad, setVad] = useState(seed?.settings.vad ?? true);
  const inspect = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await post<typeof info>("/media/inspect", { path });
      setInfo(result);
      const audio =
        result?.streams.filter((stream) => stream.codec_type === "audio") || [];
      setTrack(
        audio.length === 1
          ? String(audio[0].index)
          : seed
            ? String(seed.audio_stream)
            : "",
      );
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const startMs = parseClock(start),
        durationMs = duration ? parseClock(duration) : null;
      if (
        !Number.isFinite(startMs) ||
        (durationMs !== null &&
          (!Number.isFinite(durationMs) || durationMs <= 0))
      )
        throw new Error(
          "Enter a valid sample range, using seconds or HH:MM:SS.mmm.",
        );
      const job = await post<Job>("/jobs", {
        path,
        audio_stream: Number(track),
        start_ms: startMs,
        duration_ms: durationMs,
        parent_job_id: seed?.parent_job_id || null,
        settings: {
          ...seed?.settings,
          source_language: language,
          speech_model: model,
          device,
          vad,
          compute_type: device === "cpu" ? "int8" : null,
        },
      });
      await onCreated(job);
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const prepared = models.models.find((item) => item.id === model)?.prepared;
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">START A CONVERSATION</p>
          <h1>
            {seed?.parent_job_id
              ? "Create a replacement proposal"
              : "New subtitles"}
          </h1>
          <p className="muted">
            Choose a local video. We’ll create editable English subtitles.
          </p>
        </div>
      </header>
      <form className="new-form" onSubmit={submit}>
        {seed?.parent_job_id && (
          <div className="notice">
            This creates a separate proposal. Your saved corrections stay in the
            original job until you explicitly apply replacement text.
          </div>
        )}
        <section className="panel">
          <div className="step-heading">
            <span>01</span>
            <h2>Your video</h2>
          </div>
          <label>
            Local file path
            <div className="path-row">
              <input
                value={path}
                onChange={(e) => {
                  setPath(e.target.value);
                  setInfo(null);
                }}
                placeholder="C:\Movies\video.mp4"
                required
              />
              <button
                type="button"
                onClick={() => void inspect()}
                disabled={!path || busy}
              >
                {busy ? "Working…" : "Inspect video"}
              </button>
            </div>
          </label>
          <p className="muted">
            Use a path inside a folder approved by your local server. The file
            stays in place.
          </p>
          {info && (
            <label>
              Audio track
              <select
                value={track}
                required
                onChange={(e) => setTrack(e.target.value)}
              >
                <option value="">Choose an audio track</option>
                {info.streams
                  .filter((stream) => stream.codec_type === "audio")
                  .map((stream) => (
                    <option key={stream.index} value={stream.index}>
                      Track {stream.index} ·{" "}
                      {stream.tags?.language || "Untagged"} ·{" "}
                      {stream.codec_name} · {stream.channels} channels{" "}
                      {stream.tags?.title || ""}
                    </option>
                  ))}
              </select>
            </label>
          )}
        </section>
        <section className="panel">
          <div className="step-heading">
            <span>02</span>
            <h2>Language & quality</h2>
          </div>
          <div className="form-grid">
            <label>
              Source language
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              >
                <option value="auto">Auto detect</option>
                {languages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {models.models.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.id === "small" ? "Small · CPU test preset" : item.id}{" "}
                    {item.prepared ? "· Prepared" : "· Not downloaded"}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted">
            English output only. On this PC, Small processed a 36-second clip in
            9–14 seconds. Larger videos and harder audio vary; meaning still
            needs review.
          </p>
          {prepared === false && (
            <div className="notice">
              Prepare this model before starting:{" "}
              <code>
                local-subs models download {model} --model-cache "
                {models.model_cache}"
              </code>
              <button
                type="button"
                onClick={() =>
                  void refreshModels().catch((err) => setError(message(err)))
                }
              >
                Refresh prepared models
              </button>
            </div>
          )}
          <details>
            <summary>Advanced settings</summary>
            <div className="form-grid">
              <label>
                Device
                <select
                  value={device}
                  onChange={(e) => setDevice(e.target.value)}
                >
                  <option value="cpu">CPU</option>
                  <option value="auto">Auto</option>
                  <option value="cuda">CUDA GPU</option>
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={vad}
                  onChange={(e) => setVad(e.target.checked)}
                />
                Filter non-speech audio
              </label>
            </div>
          </details>
        </section>
        <section className="panel">
          <div className="step-heading">
            <span>03</span>
            <h2>Optional sample</h2>
          </div>
          <div className="form-grid">
            <label>
              Start time
              <input value={start} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label>
              Duration
              <input
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                placeholder="Leave blank for the remaining video"
              />
            </label>
          </div>
          <p className="muted">
            Use seconds or HH:MM:SS.mmm. Sample subtitles keep their original
            movie offset.
          </p>
        </section>
        {error && (
          <p role="alert" className="notice error">
            {error}
          </p>
        )}
        <div className="form-footer">
          <a href="#/">Back to library</a>
          <button
            className="primary"
            disabled={busy || !info || !track || !prepared}
          >
            {busy ? "Creating…" : "Create English subtitles →"}
          </button>
        </div>
      </form>
    </>
  );
}

function Review({
  job,
  jobs,
  proposalSeed,
  reprocess,
}: {
  job: Job;
  jobs: Job[];
  proposalSeed: string | null;
  reprocess: (job: Job, cue?: Cue) => void;
}) {
  const editor = useEditor(job.job_id),
    video = useRef<HTMLVideoElement>(null),
    stopAt = useRef<number | null>(null);
  const cueList = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState(0),
    [position, setPosition] = useState(0),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [qc, setQC] = useState<QC | null>(null);
  const [error, setError] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null),
    [unsupported, setUnsupported] = useState(false),
    [preparing, setPreparing] = useState(false),
    [badTimes, setBadTimes] = useState(false);
  const [trackPreview, setTrackPreview] = useState(false);
  useEffect(() => {
    void api<{ requires_selected_track_preview: boolean }>(
      `/jobs/${job.job_id}/playback`,
    )
      .then((info) => setTrackPreview(info.requires_selected_track_preview))
      .catch((err) => setError(message(err)));
  }, [job.job_id]);
  const [exportRevision, setExportRevision] = useState("latest"),
    [revisions, setRevisions] = useState<{ revision: number }[]>([]),
    [exported, setExported] = useState<{
      export_id: string;
      cue_revision: number;
    } | null>(null),
    [exporting, setExporting] = useState(false);
  const [proposalId, setProposalId] = useState(proposalSeed || ""),
    [proposalCues, setProposalCues] = useState<Cue[]>([]);
  const cue =
    editor.cues[Math.min(selected, Math.max(0, editor.cues.length - 1))];
  const needsReview = new Set(
    qc?.issues.filter((issue) => issue.cue_id).map((issue) => issue.cue_id),
  );
  useEffect(() => {
    const list = cueList.current;
    const row = list?.querySelector<HTMLElement>('[aria-current="true"]');
    if (
      list &&
      row &&
      (row.offsetTop < list.scrollTop ||
        row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight)
    )
      list.scrollTop = Math.max(0, row.offsetTop - 20);
  }, [selected, search, filter]);
  useEffect(() => {
    if (editor.status === "saved") {
      void api<QC>(`/jobs/${job.job_id}/qc`)
        .then(setQC)
        .catch((err) => setError(message(err)));
      void api<{ revision: number }[]>(`/jobs/${job.job_id}/cue-revisions`)
        .then(setRevisions)
        .catch((err) => setError(message(err)));
    }
  }, [job.job_id, editor.revision, editor.status]);
  useEffect(() => {
    if (!preview || !["queued", "processing"].includes(preview.state)) return;
    const timer = setInterval(
      () =>
        void api<Preview>(
          `/jobs/${job.job_id}/preview?key=${preview.cache_key}`,
        )
          .then(setPreview)
          .catch((err) => setError(message(err))),
      800,
    );
    return () => clearInterval(timer);
  }, [preview, job.job_id]);
  const proposalJob = jobs.find((item) => item.job_id === proposalId);
  useEffect(() => {
    if (!proposalId || proposalJob?.state !== "completed") {
      setProposalCues([]);
      return;
    }
    void api<{ cues: Cue[] }>(`/jobs/${proposalId}/cues?revision=0`)
      .then((data) => setProposalCues(data.cues))
      .catch((err) => setError(message(err)));
  }, [proposalId, proposalJob?.state]);
  const seek = useCallback(
    (index: number, play = false) => {
      const next = editor.cues[index];
      if (!next || !video.current) return;
      setSelected(index);
      video.current.currentTime = next.start_ms / 1000;
      setPosition(next.start_ms);
      stopAt.current = play ? next.end_ms / 1000 : null;
      if (play)
        void video.current.play().catch((err) => setError(message(err)));
    },
    [editor.cues],
  );
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        (event.target as HTMLElement).closest(
          "input,textarea,select,[contenteditable]",
        )
      )
        return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        seek(Math.min(selected + 1, editor.cues.length - 1));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        seek(Math.max(selected - 1, 0));
      }
      if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        seek(selected, true);
      }
      if (
        event.code === "Space" &&
        !(event.target as HTMLElement).closest("button:not(.cue-row),a")
      ) {
        event.preventDefault();
        if (video.current?.paused)
          void video.current.play().catch((err) => setError(message(err)));
        else video.current?.pause();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, seek, editor.cues.length]);
  const createPreview = async () => {
    setPreparing(true);
    setError("");
    try {
      setPreview(
        await post<Preview>(`/jobs/${job.job_id}/preview`, {
          force_transcode: preview?.state === "completed" && unsupported,
        }),
      );
    } catch (err) {
      setError(message(err));
    } finally {
      setPreparing(false);
    }
  };
  const replace = (next: Cue) =>
    editor.change(
      editor.cues.map((item) => (item.id === next.id ? next : item)),
    );
  const split = (cursor: number, at: number) => {
    try {
      editor.change(splitCue(editor.cues, selected, cursor, at));
    } catch (err) {
      setError(message(err));
    }
  };
  const merge = () => {
    try {
      editor.change(mergeCue(editor.cues, selected));
    } catch (err) {
      setError(message(err));
    }
  };
  const exportNow = async () => {
    if (badTimes || !(await editor.save())) return;
    setExporting(true);
    try {
      setExported(
        await post(`/jobs/${job.job_id}/exports`, {
          revision:
            exportRevision === "latest"
              ? editor.revision
              : Number(exportRevision),
        }),
      );
    } catch (err) {
      setError(message(err));
    } finally {
      setExporting(false);
    }
  };
  const playCue = editor.cues.find(
    (item) => item.start_ms <= position && position < item.end_ms,
  );
  const proposedText = cue
    ? proposalCues
        .filter(
          (item) => item.start_ms < cue.end_ms && item.end_ms > cue.start_ms,
        )
        .map((item) => item.text)
        .join(" ")
    : "";
  const src =
    preview?.state === "completed"
      ? `/jobs/${job.job_id}/preview/media?key=${preview.cache_key}`
      : `/jobs/${job.job_id}/media`;
  const waitingPreview =
    preparing || (preview && ["queued", "processing"].includes(preview.state));
  return (
    <>
      <header className="page-header review-header">
        <div>
          <a className="breadcrumb" href="#/">
            ← Library
          </a>
          <h1>{fileName(sourcePath(job))}</h1>
          <p className="muted">
            {job.resolved_source_language || job.settings.source_language} →
            English · {editor.cues.length} cues ·{" "}
            {editor.revision
              ? `Edited revision ${editor.revision}`
              : "Generated · not reviewed"}
          </p>
        </div>
        <div className={`save-state ${editor.status}`} role="status">
          {badTimes
            ? "Time changes need correction"
            : editor.status === "saved"
              ? `Saved · revision ${editor.revision}`
              : label(editor.status)}
        </div>
      </header>
      {(error || editor.error) && (
        <div className="notice error" role="alert">
          {error || editor.error}
          <button
            onClick={() => setError("")}
            aria-label="Dismiss review error"
          >
            ×
          </button>
        </div>
      )}
      {editor.status === "conflict" && (
        <div className="notice conflict">
          <strong>A newer revision was saved elsewhere.</strong>
          <p>
            Your draft is still here. Keep a copy before loading the saved
            revision.
          </p>
          <button
            onClick={() =>
              downloadDraft(editor.cues, `draft-${job.job_id}.json`)
            }
          >
            Download my draft
          </button>
          <button onClick={() => void editor.reload()}>
            Load saved version
          </button>
        </div>
      )}
      <div className="review-grid">
        <div className="review-left">
          <section className="player">
            <video
              ref={video}
              src={
                trackPreview && preview?.state !== "completed" ? undefined : src
              }
              controls
              preload="metadata"
              aria-label="Review video"
              onError={() => setUnsupported(true)}
              onLoadedMetadata={() => setUnsupported(false)}
              onTimeUpdate={(event) => {
                setPosition(Math.round(event.currentTarget.currentTime * 1000));
                if (
                  stopAt.current !== null &&
                  event.currentTarget.currentTime >= stopAt.current
                ) {
                  event.currentTarget.pause();
                  stopAt.current = null;
                }
              }}
            />
            {playCue && (
              <div className="subtitle-overlay" aria-hidden="true">
                {playCue.text}
              </div>
            )}
          </section>
          <div className="player-toolbar">
            <span className="timecode">{clock(position)}</span>
            <button
              onClick={() => seek(Math.max(0, selected - 1))}
              disabled={!selected}
            >
              ← Previous
            </button>
            <button
              onClick={() => seek(selected, true)}
              disabled={
                !cue || (trackPreview && preview?.state !== "completed")
              }
            >
              Replay cue
            </button>
            <button
              onClick={() =>
                seek(Math.min(editor.cues.length - 1, selected + 1))
              }
              disabled={selected >= editor.cues.length - 1}
            >
              Next →
            </button>
          </div>
          <p className="keyboard-help">
            Space · play/pause　 ↑ / ↓ · cues　 R · replay
          </p>
          {(unsupported || trackPreview || preview || preparing) && (
            <div className="notice">
              <strong>
                {waitingPreview
                  ? "Preparing a compatible preview…"
                  : preview?.state === "completed"
                    ? "Playing a compatible preview"
                    : "This video may need a compatible preview"}
              </strong>
              <p>
                {preview?.error ||
                  "The preview uses the selected audio track and preserves the movie timeline. Your source stays unchanged."}
              </p>
              <button
                disabled={Boolean(waitingPreview)}
                onClick={() => void createPreview()}
              >
                {waitingPreview ? "Preparing…" : "Create compatible preview"}
              </button>
            </div>
          )}
          <details className="preview-options">
            <summary>Playback / selected-track options</summary>
            <p>
              Use a preview if your browser cannot play the container or if you
              need the job’s selected audio track.
            </p>
            <button
              disabled={Boolean(waitingPreview)}
              onClick={() => void createPreview()}
            >
              Prepare selected-track preview
            </button>
          </details>
          {cue && (
            <div
              className="selected-flags"
              aria-label="Selected cue review issues"
            >
              {qc?.issues
                .filter((issue) => issue.cue_id === cue.id)
                .map((issue, index) => (
                  <p key={`${issue.code}-${index}`}>
                    <strong>{label(issue.code)}:</strong> {issue.message}
                  </p>
                ))}
            </div>
          )}
          {cue && (
            <CueFields
              cue={cue}
              index={selected}
              onChange={replace}
              onSplit={split}
              onMerge={merge}
              hasNext={selected + 1 < editor.cues.length}
              onInvalid={setBadTimes}
            />
          )}
          <div className="editor-tools">
            {editor.status === "error" && editor.cues.length > 0 && (
              <button
                onClick={() =>
                  downloadDraft(editor.cues, `draft-${job.job_id}.json`)
                }
              >
                Download unsaved draft
              </button>
            )}
            <button disabled={!editor.undoCount} onClick={editor.undo}>
              Undo last edit
            </button>
            <button
              disabled={
                editor.status === "saving" ||
                badTimes ||
                editor.status === "conflict"
              }
              onClick={() => void editor.save()}
            >
              Save now
            </button>
            <button
              disabled={!cue || badTimes || editor.status !== "saved"}
              onClick={() => reprocess(job, cue)}
            >
              Reprocess selection…
            </button>
          </div>
          <section className="panel export-panel">
            <div>
              <p className="eyebrow">TAKE YOUR WORDS WITH YOU</p>
              <h2>Export subtitles</h2>
              <p className="muted">
                Choose a saved revision. Meaning and timing still need your
                review.
              </p>
            </div>
            <label>
              Revision
              <select
                value={exportRevision}
                onChange={(e) => {
                  setExportRevision(e.target.value);
                  setExported(null);
                }}
              >
                <option value="latest">
                  Latest saved · {editor.revision ? "Edited" : "Generated"} (
                  {editor.revision})
                </option>
                {revisions.map((item) => (
                  <option value={item.revision} key={item.revision}>
                    {item.revision === 0
                      ? "Generated original"
                      : `Edited revision ${item.revision}`}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary"
              disabled={editor.status !== "saved" || badTimes || exporting}
              onClick={() => void exportNow()}
            >
              {exporting ? "Preparing export…" : "Prepare SRT & VTT"}
            </button>
            {exported && (
              <div className="download-links">
                <span>Revision {exported.cue_revision} ready</span>
                <a
                  className="button"
                  href={`/jobs/${job.job_id}/exports/${exported.export_id}/subtitles.en.srt`}
                  download
                >
                  Download SRT
                </a>
                <a
                  className="button"
                  href={`/jobs/${job.job_id}/exports/${exported.export_id}/subtitles.en.vtt`}
                  download
                >
                  Download VTT
                </a>
              </div>
            )}
          </section>
        </div>
        <section className="panel cues-panel">
          <div className="cue-list-heading">
            <div>
              <p className="eyebrow">THE CONVERSATION</p>
              <h2>English subtitles</h2>
            </div>
            <span className="badge">{qc?.warning_count || 0} review flags</span>
          </div>
          <div className="cue-filters">
            <input
              aria-label="Search subtitles"
              placeholder="Search subtitle text…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select
              aria-label="Filter subtitles"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">All cues</option>
              <option value="flags">Needs review</option>
              <option value="manual">Edited cues</option>
            </select>
          </div>
          <div className="cue-scroll" ref={cueList}>
            {editor.cues
              .map((item, index) => ({ item, index }))
              .filter(
                ({ item }) =>
                  item.text.toLowerCase().includes(search.toLowerCase()) &&
                  (filter === "all" ||
                    (filter === "flags"
                      ? needsReview.has(item.id)
                      : item.origin === "manual")),
              )
              .map(({ item, index }) => (
                <button
                  className={`cue-row ${selected === index ? "selected" : ""} ${playCue?.id === item.id ? "playing" : ""}`}
                  key={item.id}
                  onClick={() => seek(index)}
                  aria-label={`Cue ${index + 1}: ${item.text}`}
                  aria-current={selected === index ? "true" : undefined}
                >
                  <span className="cue-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="cue-content">
                    <span className="timecode">
                      {clock(item.start_ms)} → {clock(item.end_ms)}
                    </span>
                    <span className="cue-text">{item.text}</span>
                    <span className="cue-tags">
                      {needsReview.has(item.id) && <em>Review</em>}
                      {item.origin === "manual" && (
                        <em className="manual">Edited</em>
                      )}
                    </span>
                  </span>
                </button>
              ))}
            {editor.status === "loading" && <p>Loading subtitles…</p>}
            {editor.status !== "loading" && !editor.cues.length && (
              <p className="empty">
                No subtitles in this result. Listen to the source before
                treating it as silence.
              </p>
            )}
          </div>
          <div className="cue-footnote">
            Flags are review hints, not accuracy scores.
          </div>
        </section>
      </div>
      {cue && (
        <section className="panel proposal-panel">
          <h2>Compare a replacement</h2>
          <p className="muted">
            Generated replacements never overwrite your corrections. Apply text
            only after listening; existing cue timing stays unchanged.
          </p>
          <label>
            Replacement job
            <select
              value={proposalId}
              onChange={(e) => setProposalId(e.target.value)}
            >
              <option value="">Choose a proposal</option>
              {jobs
                .filter((item) => item.parent_job_id === job.job_id)
                .map((item) => (
                  <option key={item.job_id} value={item.job_id}>
                    Proposal {item.job_id.slice(0, 8)} · {item.state}
                  </option>
                ))}
            </select>
          </label>
          {proposalId && (
            <div className="proposal-comparison">
              <div>
                <h3>Your current text</h3>
                <p>{cue.text}</p>
              </div>
              <div>
                <h3>Proposed text</h3>
                <p>
                  {proposalJob?.state !== "completed"
                    ? `Proposal ${proposalJob?.state || "is loading"}…`
                    : proposedText || "No proposed cue overlaps this interval."}
                </p>
                <button
                  disabled={!proposedText || editor.status === "conflict"}
                  onClick={() => replace({ ...cue, text: proposedText })}
                >
                  Apply proposed text
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}

function CueFields({
  cue,
  index,
  onChange,
  onSplit,
  onMerge,
  hasNext,
  onInvalid,
}: {
  cue: Cue;
  index: number;
  onChange: (cue: Cue) => void;
  onSplit: (cursor: number, at: number) => void;
  onMerge: () => void;
  hasNext: boolean;
  onInvalid: (value: boolean) => void;
}) {
  const [start, setStart] = useState(clock(cue.start_ms)),
    [end, setEnd] = useState(clock(cue.end_ms)),
    [error, setError] = useState(""),
    [splitting, setSplitting] = useState(false),
    [at, setAt] = useState(clock(Math.round((cue.start_ms + cue.end_ms) / 2))),
    [cursor, setCursor] = useState(wordBoundary(cue.text));
  useEffect(() => {
    setStart(clock(cue.start_ms));
    setEnd(clock(cue.end_ms));
    setError("");
    onInvalid(false);
    setAt(clock(Math.round((cue.start_ms + cue.end_ms) / 2)));
    setCursor(wordBoundary(cue.text));
  }, [cue.id, cue.start_ms, cue.end_ms, onInvalid]);
  const updateTime = (a: string, b: string) => {
    setStart(a);
    setEnd(b);
    const first = parseClock(a),
      last = parseClock(b);
    if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) {
      setError(
        "Time changes not saved: enter valid times with end after start.",
      );
      onInvalid(true);
      return;
    }
    setError("");
    onInvalid(false);
    onChange({ ...cue, start_ms: first, end_ms: last });
  };
  return (
    <section className="panel cue-editor">
      <div className="section-heading">
        <h2>Edit cue {index + 1}</h2>
        <span className="muted">Autosaves after typing</span>
      </div>
      <label>
        English text
        <textarea
          value={cue.text}
          rows={3}
          onChange={(event) => {
            onChange({ ...cue, text: event.target.value });
            setCursor(wordBoundary(event.target.value));
          }}
        />
      </label>
      <div className="form-grid">
        <label>
          Start time
          <input
            value={start}
            onChange={(event) => updateTime(event.target.value, end)}
          />
        </label>
        <label>
          End time
          <input
            value={end}
            onChange={(event) => updateTime(start, event.target.value)}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="editor-tools">
        <button onClick={() => setSplitting(!splitting)}>Split…</button>
        <button disabled={!hasNext} onClick={onMerge}>
          Merge with next
        </button>
      </div>
      {splitting && (
        <div className="split-fields">
          <p>
            Choose a word boundary and a split time after listening. The
            midpoint is only a suggestion.
          </p>
          <div className="form-grid">
            <label>
              Split time
              <input value={at} onChange={(e) => setAt(e.target.value)} />
            </label>
            <label>
              After character
              <input
                type="number"
                min="1"
                max={cue.text.length - 1}
                value={cursor}
                onChange={(e) => setCursor(Number(e.target.value))}
              />
            </label>
          </div>
          <p className="split-preview">
            {cue.text.slice(0, Math.max(0, cursor))} <strong>│</strong>{" "}
            {cue.text.slice(Math.max(0, cursor))}
          </p>
          <button onClick={() => onSplit(cursor, parseClock(at))}>
            Split cue at chosen time
          </button>
        </div>
      )}
    </section>
  );
}
