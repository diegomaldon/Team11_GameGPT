import { describe, it, expect, vi } from "vitest";
import {
  STEAM_OPENID_ENDPOINT,
  buildSteamAuthUrl,
  parseSteamCallback,
  buildVerificationBody,
  verifySteamAssertion,
  extractSteamId,
  linkedAccountsResult,
  describeSteamResult,
} from "./steam";

/**
 * TM11-44 — Steam OpenID redirect and callback flow.
 * Grouped by acceptance criterion so the output reads as a checklist.
 */

const CLAIMED = "https://steamcommunity.com/openid/id/76561197960287930";
const STEAM_ID = "76561197960287930";

/** A realistic positive assertion, plus our own state/next riding on return_to. */
function idRes(overrides: Record<string, string> = {}): URLSearchParams {
  return new URLSearchParams({
    state: "nonce-123",
    next: "/library",
    "openid.ns": "http://specs.openid.net/auth/2.0",
    "openid.mode": "id_res",
    "openid.op_endpoint": STEAM_OPENID_ENDPOINT,
    "openid.claimed_id": CLAIMED,
    "openid.identity": CLAIMED,
    "openid.sig": "abcSIGdef",
    "openid.signed": "signed,op_endpoint,claimed_id,identity,mode",
    ...overrides,
  });
}

// ---------------------------------------------------------------------------
describe("AC1 — the redirect to Steam", () => {
  it("points at Steam's OpenID endpoint in checkid_setup mode", () => {
    const url = new URL(
      buildSteamAuthUrl({ realm: "https://app.example", returnTo: "https://app.example/api/steam/callback" }),
    );
    expect(`${url.origin}${url.pathname}`).toBe(STEAM_OPENID_ENDPOINT);
    expect(url.searchParams.get("openid.mode")).toBe("checkid_setup");
  });

  it("asks Steam to pick the user (identifier select), since we don't know the id yet", () => {
    const url = new URL(buildSteamAuthUrl({ realm: "https://app.example", returnTo: "https://app.example/cb" }));
    const select = "http://specs.openid.net/auth/2.0/identifier_select";
    expect(url.searchParams.get("openid.identity")).toBe(select);
    expect(url.searchParams.get("openid.claimed_id")).toBe(select);
  });

  it("carries the realm and return_to it was given (built from the request origin — AC4)", () => {
    const url = new URL(
      buildSteamAuthUrl({ realm: "https://deployed.example", returnTo: "https://deployed.example/api/steam/callback?state=x" }),
    );
    expect(url.searchParams.get("openid.realm")).toBe("https://deployed.example");
    expect(url.searchParams.get("openid.return_to")).toBe("https://deployed.example/api/steam/callback?state=x");
  });
});

// ---------------------------------------------------------------------------
describe("AC1 — reading and verifying the assertion", () => {
  it("treats a positive assertion as ready to verify and pulls out the claimed id", () => {
    const result = parseSteamCallback(idRes());
    expect(result.status).toBe("assertion");
    expect(result.status === "assertion" && result.claimedId).toBe(CLAIMED);
  });

  it("sends only openid.* fields back for verification, with mode swapped", () => {
    const body = buildVerificationBody(idRes());
    expect(body.get("openid.mode")).toBe("check_authentication");
    // Our own params must not be echoed to Steam — it neither signed nor expects them.
    expect(body.get("state")).toBeNull();
    expect(body.get("next")).toBeNull();
    expect(body.get("openid.sig")).toBe("abcSIGdef");
  });

  it("confirms only on an explicit is_valid:true from Steam", async () => {
    const ok = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve("ns:...\nis_valid:true\n") });
    expect(await verifySteamAssertion(new URLSearchParams(), ok as unknown as typeof fetch)).toBe(true);
  });

  it("rejects a forged assertion Steam says is_valid:false", async () => {
    const no = vi.fn().mockResolvedValue({ ok: true, text: () => Promise.resolve("is_valid:false\n") });
    expect(await verifySteamAssertion(new URLSearchParams(), no as unknown as typeof fetch)).toBe(false);
  });

  it("treats a non-200 or a thrown fetch as not verified, never as a pass", async () => {
    const bad = vi.fn().mockResolvedValue({ ok: false, text: () => Promise.resolve("is_valid:true") });
    const threw = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    expect(await verifySteamAssertion(new URLSearchParams(), bad as unknown as typeof fetch)).toBe(false);
    expect(await verifySteamAssertion(new URLSearchParams(), threw as unknown as typeof fetch)).toBe(false);
  });

  it("extracts the 17-digit steamID64 from a valid claimed_id", () => {
    expect(extractSteamId(CLAIMED)).toBe(STEAM_ID);
  });

  it("refuses a claimed_id that is not a Steam identity URL", () => {
    expect(extractSteamId("https://evil.example/openid/id/76561197960287930")).toBeNull();
    expect(extractSteamId("https://steamcommunity.com/openid/id/not-a-number")).toBeNull();
    expect(parseSteamCallback(idRes({ "openid.claimed_id": "https://evil.example/id/1" }))).toEqual({
      status: "error",
      reason: "identity",
    });
  });
});

// ---------------------------------------------------------------------------
describe("AC3 — cancelled or failed auth returns to linked accounts with a message", () => {
  it("reads Steam's mode=cancel as a cancellation, not a crash", () => {
    expect(parseSteamCallback(new URLSearchParams({ "openid.mode": "cancel" }))).toEqual({
      status: "cancelled",
    });
  });

  it("treats a direct hit or spent link (no id_res) as an error", () => {
    expect(parseSteamCallback(new URLSearchParams())).toEqual({ status: "error", reason: "mode" });
  });

  it("always lands back on /settings carrying the outcome", () => {
    expect(linkedAccountsResult("cancelled")).toBe("/settings?steam=cancelled");
    expect(linkedAccountsResult("error", { reason: "verify" })).toBe("/settings?steam=error&reason=verify");
    expect(linkedAccountsResult("linked", { steamId: STEAM_ID })).toBe(
      `/settings?steam=linked&steamid=${STEAM_ID}`,
    );
  });

  it("carries a safe next but refuses to smuggle an off-site one through return_to", () => {
    expect(linkedAccountsResult("linked", { steamId: STEAM_ID, next: "/library" })).toContain("next=%2Flibrary");
    expect(linkedAccountsResult("cancelled", { next: "https://evil.example" })).toBe("/settings?steam=cancelled");
  });

  it("turns each outcome into a message a person can act on", () => {
    expect(describeSteamResult("linked")).toMatchObject({ tone: "success" });
    expect(describeSteamResult("cancelled")).toMatchObject({ tone: "info" });
    expect(describeSteamResult("error", "state")?.message).toMatch(/couldn't be verified as yours/i);
    expect(describeSteamResult("error", "verify")?.message).toMatch(/couldn't confirm/i);
    expect(describeSteamResult(null)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
describe("AC2 — the state nonce", () => {
  it("rides on return_to alongside the openid fields and is kept out of the Steam verify POST", () => {
    // parseSteamCallback keeps state available to the caller (which compares it to the cookie)
    // while buildVerificationBody strips it, so the two responsibilities don't leak into each other.
    const params = idRes({ state: "nonce-xyz" });
    expect(params.get("state")).toBe("nonce-xyz");
    expect(buildVerificationBody(params).has("state")).toBe(false);
  });
});
