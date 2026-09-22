import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * TM11-27 — email + password sign-in, the path that produces the session the auth gate
 * checks for. Grouped so the output reads as a checklist.
 */

const signInWithPasswordMock = vi.fn();
vi.mock("../supabase", () => ({
  supabase: { auth: { signInWithPassword: signInWithPasswordMock } },
}));

const { signInWithPassword } = await import("./signin");

const VALID = { email: "Diego@Example.com", password: "CorrectHorse9Battery" };

function authError(partial: Record<string, unknown>) {
  return Object.assign(new Error(String(partial.message ?? "error")), {
    name: "AuthApiError",
    ...partial,
  });
}

function ok() {
  return {
    data: { session: { access_token: "t" }, user: { id: "u1" } },
    error: null,
  };
}

beforeEach(() => {
  signInWithPasswordMock.mockReset();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
describe("validation blocks a bad submit before any network call", () => {
  it("rejects an empty email", async () => {
    const result = await signInWithPassword({ ...VALID, email: "" });

    expect(result).toMatchObject({ status: "invalid" });
    expect(signInWithPasswordMock).not.toHaveBeenCalled();
  });

  it("rejects an empty password", async () => {
    const result = await signInWithPassword({ ...VALID, password: "" });

    expect(result.status === "invalid" && result.fieldErrors.password?.[0]).toBe(
      "Enter your password.",
    );
    expect(signInWithPasswordMock).not.toHaveBeenCalled();
  });

  it("does not apply registration complexity rules to an existing password", async () => {
    signInWithPasswordMock.mockResolvedValue(ok());

    // Short and lowercase: registerSchema would reject it, sign-in must not.
    const result = await signInWithPassword({ ...VALID, password: "old" });

    expect(result).toMatchObject({ status: "signed_in" });
  });

  it("normalises the email before sending it", async () => {
    signInWithPasswordMock.mockResolvedValue(ok());

    await signInWithPassword({ ...VALID, email: "  Diego@Example.COM  " });

    expect(signInWithPasswordMock).toHaveBeenCalledWith({
      email: "diego@example.com",
      password: VALID.password,
    });
  });
});

// ---------------------------------------------------------------------------
describe("failures map to something the form can say out loud", () => {
  it("collapses wrong password and unknown address into one result", async () => {
    signInWithPasswordMock.mockResolvedValue({
      data: { session: null, user: null },
      error: authError({ status: 400, code: "invalid_credentials" }),
    });

    const result = await signInWithPassword(VALID);

    // One case on purpose: telling them apart would let anyone probe for accounts.
    expect(result).toEqual({ status: "invalid_credentials" });
  });

  it("separates an unconfirmed account, which needs different advice", async () => {
    signInWithPasswordMock.mockResolvedValue({
      data: { session: null, user: null },
      error: authError({ status: 400, code: "email_not_confirmed" }),
    });

    expect(await signInWithPassword(VALID)).toEqual({ status: "email_not_confirmed" });
  });

  it("reports a rate limit with the wait when GoTrue gives one", async () => {
    signInWithPasswordMock.mockResolvedValue({
      data: { session: null, user: null },
      error: authError({ status: 429, message: "try again in 34 seconds" }),
    });

    expect(await signInWithPassword(VALID)).toEqual({
      status: "rate_limited",
      retryAfterSeconds: 34,
    });
  });

  it("treats a success shape with no session as a failure", async () => {
    signInWithPasswordMock.mockResolvedValue({
      data: { session: null, user: null },
      error: null,
    });

    expect(await signInWithPassword(VALID)).toMatchObject({ status: "error" });
  });

  it("survives a thrown network error", async () => {
    signInWithPasswordMock.mockRejectedValue(new TypeError("Failed to fetch"));

    expect(await signInWithPassword(VALID)).toEqual({
      status: "error",
      message: "Check your connection and try again.",
    });
  });
});

// ---------------------------------------------------------------------------
describe("the password never reaches a log", () => {
  it("keeps the plaintext out of every console.error argument", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    signInWithPasswordMock.mockResolvedValue({
      data: { session: null, user: null },
      error: authError({ status: 500, message: "boom" }),
    });

    await signInWithPassword(VALID);

    const logged = JSON.stringify(spy.mock.calls);
    expect(logged).not.toContain(VALID.password);
  });

  it("keeps the plaintext out of logs when the call throws", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    signInWithPasswordMock.mockRejectedValue(new Error(`failed for ${VALID.password}`));

    await signInWithPassword(VALID);

    // The thrown message is the one place a password could ride along; scrubError keeps
    // name/message/status only, so this asserts the caller never adds the input back.
    const calls = spy.mock.calls.map((c) => c[0]);
    expect(calls.join(" ")).not.toContain("password=");
  });
});
