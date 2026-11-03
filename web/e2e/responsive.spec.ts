import { test, expect, type Page, type TestInfo } from "@playwright/test";
import path from "node:path";

/**
 * REQ039 — "Full use on mobile without installing anything."
 *
 * Acceptance criteria checked here, automatically, on every page:
 *   • Usable at 320 px, 360 px, 375 px, 768 px and 1440 px.
 *   • No horizontal scroll.
 *   • No clipped / off-screen controls.
 *   • Exercised in Chrome (Chromium) and Safari (WebKit) — see playwright.config.ts.
 *
 * Each test also attaches a full-page screenshot and writes it to
 * test-results/screens/, so the layout can be eyeballed per width per engine —
 * the "visually verify" part of the request.
 */

const VIEWPORTS = [
  { label: "320-small", width: 320, height: 640 }, // smallest width WCAG reflow targets
  { label: "360-android", width: 360, height: 780 }, // common Android width
  { label: "375-mobile", width: 375, height: 812 }, // iPhone-class width
  { label: "768-tablet", width: 768, height: 1024 }, // iPad-class width / md breakpoint
  { label: "1440-desktop", width: 1440, height: 900 }, // laptop width
] as const;

// Public (signed-out) pages. `heading` is a real, page-specific heading so the
// test fails (rather than false-passing on Next's dev error overlay) if the
// page crashes to render.
const PUBLIC_PAGES = [
  { name: "signin", path: "/signin", heading: /Welcome back/ },
  { name: "register", path: "/register", heading: /Create your account/ },
] as const;

// Authenticated pages, rendered inside the AppShell chrome.
const APP_PAGES = [
  { name: "discover", path: "/", heading: /Describe a vibe/ },
  { name: "library", path: "/library", heading: /Your library/ },
  { name: "settings", path: "/settings", heading: /^Settings$/ },
] as const;

/**
 * Protected routes sit behind <RequireAuth>, which asks supabase-js for a session, and
 * supabase-js reads it from localStorage under `sb-<project ref>-auth-token`. Seeding an
 * unexpired session there before any page script runs lands us on the page signed in,
 * with no network call (the token is only refreshed near expiry). The mock store's
 * `signedIn` flag is seeded too, for the profile data it still supplies.
 * addInitScript re-runs on every navigation, so both survive client-side redirects.
 */
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "https://placeholder.supabase.co";
const AUTH_KEY = `sb-${new URL(SUPABASE_URL).hostname.split(".")[0]}-auth-token`;

async function seedSignedIn(page: Page) {
  const session = {
    access_token: "e2e.fake.token",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 24 * 3600,
    refresh_token: "e2e-fake-refresh",
    user: {
      id: "00000000-0000-0000-0000-0000000000e2",
      aud: "authenticated",
      role: "authenticated",
      email: "e2e@example.com",
      user_metadata: { display_name: "E2E Tester" },
      app_metadata: { provider: "email" },
      created_at: "2026-09-01T00:00:00Z",
    },
  };
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
      window.localStorage.setItem("gamegpt.mock.v1", JSON.stringify({ signedIn: true }));
    },
    { key: AUTH_KEY, value: JSON.stringify(session) },
  );
}

/** The document must not scroll sideways at the given width (1px rounding slack). */
async function expectNoHorizontalScroll(page: Page, width: number) {
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(
    scrollWidth,
    `document scrollWidth (${scrollWidth}px) exceeds viewport width (${width}px) → horizontal scroll`,
  ).toBeLessThanOrEqual(width + 1);
}

/**
 * Every visible interactive control must sit fully inside the viewport
 * horizontally. Catches buttons/inputs pushed off the right edge or clipped on
 * the left — the "no clipped controls" criterion. Controls inside a container that
 * scrolls sideways on its own (the Popular games strip) are skipped: they are off-screen
 * by design and reached by scrolling that container, not the page.
 */
