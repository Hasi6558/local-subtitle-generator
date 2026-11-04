import {
  expect,
  test,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
test.skip(
  !!process.env.LOCAL_SUBS_UI_LIVE,
  "Synthetic fixtures are tested separately from real inference",
);
const headers = { Authorization: "Bearer ui-test-key" };
async function fixture(request: APIRequestContext, unsupported = false) {
  const response = await request.post("/__test/job", {
    headers,
    data: { unsupported },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}
async function connect(page: Page, id: string) {
  await page.goto(`/#/review/${id}`);
  await page.getByLabel("Local session key").fill("ui-test-key");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByLabel("English text")).toBeVisible();
}
async function saved(page: Page) {
  await expect(page.locator(".save-state")).toContainText("Saved");
}

test("pipeline toggle creates paired results and preserves separate edits", async ({
  page,
  request,
}) => {
  const job = await fixture(request);
  await connect(page, job.job_id);
  await page.getByLabel("English text").fill("My direct-mode correction.");
  await saved(page);
  await page
    .getByRole("button", { name: "Contextual local · Create test…" })
    .click();
  await expect(
    page.getByRole("radio", { name: "Contextual local", exact: true }),
  ).toBeChecked();
  await page
    .getByRole("radio", { name: "Whisper direct", exact: true })
    .check();
  await expect(
    page.getByRole("combobox", { name: "Text model", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("radio", { name: "Contextual local", exact: true })
    .check();
  await page
    .getByRole("combobox", { name: "Text model", exact: true })
    .selectOption("qwen3-1.7b");
  await expect(
    page.getByRole("button", { name: "Create English subtitles →" }),
  ).toBeDisabled();
  await page
    .getByRole("combobox", { name: "Text model", exact: true })
    .selectOption("qwen3-4b");
  await page
    .getByLabel("Names & terminology glossary (JSON)")
    .fill('{"コーヒー":"coffee"}');
  await page
    .getByRole("button", { name: "Inspect video", exact: true })
    .click();
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/jobs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create English subtitles →" })
    .click();
  const contextual = await (await created).json();
  expect(contextual.settings.pipeline).toBe("contextual");
  expect(contextual.comparison_job_id).toBe(job.job_id);
  expect(contextual.settings.glossary).toEqual({ コーヒー: "coffee" });
  await request.post(`/__test/finish/${contextual.job_id}`, { headers });
  await page.goto(`/#/review/${contextual.job_id}`);
  await expect(page.getByLabel("English text")).toHaveValue(
    "Proposed replacement text.",
  );
  await expect(page.locator(".cue-editor .source-text")).toContainText(
    "コーヒーをください。",
  );
  await expect(page.locator(".pipeline-comparison")).toContainText(
    "My direct-mode correction.",
  );
  await page.getByLabel("English text").fill("My contextual correction.");
  await saved(page);
  await page
    .getByRole("button", { name: "Whisper direct", exact: true })
    .click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "My direct-mode correction.",
  );
  await page
    .getByRole("button", { name: "Contextual local", exact: true })
    .click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "My contextual correction.",
  );
  await page.screenshot({
    path: "test-results/phase6-comparison.png",
    fullPage: true,
  });
});

test("review, autosave, reload, explicit split/merge/undo, seek, keyboard and edited export", async ({
  page,
  request,
}) => {
  const job = await fixture(request);
  await connect(page, job.job_id);
  const text = page.getByLabel("English text");
  await text.fill("A corrected English subtitle.");
  await saved(page);
  await page.reload();
  await expect(text).toHaveValue("A corrected English subtitle.");
  await page.getByRole("button", { name: "Split…", exact: true }).click();
  await page.getByLabel("Split time", { exact: true }).fill("1.500");
  await page.getByLabel("After character").fill("1");
  await page.getByRole("button", { name: "Split cue at chosen time" }).click();
  await expect(page.locator(".cue-row")).toHaveCount(4);
  await saved(page);
  await page.getByRole("button", { name: "Merge with next" }).click();
  await expect(page.locator(".cue-row")).toHaveCount(3);
  await saved(page);
  await expect(text).toHaveValue("A corrected English subtitle.");
  await page.getByRole("button", { name: "Undo last edit" }).click();
  await expect(page.locator(".cue-row")).toHaveCount(4);
  await saved(page);
  await page.getByRole("button", { name: /^Cue 3:/ }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((element: HTMLVideoElement) => element.currentTime),
    )
    .toBeCloseTo(3, 1);
  await page.locator("h1").click();
  await page.keyboard.press("ArrowDown");
  await expect(
    page.getByRole("heading", { name: "Edit cue 4", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Replay cue", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((element: HTMLVideoElement) => element.paused),
    )
    .toBe(false);
  await page
    .locator("video")
    .evaluate((element: HTMLVideoElement) => element.pause());
  await expect(page.locator(".notice.error")).toHaveCount(0);
  await page.getByRole("button", { name: "Prepare SRT & VTT" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download SRT", exact: true }).click();
  const file = await download;
  const path = await file.path();
  expect(path).toBeTruthy();
  const fs = await import("node:fs/promises");
  const contents = await fs.readFile(path!, "utf8");
  expect(contents).toContain("corrected English subtitle.");
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({
    path: "../outputs/phase5-review-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../outputs/phase5-review-mobile.png",
    fullPage: true,
  });
});

test("edit conflict preserves a draft until explicit reload and supports draft download", async ({
  page,
  request,
}) => {
  const job = await fixture(request);
  await connect(page, job.job_id);
  const current = await (
    await request.get(`/jobs/${job.job_id}/cues`, { headers })
  ).json();
  current.cues[0].text = "Another editor saved this.";
  expect(
    (
      await request.put(`/jobs/${job.job_id}/cues`, {
        headers,
        data: { expected_revision: 0, cues: current.cues },
      })
    ).ok(),
  ).toBeTruthy();
  await page.getByLabel("English text").fill("My local correction.");
  await expect(
    page.getByText("A newer revision was saved elsewhere."),
  ).toBeVisible();
  await expect(page.getByLabel("English text")).toHaveValue(
    "My local correction.",
  );
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download my draft" }).click();
  expect((await download).suggestedFilename()).toContain("draft-");
  await page.getByRole("button", { name: "Load saved version" }).click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Another editor saved this.",
  );
});

test("unsupported playback offers a cached compatible preview with correct seeking", async ({
  page,
  request,
}) => {
  const job = await fixture(request, true);
  await connect(page, job.job_id);
  // Native decoder support varies. Triggering the native error event also tests the fallback affordance.
  await page.locator("video").dispatchEvent("error");
  await page
    .getByRole("button", { name: "Create compatible preview", exact: true })
    .click();
  await expect(
    page.getByText("Playing a compatible preview", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Cue 2:/ }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((element: HTMLVideoElement) => element.currentTime),
    )
    .toBeCloseTo(3, 1);
  expect(
    (
      await (
        await request.get(`/jobs/${job.job_id}/preview`, { headers })
      ).json()
    ).mode,
  ).toBe("video transcode");
});

test("new job, queue cancellation, and a replacement proposal require explicit text acceptance", async ({
  page,
  request,
}) => {
  const job = await fixture(request);
  await connect(page, job.job_id);
  await page.getByLabel("English text").fill("Keep my saved correction.");
  await saved(page);
  await page.getByRole("button", { name: "Reprocess selection…" }).click();
  await expect(
    page.getByRole("heading", { name: "Create a replacement proposal" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Inspect video", exact: true })
    .click();
  await expect(page.getByLabel("Audio track")).toBeVisible();
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/jobs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create English subtitles →" })
    .click();
  const proposal = await (await created).json();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Keep my saved correction.",
  );
  expect(
    (await request.post(`/__test/finish/${proposal.job_id}`, { headers })).ok(),
  ).toBeTruthy();
  await expect(
    page.getByRole("button", { name: "Apply proposed text" }),
  ).toBeEnabled();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Keep my saved correction.",
  );
  await page.getByRole("button", { name: "Apply proposed text" }).click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Proposed replacement text.",
  );
  await saved(page);
  await page
    .locator(".sidebar")
    .getByRole("link", { name: /New subtitles/ })
    .click();
  await page.getByLabel("Local file path").fill(job.source_path);
  await page
    .getByRole("button", { name: "Inspect video", exact: true })
    .click();
  await expect(page.getByLabel("Audio track")).toBeVisible();
  const queued = page.waitForResponse(
    (response) =>
      response.url().endsWith("/jobs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create English subtitles →" })
    .click();
  const queuedJob = await (await queued).json();
  // Find the queued row by its only cancel action; the other fixture jobs are completed.
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`/jobs/${queuedJob.job_id}`, { headers })
          ).json()
        ).state,
    )
    .toBe("cancelled");
});
