import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * TM11 REQ005 — account deletion, client side.
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

const getSession = vi.fn();
vi.mock("../supabase", () => ({ supabase: { auth: { getSession } } }));

const { deleteMyAccount, confirmationMatches, DELETE_CONFIRMATION } = await import(
  "./delete"
);

function session(access_token = "jwt-123") {
  return { data: { session: { access_token } }, error: null };
}

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  getSession.mockReset().mockResolvedValue(session());
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
describe("AC — the settings action requires explicit confirmation", () => {
  it("accepts the exact word", () => {
    expect(confirmationMatches(DELETE_CONFIRMATION)).toBe(true);
  });

  it("tolerates surrounding whitespace from a paste", () => {
    expect(confirmationMatches("  DELETE  ")).toBe(true);
  });

  it("rejects the wrong case, so the gesture stays deliberate", () => {
    expect(confirmationMatches("delete")).toBe(false);
    expect(confirmationMatches("Delete")).toBe(false);
  });

  it("rejects empty input and near misses", () => {
    expect(confirmationMatches("")).toBe(false);
    expect(confirmationMatches("DELET")).toBe(false);
    expect(confirmationMatches("DELETE ACCOUNT")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
describe("AC — deletion removes the account", () => {
  it("sends the session token and reports the revocations back", async () => {
    const revocations = [{ platform: "STEAM", status: "no_token" }];
    vi.mocked(fetch).mockResolvedValue(response(200, { deleted: true, revocations }));

    const result = await deleteMyAccount();

    expect(result).toEqual({ status: "deleted", revocations });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/account/delete");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer jwt-123");
  });

  it("copes with a success that carries no revocation list", async () => {
    vi.mocked(fetch).mockResolvedValue(response(200, { deleted: true }));

    expect(await deleteMyAccount()).toEqual({ status: "deleted", revocations: [] });
  });
});

// ---------------------------------------------------------------------------
describe("failures never claim the account was deleted", () => {
  it("does not call the API without a session", async () => {
    getSession.mockResolvedValue({ data: { session: null }, error: null });

    expect(await deleteMyAccount()).toEqual({ status: "unauthenticated" });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("treats a 401 as an expired session", async () => {
    vi.mocked(fetch).mockResolvedValue(response(401, { error: "nope" }));

    expect(await deleteMyAccount()).toEqual({ status: "unauthenticated" });
  });

  it("surfaces the server's message on a 500", async () => {
    vi.mocked(fetch).mockResolvedValue(
      response(500, { error: "We couldn't delete your account." }),
    );

    expect(await deleteMyAccount()).toEqual({
      status: "error",
      message: "We couldn't delete your account.",
    });
  });

  it("refuses a 200 that does not actually confirm deletion", async () => {
    // A proxy or error page returning 200 must not read as success.
    vi.mocked(fetch).mockResolvedValue(response(200, { deleted: false }));

    expect((await deleteMyAccount()).status).toBe("error");
  });

  it("survives a body that is not JSON", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("Unexpected token");
      },
    } as unknown as Response);

    expect((await deleteMyAccount()).status).toBe("error");
  });

  it("tells the user to check rather than retry when the connection drops", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    const result = await deleteMyAccount();

    // The request may have succeeded before the socket died, so a blind retry
    // is the wrong advice.
    expect(result.status).toBe("error");
    expect(result.status === "error" && result.message).toMatch(/reload and check/i);
  });
});
