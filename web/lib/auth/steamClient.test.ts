import { describe, expect, it, vi } from "vitest";
import { completeSteamLink } from "./steamClient";

/** TM11-52: the settings page asks the server to save the Steam sign-in it verified. */

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("completeSteamLink", () => {
  it("posts with the bearer token and returns the saved steamID64", async () => {
    const fetchImpl = vi.fn(() => json(200, { steamId: "76561197960287930" }));
    await expect(completeSteamLink(fetchImpl as typeof fetch, "jwt")).resolves.toEqual({
      status: "linked",
      steamId: "76561197960287930",
    });
    expect(fetchImpl).toHaveBeenCalledWith("/api/steam/link", {
      method: "POST",
      credentials: "same-origin",
      headers: { Authorization: "Bearer jwt" },
    });
  });

  it("passes the server's reason through", async () => {
    const fetchImpl = vi.fn(() => json(409, { reason: "taken" }));
    await expect(completeSteamLink(fetchImpl as typeof fetch, "jwt")).resolves.toEqual({
      status: "error",
      reason: "taken",
    });
  });

  it("does not call the server without a session", async () => {
    const fetchImpl = vi.fn();
    await expect(completeSteamLink(fetchImpl as typeof fetch, null)).resolves.toEqual({
      status: "error",
      reason: "session",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports a network failure", async () => {
    const fetchImpl = vi.fn(() => Promise.reject(new TypeError("offline")));
    await expect(completeSteamLink(fetchImpl as typeof fetch, "jwt")).resolves.toEqual({
      status: "error",
      reason: "network",
    });
  });
});