async function expectControlsNotClipped(page: Page, width: number) {
  const offenders = await page.evaluate((vw) => {
    const bad: string[] = [];
    const inScroller = (el: Element) => {
      for (let p = el.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === "auto" || ox === "scroll") && p.scrollWidth > p.clientWidth) return true;
      }
      return false;
    };
    const controls = document.querySelectorAll(
      'a, button, input, select, textarea, [role="switch"], [role="dialog"]',
    );
    controls.forEach((el) => {
      const style = getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") return;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return; // not rendered
      if (inScroller(el)) return;
      if (r.right > vw + 1 || r.left < -1) {
        const label =
          el.getAttribute("aria-label") ||
          el.textContent?.trim().slice(0, 30) ||
          "";
        bad.push(
          `<${el.tagName.toLowerCase()}${label ? ` "${label}"` : ""}> left=${Math.round(r.left)} right=${Math.round(r.right)}`,
        );
      }
    });
    return bad;
  }, width);

  expect(
    offenders,
    `controls clipped or off-screen horizontally:\n  ${offenders.join("\n  ")}`,
  ).toEqual([]);
}

// Screens are grouped by engine into e2e/screens/<chrome|safari>/ for easy
// side-by-side visual review, and also attached to the HTML report.
async function capture(
  page: Page,
  name: string,
  viewportLabel: string,
  testInfo: TestInfo,
  fullPage = true,
) {
  const file = path.join(
    testInfo.project.testDir,
    "screens",
    testInfo.project.name,
    `${name}-${viewportLabel}.png`,
  );
  const buf = await page.screenshot({ fullPage, path: file });
  await testInfo.attach(`${name}-${viewportLabel}`, {
    body: buf,
    contentType: "image/png",
  });
}

for (const vp of VIEWPORTS) {
  test.describe(`${vp.width}px`, () => {
    test.use({ viewport: { width: vp.width, height: vp.height } });

    for (const p of PUBLIC_PAGES) {
      test(`${p.name} — no h-scroll, controls in view`, async ({ page }, testInfo) => {
        await page.goto(p.path);
        // Wait for the page's own heading, not networkidle (Next dev keeps an
        // HMR socket open).
        await expect(page.getByRole("heading", { name: p.heading })).toBeVisible();
        await expectNoHorizontalScroll(page, vp.width);
        await expectControlsNotClipped(page, vp.width);
        await capture(page, p.name, vp.label, testInfo);
      });
    }

    for (const p of APP_PAGES) {
      test(`${p.name} (signed in) — no h-scroll, controls in view`, async ({ page }, testInfo) => {
        await seedSignedIn(page);
        await page.goto(p.path);
        // AppShell renders a "Loading…" gate until hydrated+signed-in; wait for
        // the real chrome (nav) and the page's own heading.
        await expect(page.getByRole("navigation").first()).toBeVisible();
        await expect(page.getByRole("heading", { name: p.heading })).toBeVisible();
        await expectNoHorizontalScroll(page, vp.width);
        await expectControlsNotClipped(page, vp.width);
        await capture(page, p.name, vp.label, testInfo);
      });
    }
  });
}

/**
 * Bottom-sheet modal on the smallest phone width: the "Add game" dialog is a
 * common place for controls to overflow. Verify it opens, fits, and its buttons
 * are reachable at 375px in both engines.
 */
test.describe("modal @ 375px", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("add-game modal fits and controls are in view", async ({ page }, testInfo) => {
    await seedSignedIn(page);
    await page.goto("/library");
    await page.getByRole("button", { name: "Add game" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.getByRole("button", { name: "Add to library" })).toBeVisible();
    await expectNoHorizontalScroll(page, 375);
    await expectControlsNotClipped(page, 375);
    // Viewport-only shot: the modal is position:fixed, so a fullPage capture
    // would smear it over the scrolled page behind it.
    await capture(page, "library-add-modal", "375-mobile", testInfo, false);
  });
});
