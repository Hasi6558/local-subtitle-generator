import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { sameEdits, validateDraft } from "./editing";
import type { Cue } from "./types";
type Saved = { revision: number; cues: Cue[] };
// Storage can be disabled or full. It must never prevent the server autosave.
const recoveryStorage = {
  getItem(key: string) {
    try {
      return sessionStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string) {
    try {
      sessionStorage.setItem(key, value);
    } catch {
      /* Current draft remains in memory and can be downloaded. */
    }
  },
  removeItem(key: string) {
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* No stored copy to clear. */
    }
  },
};
export function useEditor(jobId: string) {
  const [cues, setCues] = useState<Cue[]>([]),
    [revision, setRevision] = useState(0);
  const [status, setStatus] = useState("loading"),
    [error, setError] = useState("");
  const [undoCount, setUndoCount] = useState(0);
  const draft = useRef<Cue[]>([]),
    base = useRef(0),
    version = useRef(0),
    savedVersion = useRef(0),
    active = useRef(0);
  const saving = useRef(false),
    conflict = useRef(false),
    history = useRef<Cue[][]>([]);
  const key = `subline-draft-${jobId}`;
  const load = useCallback(
    async (discard = false) => {
      const generation = active.current;
      try {
        const data = await api<Saved>(`/jobs/${jobId}/cues`);
        if (active.current !== generation) return;
        let backup: Saved | null = null;
        try {
          backup = discard
            ? null
            : JSON.parse(recoveryStorage.getItem(key) || "null");
        } catch {
          recoveryStorage.removeItem(key);
        }
        base.current = data.revision;
        savedVersion.current = version.current;
        conflict.current = false;
        setError("");
        if (
          backup &&
          Array.isArray(backup.cues) &&
          Number.isInteger(backup.revision) &&
          backup.cues.every(
            (cue) =>
              cue &&
              typeof cue.id === "string" &&
              typeof cue.text === "string" &&
              Number.isInteger(cue.start_ms) &&
              Number.isInteger(cue.end_ms),
          ) &&
          !sameEdits(backup.cues, data.cues)
        ) {
          draft.current = backup.cues;
          version.current++;
          base.current = backup.revision;
          conflict.current = backup.revision !== data.revision;
          setStatus(conflict.current ? "conflict" : "unsaved");
          setError(
            conflict.current
              ? "The saved revision changed. Your recovered draft is kept here."
              : "Recovered your unsaved draft.",
          );
        } else {
          draft.current = data.cues;
          setStatus("saved");
          recoveryStorage.removeItem(key);
        }
        setCues(draft.current);
        setRevision(base.current);
        history.current = [];
        setUndoCount(0);
      } catch (err) {
        if (active.current === generation) {
          setStatus("error");
          setError((err as Error).message);
        }
      }
    },
    [jobId, key],
  );
  useEffect(() => {
    active.current++;
    void load();
    return () => {
      active.current++;
    };
  }, [load]);
  const change = useCallback(
    (next: Cue[], remember = true) => {
      if (remember) {
        history.current = [
          ...history.current.slice(-49),
          structuredClone(draft.current),
        ];
        setUndoCount(history.current.length);
      }
      draft.current = next;
      version.current++;
      setCues(next);
      recoveryStorage.setItem(
        key,
        JSON.stringify({ revision: base.current, cues: next }),
      );
      if (!conflict.current) {
        setStatus("unsaved");
        setError("");
      }
    },
    [key],
  );
  const save = useCallback(async (): Promise<boolean> => {
    if (saving.current || conflict.current) return false;
    if (version.current === savedVersion.current) return true;
    const validation = validateDraft(draft.current);
    if (validation) {
      setStatus("error");
      setError(validation);
      return false;
    }
    saving.current = true;
    const captured = version.current,
      generation = active.current;
    setStatus("saving");
    try {
      const response = await api<Saved>(`/jobs/${jobId}/cues`, {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: base.current,
          cues: draft.current,
        }),
      });
      if (active.current !== generation) return false;
      base.current = response.revision;
      setRevision(response.revision);
      savedVersion.current = captured;
      if (captured === version.current) {
        draft.current = response.cues;
        setCues(response.cues);
        recoveryStorage.removeItem(key);
        setStatus("saved");
        setError("");
      } else {
        recoveryStorage.setItem(
          key,
          JSON.stringify({ revision: base.current, cues: draft.current }),
        );
        setStatus("unsaved");
        setTimeout(() => {
          if (active.current === generation) void save();
        }, 0);
      }
      return captured === version.current;
    } catch (err) {
      if (active.current === generation) {
        conflict.current = err instanceof ApiError && err.status === 409;
        setStatus(conflict.current ? "conflict" : "error");
        setError((err as Error).message);
      }
      return false;
    } finally {
      saving.current = false;
    }
  }, [jobId, key]);
  useEffect(() => {
    if (status !== "unsaved") return;
    const timer = setTimeout(() => void save(), 700);
    return () => clearTimeout(timer);
  }, [cues, status, save]);
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (version.current !== savedVersion.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, []);
  const undo = () => {
    const previous = history.current.pop();
    if (previous) {
      setUndoCount(history.current.length);
      change(previous, false);
    }
  };
  return {
    cues,
    revision,
    status,
    error,
    change,
    save,
    undo,
    undoCount,
    reload: () => load(true),
  };
}
