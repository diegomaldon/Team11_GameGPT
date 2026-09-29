import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * TM11-26 — Google OAuth sign-in.
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

const signInWithOAuth = vi.fn();
const exchangeCodeForSession = vi.fn();

vi.mock("../supabase", () => ({
  supabase: { auth: { signInWithOAuth, exchangeCodeForSession } },
}));

const { startGoogleSignIn, completeOAuthSignIn, describeCallbackError } = await import(
  "./oauth"
);

function authError(partial: Record<string, unknown>) {
  return Object.assign(new Error(String(partial.message ?? "error")), {
    name: "AuthApiError",
    ...partial,
  });
}

/** The redirectTo the last startGoogleSignIn call asked for. */
function redirectTo(): string {
  return signInWithOAuth.mock.calls[0][0].options.redirectTo;
}

beforeEach(() => {
  signInWithOAuth.mockReset().mockResolvedValue({ data: {}, error: null });
  exchangeCodeForSession.mockReset();
  vi.stubGlobal("window", { location: { origin: "http://localhost:3000" } });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
describe("starting the flow", () => {
  it("asks Supabase for Google and reports that it is redirecting", async () => {
    const result = await startGoogleSignIn();

    expect(result).toEqual({ status: "redirecting" });
    expect(signInWithOAuth.mock.calls[0][0].provider).toBe("google");
  });

  it("comes back to our own callback route", async () => {
    await startGoogleSignIn();
    expect(redirectTo()).toBe("http://localhost:3000/auth/callback");
  });

  it("carries the intended page through the round trip", async () => {
    await startGoogleSignIn("/library?filter=steam");

    const url = new URL(redirectTo());
    expect(url.pathname).toBe("/auth/callback");
    expect(url.searchParams.get("next")).toBe("/library?filter=steam");
  });

  it("refuses to carry an off-site next through the round trip", async () => {
    await startGoogleSignIn("https://evil.example");
    expect(new URL(redirectTo()).searchParams.get("next")).toBeNull();
  });

  it("forces the account chooser so a shared machine can switch users", async () => {
    await startGoogleSignIn();
    expect(signInWithOAuth.mock.calls[0][0].options.queryParams).toEqual({
      prompt: "select_account",
    });
  });

  it("says so plainly when the provider is not enabled in this environment", async () => {
    signInWithOAuth.mockResolvedValue({
      data: {},
      error: authError({ status: 400, message: "Unsupported provider: provider is not enabled" }),
    });

    const result = await startGoogleSignIn();

    expect(result.status).toBe("error");
    expect(result.status === "error" && result.message).toMatch(/isn't set up/i);
  });

  it("survives a thrown network error", async () => {
    signInWithOAuth.mockRejectedValue(new TypeError("Failed to fetch"));

    expect(await startGoogleSignIn()).toEqual({
      status: "error",
      message: "Check your connection and try again.",
    });
  });
});

// ---------------------------------------------------------------------------
describe("AC2 — a successful callback produces a session", () => {
  it("trades the code and reports where to go next", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { session: { access_token: "t" } },
      error: null,
    });

    const result = await completeOAuthSignIn(
      new URLSearchParams({ code: "abc123", next: "/library" }),
    );

    expect(exchangeCodeForSession).toHaveBeenCalledWith("abc123");
    expect(result).toEqual({ status: "signed_in", next: "/library" });
  });

  it("defaults to the app root when no next was carried", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { session: { access_token: "t" } },
      error: null,
    });

    const result = await completeOAuthSignIn(new URLSearchParams({ code: "abc123" }));

    expect(result).toEqual({ status: "signed_in", next: "/" });
  });

  it("will not follow an off-site next even with a valid code", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { session: { access_token: "t" } },
      error: null,
    });

    const result = await completeOAuthSignIn(
      new URLSearchParams({ code: "abc123", next: "https://evil.example" }),
    );

    expect(result).toEqual({ status: "signed_in", next: "/" });
  });
});

// ---------------------------------------------------------------------------
describe("AC4 — callback errors surface a usable message", () => {
  it("treats a cancelled sign-in as a refusal, not a crash", async () => {
    const result = await completeOAuthSignIn(
      new URLSearchParams({ error: "access_denied", error_description: "The user denied" }),
    );

    expect(result.status).toBe("denied");
    expect(result.status === "denied" && result.message).toMatch(/cancelled/i);
  });

  it("reads error_code as well as error", async () => {
    const result = await completeOAuthSignIn(
      new URLSearchParams({ error_code: "server_error" }),
    );

    expect(result.status).toBe("denied");
  });

  it("explains a missing code rather than hanging on a spinner", async () => {
    const result = await completeOAuthSignIn(new URLSearchParams());

    expect(result.status).toBe("error");
    expect(result.status === "error" && result.message).toMatch(/incomplete or already used/i);
  });

  it("reports a failed exchange without leaking the reason", async () => {
    exchangeCodeForSession.mockResolvedValue({
      data: { session: null },
      error: authError({ status: 400, message: "code verifier should be non-empty" }),
    });

    const result = await completeOAuthSignIn(new URLSearchParams({ code: "spent" }));

    expect(result.status).toBe("error");
    expect(result.status === "error" && result.message).not.toContain("verifier");
  });

  it("treats a success shape with no session as a failure", async () => {
    exchangeCodeForSession.mockResolvedValue({ data: { session: null }, error: null });

    expect(await completeOAuthSignIn(new URLSearchParams({ code: "abc" }))).toMatchObject({
      status: "error",
    });
  });

  it("survives a thrown network error during exchange", async () => {
    exchangeCodeForSession.mockRejectedValue(new TypeError("Failed to fetch"));

    expect(await completeOAuthSignIn(new URLSearchParams({ code: "abc" }))).toEqual({
      status: "error",
      message: "Check your connection and try again.",
    });
  });
});

// ---------------------------------------------------------------------------
describe("AC4 — every mapped error says something a person can act on", () => {
  it.each([
    ["access_denied", /cancelled/i],
    ["provider_email_needs_verification", /verify your email/i],
    ["provider_disabled", /isn't set up/i],
    ["unsupported_provider", /isn't set up/i],
    ["redirect_uri_mismatch", /configuration problem/i],
    ["server_error", /try again/i],
    ["temporarily_unavailable", /try again/i],
  ])("%s", (code, expected) => {
    expect(describeCallbackError(code)).toMatch(expected);
  });

  it("falls back to advice rather than an error code for anything unmapped", () => {
    const message = describeCallbackError("something_new_from_gotrue", "internal detail");

    expect(message).toMatch(/try again/i);
    // The raw description can name internal config, so it is logged, not displayed.
    expect(message).not.toContain("internal detail");
    expect(message).not.toContain("something_new_from_gotrue");
  });
});
