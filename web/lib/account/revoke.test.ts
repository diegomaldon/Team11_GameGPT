import { describe, it, expect, vi } from "vitest";
import { revokePlatformTokens, type PlatformAccount } from "./revoke";

/**
 * TM11 REQ005 — "platform tokens revoked where the provider allows".
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

function account(
  platform: PlatformAccount["platform"],
  access_token: string | null,
): PlatformAccount {
  return { platform, access_token };
}

function okFetch() {
  return vi.fn().mockResolvedValue({ ok: true, status: 200 } as Response);
}

// ---------------------------------------------------------------------------
describe("providers that allow revocation", () => {
  it("revokes an Epic token against the provider endpoint", async () => {
    const fetchImpl = okFetch();

    const [outcome] = await revokePlatformTokens(
      [account("EPIC", "epic-token")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcome).toEqual({ platform: "EPIC", status: "revoked" });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.epicgames.dev/epic/oauth/v2/revoke");
    expect(init.method).toBe("POST");
    expect(init.body).toContain("epic-token");
  });
});

// ---------------------------------------------------------------------------
describe("providers that do not allow revocation say so plainly", () => {
  it("reports Steam as unsupported rather than pretending to revoke", async () => {
    const fetchImpl = okFetch();

    const [outcome] = await revokePlatformTokens(
      [account("STEAM", "somehow-a-token")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcome.status).toBe("unsupported");
    expect(outcome.status === "unsupported" && outcome.reason).toMatch(/OpenID/i);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports Xbox as unsupported and names why", async () => {
    const [outcome] = await revokePlatformTokens(
      [account("XBOX", "ms-token")],
      okFetch() as unknown as typeof fetch,
    );

    expect(outcome.status).toBe("unsupported");
    expect(outcome.status === "unsupported" && outcome.reason).toMatch(/Microsoft/i);
  });

  it("distinguishes no stored token from an unsupported provider", async () => {
    const outcomes = await revokePlatformTokens(
      [account("STEAM", null), account("EPIC", "  ")],
      okFetch() as unknown as typeof fetch,
    );

    // Steam today stores no token at all, which is a different fact from
    // "the provider refuses to revoke".
    expect(outcomes.map((o) => o.status)).toEqual(["no_token", "no_token"]);
  });
});

// ---------------------------------------------------------------------------
describe("a failing provider cannot block account deletion", () => {
  it("records a non-2xx response as failed and does not throw", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 503 } as Response);

    const [outcome] = await revokePlatformTokens(
      [account("EPIC", "t")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcome.status).toBe("failed");
    expect(outcome.status === "failed" && outcome.reason).toContain("503");
  });

  it("records a network error as failed and does not throw", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const [outcome] = await revokePlatformTokens(
      [account("EPIC", "t")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcome).toEqual({
      platform: "EPIC",
      status: "failed",
      reason: "Could not reach the provider.",
    });
  });

  it("gives a provider that hangs its own message", async () => {
    const timeout = Object.assign(new Error("timed out"), { name: "TimeoutError" });
    const fetchImpl = vi.fn().mockRejectedValue(timeout);

    const [outcome] = await revokePlatformTokens(
      [account("EPIC", "t")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcome.status === "failed" && outcome.reason).toMatch(/did not respond/i);
  });

  it("keeps going after one provider fails", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ ok: true, status: 200 } as Response);

    const outcomes = await revokePlatformTokens(
      [account("EPIC", "a"), account("EPIC", "b")],
      fetchImpl as unknown as typeof fetch,
    );

    expect(outcomes.map((o) => o.status)).toEqual(["failed", "revoked"]);
  });
});

// ---------------------------------------------------------------------------
describe("nothing linked", () => {
  it("returns an empty list rather than failing", async () => {
    expect(await revokePlatformTokens([], okFetch() as unknown as typeof fetch)).toEqual([]);
  });
});
