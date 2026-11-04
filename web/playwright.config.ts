import { defineConfig } from "@playwright/test";
const server = process.env.LOCAL_SUBS_UI_LIVE
  ? "tests/live_server.py"
  : "tests/server.py";
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  workers: 1,
  timeout: 45000,
  use: {
    baseURL: "http://127.0.0.1:8767",
    browserName: "chromium",
    channel: process.platform === "win32" ? "chrome" : undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command:
      process.platform === "win32"
        ? `"..\\.venv\\Scripts\\python.exe" ${server}`
        : `../.venv/bin/python ${server}`,
    url: "http://127.0.0.1:8767/health",
    timeout: 30000,
    reuseExistingServer: false,
  },
});
