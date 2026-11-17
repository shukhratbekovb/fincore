import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  workers: 1,
  use: {
    actionTimeout: 15000,
    baseURL: "http://localhost:3000",
    browserName: "chromium",
    channel: process.env.CI ? undefined : "chrome",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  reporter: process.env.CI
    ? [
        ["list"],
        ["html", { open: "never" }],
        ["junit", { outputFile: "test-results/e2e.xml" }],
      ]
    : "list",
});
