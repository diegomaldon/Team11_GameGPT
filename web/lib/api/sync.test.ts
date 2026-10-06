import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/**
 * TM11-49 — library import progress, client side.
 * runLibrarySync starts a job and polls it, surfacing every snapshot.
 */

vi.mock("../auth/token", () => ({ getAccessToken: () => null }));

const { runLibrarySync, ApiError } = await import("./client");

type Job = Record<string, unknown>;

function job(over: Job = {}): Job {
  return {
    job_id: "job-1",
    state: "importing",
    total: 500,
    processed: 0,
    synced: 0,
    failed: [],
    source: "steam",
    error: null,
    started_at: "2026-10-06T14:00:00Z",
    finished_at: null,
    ...over,
  };
}

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: async () => body,
  } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AC — progress is surfaced while the sync runs", () => {
  it("reports each snapshot until the job finishes", async () => {
    fetchMock
      .mockResolvedValueOnce(response(202, job({ state: "fetching", total: 0 })))
      .mockResolvedValueOnce(response(200, job({ processed: 250, synced: 250 })))
      .mockResolvedValueOnce(
        response(200, job({ state: "succeeded", processed: 500, synced: 500 })),
      );
    const seen: Job[] = [];
    const final = await runLibrarySync("7656", (j) => seen.push(j), { intervalMs: 0 });

    expect(seen.map((j) => [j.state, j.processed])).toEqual([
      ["fetching", 0],
      ["importing", 250],
      ["succeeded", 500],
    ]);
    expect(final.state).toBe("succeeded");
    const [startUrl, startInit] = fetchMock.mock.calls[0];
    expect(startUrl).toMatch(/\/api\/library\/sync\/jobs$/);
    expect(startInit.method).toBe("POST");
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/api\/library\/sync\/jobs\/job-1$/);
  });
});

describe("AC — per-title failures are reported without aborting", () => {
  it("resolves with the failures alongside the imported count", async () => {
    const failed = [{ steam_appid: 7, title: "Broken", reason: "DataError: integer out of range" }];
    fetchMock
      .mockResolvedValueOnce(response(202, job()))
      .mockResolvedValueOnce(
        response(200, job({ state: "succeeded", processed: 500, synced: 499, failed })),
      );
    const final = await runLibrarySync("7656", () => {}, { intervalMs: 0 });
    expect(final.synced).toBe(499);
    expect(final.failed).toEqual(failed);
  });
});

describe("AC — a failed run is reported, not thrown", () => {
  it("resolves with state=failed so the UI can say the library is unchanged", async () => {
    fetchMock
      .mockResolvedValueOnce(response(202, job()))
      .mockResolvedValueOnce(response(200, job({ state: "failed", error: "rolled back" })));
    const final = await runLibrarySync("7656", () => {}, { intervalMs: 0 });
    expect(final.state).toBe("failed");
  });
});

describe("polling resilience", () => {
  it("rides out a transient poll error", async () => {
    fetchMock
      .mockResolvedValueOnce(response(202, job()))
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(response(200, job({ state: "succeeded", processed: 500 })));
    const final = await runLibrarySync("7656", () => {}, { intervalMs: 0 });
    expect(final.state).toBe("succeeded");
  });

  it("gives up after repeated poll errors", async () => {
    fetchMock
      .mockResolvedValueOnce(response(202, job()))
      .mockRejectedValue(new TypeError("network down"));
    await expect(
      runLibrarySync("7656", () => {}, { intervalMs: 0, maxPollErrors: 2 }),
    ).rejects.toThrow("network down");
  });

  it("stops immediately when the server no longer knows the job", async () => {
    fetchMock
      .mockResolvedValueOnce(response(202, job()))
      .mockResolvedValueOnce(response(404, { detail: { error: "job_not_found" } }));
    await expect(runLibrarySync("7656", () => {}, { intervalMs: 0 })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
