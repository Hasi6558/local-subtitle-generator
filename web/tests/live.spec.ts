import { expect, test } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
test.skip(
  !process.env.LOCAL_SUBS_UI_LIVE,
  "Enable LOCAL_SUBS_UI_LIVE for real cached-model browser acceptance",
);
test("real local video: create, infer, review, edit, reload, preview, seek and export", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  const info = JSON.parse(
    await readFile("../outputs/phase5-live-info.json", "utf8"),
  );
  await page.goto("/");
  await page.getByLabel("Local session key").fill("ui-test-key");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page
    .locator(".sidebar")
    .getByRole("link", { name: /New subtitles/ })
    .click();
  await page.getByLabel("Local file path").fill(info.source);
  await page
    .getByRole("button", { name: "Inspect video", exact: true })
    .click();
  await expect(page.getByLabel("Audio track")).toBeVisible();
  await page.getByLabel("Source language").selectOption("ja");
  const created = page.waitForResponse(
    (response) =>
      response.url().endsWith("/jobs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create English subtitles →" })
    .click();
  const job = await (await created).json();
  const review = page.locator(`a[href="#/review/${job.job_id}"]`);
  await expect(review).toBeVisible({ timeout: 90000 });
  await review.click();
  const text = page.getByLabel("English text");
  await expect(text).toBeVisible();
  await text.fill("Manual browser acceptance edit.");
  await expect(page.locator(".save-state")).toContainText("Saved · revision 1");
  await page.reload();
  await expect(text).toHaveValue("Manual browser acceptance edit.");
  await page
    .getByText("Playback / selected-track options", { exact: true })
    .click();
  await page
    .getByRole("button", { name: "Prepare selected-track preview" })
    .click();
  await expect(
    page.getByText("Playing a compatible preview", { exact: true }),
  ).toBeVisible({ timeout: 15000 });
  const cues = await (
    await request.get(`/jobs/${job.job_id}/cues`, {
      headers: { Authorization: "Bearer ui-test-key" },
    })
  ).json();
  await page.getByRole("button", { name: /^Cue 2:/ }).click();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video: HTMLVideoElement) => video.currentTime),
    )
    .toBeCloseTo(cues.cues[1].start_ms / 1000, 1);
  await page.getByRole("button", { name: "Prepare SRT & VTT" }).click();
  const downloading = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download SRT", exact: true }).click();
  const downloaded = await downloading;
  expect(await readFile((await downloaded.path())!, "utf8")).toContain(
    "Manual browser acceptance edit.",
  );
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({
    path: "../outputs/phase5-real-review.png",
    fullPage: true,
  });
});

test("real contextual worker: paired generation, source review and independent edits", async ({
  page,
  request,
}) => {
  test.skip(
    !process.env.LOCAL_SUBS_UI_CONTEXTUAL,
    "Enable LOCAL_SUBS_UI_CONTEXTUAL for the slower local text-model gate",
  );
  test.setTimeout(300000);
  const headers = { Authorization: "Bearer ui-test-key" };
  const jobs = await (await request.get("/jobs", { headers })).json();
  const direct = jobs.find(
    (job: { state: string; settings: { pipeline?: string } }) =>
      job.state === "completed" && job.settings.pipeline === "direct",
  );
  expect(direct).toBeTruthy();
  await page.goto(`/#/review/${direct.job_id}`);
  await page.getByLabel("Local session key").fill("ui-test-key");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Manual browser acceptance edit.",
  );
  await page
    .getByRole("button", { name: "Contextual local · Create test…" })
    .click();
  await expect(
    page.getByRole("radio", { name: "Contextual local", exact: true }),
  ).toBeChecked();
  await page
    .getByRole("button", { name: "Inspect video", exact: true })
    .click();
  const creating = page.waitForResponse(
    (response) =>
      response.url().endsWith("/jobs") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Create English subtitles →" })
    .click();
  const contextual = await (await creating).json();
  const review = page.locator(`a[href="#/review/${contextual.job_id}"]`);
  await expect(review).toBeVisible({ timeout: 240000 });
  await review.click();
  await expect(page.locator(".cue-editor .source-text")).toContainText("ja");
  const manifest = await (
    await request.get(`/jobs/${contextual.job_id}`, { headers })
  ).json();
  const source = await (
    await request.get(`/jobs/${contextual.job_id}/source-cues`, { headers })
  ).json();
  expect(source.translation.incomplete_ids).toEqual([]);
  expect(manifest.translation.state).toBe("completed");
  const comparison = await (
    await request.get(`/jobs/${contextual.job_id}/compare/${direct.job_id}`, {
      headers,
    })
  ).json();
  expect(comparison.human_meaning).toBe("unverified");
  await page
    .getByLabel("English text")
    .fill("Independent contextual acceptance edit.");
  await expect(page.locator(".save-state")).toContainText("Saved");
  await page
    .getByRole("button", { name: "Whisper direct", exact: true })
    .click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Manual browser acceptance edit.",
  );
  await page
    .getByRole("button", { name: "Contextual local", exact: true })
    .click();
  await expect(page.getByLabel("English text")).toHaveValue(
    "Independent contextual acceptance edit.",
  );
  await page.getByRole("button", { name: "Prepare SRT & VTT" }).click();
  await expect(
    page.getByRole("link", { name: "Download SRT", exact: true }),
  ).toBeVisible();
  await writeFile(
    "../outputs/phase6-live-acceptance.json",
    JSON.stringify(
      {
        direct,
        contextual: manifest,
        comparison,
        source_count: source.cues.length,
      },
      null,
      2,
    ),
  );
  await page.screenshot({
    path: "../outputs/phase6-live-comparison.png",
    fullPage: true,
  });
});
