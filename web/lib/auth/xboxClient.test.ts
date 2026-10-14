import { describe, it, expect, vi } from "vitest";

/** TM11-53 — the browser call that finishes an Xbox link. */

vi.mock("./token", () => ({ getAccessToken: () => null }));
const { completeXboxLink } = await import("./xboxClient");

function response(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("completeXboxLink", () => {
  it("posts to /api/xbox/link with the session token and returns the gamertag", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(200, { gamertag: "MajorNelson" }));
    await expect(completeXboxLink(fetchImpl, "jwt-1")).resolves.toEqual({
      status: "linked",
      gamertag: "MajorNelson",
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/api/xbox/link");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer jwt-1");
  });

  it("passes the server's reason through so the page can explain it", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(response(409, { reason: "taken" }));
    await expect(completeXboxLink(fetchImpl, "jwt-1")).resolves.toEqual({
      status: "error",
      reason: "taken",
    });
  });

  it("does not call the server without a session", async () => {
    const fetchImpl = vi.fn();
    await expect(completeXboxLink(fetchImpl, null)).resolves.toEqual({
      status: "error",
      reason: "session",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports a thrown fetch as a network error", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("offline"));
    await expect(completeXboxLink(fetchImpl, "jwt-1")).resolves.toEqual({
      status: "error",
      reason: "network",
    });
  });
});
