import { describe, expect, it } from "vitest";
import {
  STEAM_LINK_TTL_SECONDS,
  openSteamId,
  sealSteamId,
  steamLinkSecretFromEnv,
} from "./steamLink";

/** TM11-52: the steamID64 sealed between /api/steam/callback and POST /api/steam/link. */

const SECRET = "0123456789abcdef0123456789abcdef";
const STEAM_ID = "76561197960287930";
const NOW = 1_760_000_000_000;

const env = (vars: Record<string, string>) => vars as unknown as NodeJS.ProcessEnv;

describe("sealSteamId / openSteamId", () => {
  it("round-trips a steamID64", () => {
    expect(openSteamId(sealSteamId(STEAM_ID, SECRET, NOW), SECRET, NOW)).toBe(STEAM_ID);
  });

  it("rejects a cookie signed with another secret", () => {
    const sealed = sealSteamId(STEAM_ID, SECRET, NOW);
    expect(openSteamId(sealed, "f".repeat(32), NOW)).toBeNull();
  });

  it("rejects a swapped steamID64, so nobody can link someone else's account", () => {
    const [, sig] = sealSteamId(STEAM_ID, SECRET, NOW).split(".");
    const forged = Buffer.from(
      JSON.stringify({ steamId: "76561198000000000", exp: NOW + 60_000 }),
    ).toString("base64url");
    expect(openSteamId(`${forged}.${sig}`, SECRET, NOW)).toBeNull();
  });

  it("expires after the TTL", () => {
    const sealed = sealSteamId(STEAM_ID, SECRET, NOW);
    const later = NOW + STEAM_LINK_TTL_SECONDS * 1000 + 1;
    expect(openSteamId(sealed, SECRET, later)).toBeNull();
  });

  it.each([undefined, null, "", "nodot", "a.b"])("rejects %j", (value) => {
    expect(openSteamId(value, SECRET, NOW)).toBeNull();
  });
});

describe("steamLinkSecretFromEnv", () => {
  it("returns a long enough secret", () => {
    expect(steamLinkSecretFromEnv(env({ STEAM_LINK_SECRET: SECRET }))).toBe(SECRET);
  });

  it("treats a missing or short secret as not configured", () => {
    expect(steamLinkSecretFromEnv(env({}))).toBeNull();
    expect(steamLinkSecretFromEnv(env({ STEAM_LINK_SECRET: "short" }))).toBeNull();
  });
});
