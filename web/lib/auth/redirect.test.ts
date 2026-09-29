import { describe, it, expect } from "vitest";
import { safeNext, signInUrlFor, DEFAULT_AFTER_SIGN_IN } from "./redirect";

/**
 * TM11-27 AC3 — "unauthenticated access to a protected route redirects to sign-in then
 * returns to the intended page".
 *
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

// ---------------------------------------------------------------------------
describe("AC3 — the intended page is preserved", () => {
  it("keeps a plain path", () => {
    expect(safeNext("/library")).toBe("/library");
  });

  it("keeps the query string, so /library?filter=steam comes back whole", () => {
    expect(safeNext("/library?filter=steam")).toBe("/library?filter=steam");
  });

  it("falls back to the app root when there is no next param", () => {
    expect(safeNext(null)).toBe(DEFAULT_AFTER_SIGN_IN);
    expect(safeNext(undefined)).toBe(DEFAULT_AFTER_SIGN_IN);
    expect(safeNext("")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("builds a sign-in URL that carries the destination", () => {
    expect(signInUrlFor("/library?filter=steam")).toBe(
      "/signin?next=%2Flibrary%3Ffilter%3Dsteam",
    );
  });

  it("omits next entirely when the destination is just the root", () => {
    expect(signInUrlFor("/")).toBe("/signin");
  });
});

// ---------------------------------------------------------------------------
describe("AC3 — next cannot be used to send someone off-site", () => {
  it("rejects an absolute http URL", () => {
    expect(safeNext("https://evil.example/steal")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects a protocol-relative URL", () => {
    // Passes a naive "starts with /" check but the browser treats it as a full URL.
    expect(safeNext("//evil.example")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects the backslash variant of a protocol-relative URL", () => {
    expect(safeNext("/\\evil.example")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects a javascript: payload", () => {
    expect(safeNext("javascript:alert(1)")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects a value carrying a control character", () => {
    expect(safeNext("/library\nLocation: https://evil.example")).toBe(
      DEFAULT_AFTER_SIGN_IN,
    );
  });

  it("never emits an off-site destination through signInUrlFor", () => {
    expect(signInUrlFor("https://evil.example")).toBe("/signin");
  });
});

// ---------------------------------------------------------------------------
describe("AC3 — returning to an auth page would loop, so it is refused", () => {
  it.each(["/signin", "/register", "/auth/callback"])("rejects %s", (route) => {
    expect(safeNext(route)).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects a nested auth route", () => {
    expect(safeNext("/auth/callback/extra")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("rejects an auth route that carries its own query string", () => {
    expect(safeNext("/signin?next=%2Flibrary")).toBe(DEFAULT_AFTER_SIGN_IN);
  });

  it("does not reject a normal route that merely starts with the same letters", () => {
    expect(safeNext("/registered-games")).toBe("/registered-games");
  });
});
