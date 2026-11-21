// TM11-77: the client gives up on a hung recommend, library or history read, so the
// page can show the rainy-day "try again" state instead of loading forever.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/token", () => ({ getAccessToken: () => null }));

const {
  ApiError,
  getHistory,
  getLibrary,
  recommend,
  REQUEST_TIMEOUT_CODE,
  startLibrarySync,
} = await import("./client");

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers(),
    json: async () => body,
  } as Response;
}

/** A fetch that never answers, and rejects the way a browser does when it is aborted. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init.signal?.addEventListener("abort", () =>
          reject(new DOMException("The operation was aborted.", "AbortError")),
        );
      }),
  );
}

/** Rejects with whatever `promise` rejects with, after running the fake clock forward. */
async function rejectionAfter(promise: Promise<unknown>, ms: number): Promise<unknown> {
  const caught = promise.catch((err: unknown) => err);
  await vi.advanceTimersByTimeAsync(ms);
  return caught;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("request time limits", () => {
  it("gives up on a recommend after 15 seconds with a timeout error", async () => {
    vi.stubGlobal("fetch", hangingFetch());

    const err = await rejectionAfter(recommend("cozy farming"), 15_000);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as InstanceType<typeof ApiError>).code).toBe(REQUEST_TIMEOUT_CODE);
  });

  it("lets a recommend that answers inside the limit through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) =>
            setTimeout(() => resolve(response(200, { recommendations: [] })), 14_000),
          ),
      ),
    );

    const pending = recommend("cozy farming");
    await vi.advanceTimersByTimeAsync(14_000);

    await expect(pending).resolves.toEqual({ recommendations: [] });
  });

  it("gives up on reading the library after 10 seconds", async () => {
    vi.stubGlobal("fetch", hangingFetch());

    const err = await rejectionAfter(getLibrary(), 10_000);

    expect((err as InstanceType<typeof ApiError>).code).toBe(REQUEST_TIMEOUT_CODE);
  });

  it("does not put a time limit on starting a library import", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(200, { job_id: "job-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await startLibrarySync("76561197960287930");

    expect(fetchMock.mock.calls[0][1].signal).toBeUndefined();
  });

  it("still reports a network failure as it is, not as a timeout", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(recommend("cozy farming")).rejects.toBeInstanceOf(TypeError);
  });
});

describe("getHistory", () => {
  it("reads the user's past searches with the requested limit", async () => {
    const body = { items: [] };
    const fetchMock = vi.fn().mockResolvedValue(response(200, body));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getHistory(5)).resolves.toEqual(body);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/history\?limit=5$/);
  });

  it("passes on the server's db_unavailable code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        response(503, { detail: { error: "db_unavailable", message: "Try again later." } }),
      ),
    );

    const err = await getHistory().catch((e: unknown) => e);

    expect((err as InstanceType<typeof ApiError>).code).toBe("db_unavailable");
  });

  it("gives up after 10 seconds", async () => {
    vi.stubGlobal("fetch", hangingFetch());

    const err = await rejectionAfter(getHistory(), 10_000);

    expect((err as InstanceType<typeof ApiError>).code).toBe(REQUEST_TIMEOUT_CODE);
  });
});
