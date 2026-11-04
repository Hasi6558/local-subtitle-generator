import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useEditor } from "./useEditor";
const original = {
  id: "one",
  start_ms: 0,
  end_ms: 2000,
  text: "Original text.",
};
beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());
it("continues autosaving when browser draft storage is unavailable", async () => {
  const blocked = vi
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("Storage full");
    });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (_url, options) =>
        new Response(
          JSON.stringify(
            options.method === "PUT"
              ? { revision: 1, cues: JSON.parse(options.body).cues }
              : { revision: 0, cues: [original] },
          ),
        ),
    ),
  );
  try {
    const hook = renderHook(() => useEditor("storage"));
    await waitFor(() => expect(hook.result.current.status).toBe("saved"));
    act(() =>
      hook.result.current.change([
        { ...original, text: "Saved despite unavailable storage." },
      ]),
    );
    await act(async () => {
      await hook.result.current.save();
    });
    expect(hook.result.current.status).toBe("saved");
    expect(hook.result.current.revision).toBe(1);
  } finally {
    blocked.mockRestore();
  }
});
it("saves a newer edit that arrives while an earlier autosave is in flight", async () => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let puts = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      if (options.method !== "PUT")
        return new Response(JSON.stringify({ revision: 0, cues: [original] }));
      const input = JSON.parse(options.body);
      const revision = ++puts;
      if (revision === 1) await gate;
      return new Response(JSON.stringify({ revision, cues: input.cues }));
    }),
  );
  const hook = renderHook(() => useEditor("rapid"));
  await waitFor(() => expect(hook.result.current.status).toBe("saved"));
  act(() => hook.result.current.change([{ ...original, text: "First edit." }]));
  let pending!: Promise<boolean>;
  act(() => {
    pending = hook.result.current.save();
  });
  act(() => hook.result.current.change([{ ...original, text: "Newer edit." }]));
  await act(async () => {
    release();
    await pending;
  });
  await waitFor(() => expect(hook.result.current.revision).toBe(2));
  expect(hook.result.current.cues[0].text).toBe("Newer edit.");
  expect(hook.result.current.status).toBe("saved");
});
it("autosaves, supports undo, and preserves a conflicting draft", async () => {
  let revision = 0,
    text = original.text;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url, options) => {
      if (options.method === "PUT") {
        const input = JSON.parse(options.body);
        if (input.expected_revision !== revision)
          return new Response(JSON.stringify({ detail: "Edit conflict" }), {
            status: 409,
          });
        revision++;
        text = input.cues[0].text;
      }
      return new Response(
        JSON.stringify({ revision, cues: [{ ...original, text }] }),
        { status: 200 },
      );
    }),
  );
  const hook = renderHook(() => useEditor("job"));
  await waitFor(() => expect(hook.result.current.status).toBe("saved"));
  act(() =>
    hook.result.current.change([{ ...original, text: "My correction." }]),
  );
  await act(async () => {
    await hook.result.current.save();
  });
  expect(hook.result.current.revision).toBe(1);
  expect(text).toBe("My correction.");
  act(() => hook.result.current.undo());
  expect(hook.result.current.cues[0].text).toBe(original.text);
  revision = 2;
  await act(async () => {
    await hook.result.current.save();
  });
  expect(hook.result.current.status).toBe("conflict");
  expect(
    JSON.parse(sessionStorage.getItem("subline-draft-job")!).cues[0].text,
  ).toBe(original.text);
});
it("recovers an unsaved draft without overwriting a newer server revision", async () => {
  sessionStorage.setItem(
    "subline-draft-job",
    JSON.stringify({
      revision: 0,
      cues: [{ ...original, text: "Local draft." }],
    }),
  );
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          revision: 1,
          cues: [{ ...original, text: "Other editor." }],
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useEditor("job"));
  await waitFor(() => expect(hook.result.current.status).toBe("conflict"));
  expect(hook.result.current.cues[0].text).toBe("Local draft.");
  await act(async () => {
    await hook.result.current.reload();
  });
  expect(hook.result.current.cues[0].text).toBe("Other editor.");
  expect(fetcher).toHaveBeenCalledTimes(2);
});
