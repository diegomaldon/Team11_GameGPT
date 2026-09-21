import { defineConfig, devices } from "@playwright/test";

/**
 * GameGPT · REQ039 · Mobile / responsive E2E.
 *
 * Verifies the app is fully usable on a phone with nothing installed: no
 * horizontal scroll and no clipped controls at 375 / 768 / 1440 px, in both
 * Chrome (Chromium) and Safari (WebKit). These are the two engines that ship on
 * real phones — Chrome on Android and every iOS browser (all iOS browsers are
 * WebKit under the hood). Emulation is not a literal replacement for a physical
 * handset, but it exercises the same layout engines at the same widths, which is
 * what the layout part of the acceptance criteria turns on.
 *
 * Kept separate from the Vitest unit suite: Playwright owns `e2e/**`, Vitest owns
 * everything else (see the `e2e/**` exclude in vitest.config.ts).
 */
export default defineConfig({
  testDir: "./e2e",
  // Only our Playwright specs — never the Vitest *.test.ts(x) files under app/.
  testMatch: "**/*.spec.ts",
  // Screenshots + traces land here so they can be browsed after a run.
  outputDir: "test-results",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // First hit on a Next dev route triggers an on-demand compile, so give each
  // test room beyond the 30s default.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    // We capture our own full-page screenshots as evidence; also grab one on
    // failure automatically.
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chrome", use: { ...devices["Desktop Chrome"] } },
    { name: "safari", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    // lib/supabase.ts throws on import if these are missing, which would crash
    // /register before we can test its layout. They're public, browser-safe
    // values; harmless placeholders let the page render for layout checks. Real
    // values from the shell/.env.local take precedence (Next won't override an
    // env var already set on the process).
    env: {
      NEXT_PUBLIC_SUPABASE_URL:
        process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://placeholder.supabase.co",
      NEXT_PUBLIC_SUPABASE_ANON_KEY:
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "placeholder-anon-key-for-e2e",
    },
  },
});
