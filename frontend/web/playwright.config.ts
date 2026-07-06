import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:8765",
    colorScheme: "dark",
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "tablet", use: { viewport: { width: 1024, height: 768 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true } },
  ],
  webServer: {
    command: "uv run python scripts/run_web_visual_fixture.py",
    cwd: "../..",
    env: {
      OPENHARNESS_CONFIG_DIR: "/tmp/openharness-web-audit/config",
      OPENHARNESS_DATA_DIR: "/tmp/openharness-web-audit/data",
      OPENHARNESS_LOGS_DIR: "/tmp/openharness-web-audit/logs",
      UV_CACHE_DIR: "/tmp/openharness-uv-cache",
    },
    url: "http://127.0.0.1:8765/",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
