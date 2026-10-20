import { describe, expect, it, vi } from "vitest";
import type { XboxSession } from "@/lib/auth/xbox";
import {
  fetchXboxTitleHistory,
  importXboxLibrary,
  titleHistoryUrl,
  type ImportDb,
} from "./xboxImport";

/**
 * TM11-56 — Xbox library import, server half. No network: titlehub and the GameGPT API
 * are fake fetches, and platform_accounts is a fake supabase-js slice.
 */

const SESSION: XboxSession = {
  xuid: "2533274812345678",
  gamertag: "MajorNelson",
  uhs: "1234567890",
  xstsToken: "xsts-token",
};
const API = "http://api.test";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const HISTORY = {
  titles: [
    { titleId: "2043073184", name: "Halo Infinite", type: "Game" },
    { titleId: "1144039928", name: "Portal 2™", type: "Game" },
    { titleId: "327370029", name: "Netflix", type: "App" },
    { titleId: "", name: "No id", type: "Game" },
    { titleId: "1915865634", name: "   ", type: "Game" },
  ],
};

const SUMMARY = {
  total: 2, added: 2, updated: 0, already_owned: 0, matched: 2, unmatched: 0,
  match_rate: 1, import_id: null,
};

function fakeDb({
  linkedXuid = SESSION.xuid as string | null,
  signedIn = true,
  readError = false,
} = {}): ImportDb {
  return {
    auth: {
      getUser: async () => ({
        data: { user: signedIn ? { id: "user-1" } : null },
        error: signedIn ? null : new Error("expired"),
      }),
    },
    from: () => ({
      select: () => ({
        eq: () => ({
          maybeSingle: async () => ({
            data: linkedXuid ? { platform_user_id: linkedXuid } : null,
            error: readError ? { message: "permission denied" } : null,
          }),
        }),
      }),
    }),
  };
}

function routes(titlehub: () => Response, api: () => Response = () => json(200, SUMMARY)) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === titleHistoryUrl(SESSION.xuid)) return titlehub();
    if (url === `${API}/api/library/xbox`) return api();
    throw new Error(`unexpected fetch ${url}`);
  }) as unknown as typeof fetch;
}

// ---------------------------------------------------------------------------
describe("reading the Xbox title history", () => {
  it("calls titlehub for the session's XUID with the XBL3.0 header", async () => {
    const fetchImpl = routes(() => json(200, HISTORY));
    await fetchXboxTitleHistory(SESSION, fetchImpl);

    const [url, init] = vi.mocked(fetchImpl).mock.calls[0];
    expect(String(url)).toBe(
      "https://titlehub.xboxlive.com/users/xuid(2533274812345678)/titles/titlehistory/decoration/detail",
    );
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("XBL3.0 x=1234567890;xsts-token");
    expect(headers["x-xbl-contract-version"]).toBe("2");
  });

  it("keeps games, and drops apps and entries without an id or a name", async () => {
    const titles = await fetchXboxTitleHistory(SESSION, routes(() => json(200, HISTORY)));
    expect(titles).toEqual([
      { title_id: "2043073184", name: "Halo Infinite" },
      { title_id: "1144039928", name: "Portal 2™" },
    ]);
  });

  it.each([
    [401, "expired"],
    [403, "private"],
    [503, "network"],
    [404, "import"],
  ])("maps a titlehub %i to %s", async (status, reason) => {
    await expect(
      fetchXboxTitleHistory(SESSION, routes(() => json(status, {}))),
    ).rejects.toMatchObject({ reason });
  });

  it("treats an unreachable titlehub as network and a junk body as import", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    await expect(fetchXboxTitleHistory(SESSION, down)).rejects.toMatchObject({
      reason: "network",
    });
    await expect(
      fetchXboxTitleHistory(SESSION, routes(() => json(200, { nope: true }))),
    ).rejects.toMatchObject({ reason: "import" });
  });
});

// ---------------------------------------------------------------------------
describe("AC: owned titles written with platform attribution, via the GameGPT API", () => {
  it("posts the games to /api/library/xbox and returns the API's summary", async () => {
    const fetchImpl = routes(() => json(200, HISTORY));
    const outcome = await importXboxLibrary({
      db: fakeDb(), session: SESSION, accessToken: "jwt-1", apiUrl: `${API}/`, fetchImpl,
    });

    expect(outcome).toEqual({ status: "imported", summary: SUMMARY });
    const [, init] = vi.mocked(fetchImpl).mock.calls[1];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      titles: [
        { title_id: "2043073184", name: "Halo Infinite" },
        { title_id: "1144039928", name: "Portal 2™" },
      ],
    });
  });

  it("forwards the user's own bearer token to the GameGPT API", async () => {
    // PR #42 review: so the API can check the user once TM11-131 lands.
    const fetchImpl = routes(() => json(200, HISTORY));
    await importXboxLibrary({
      db: fakeDb(), session: SESSION, accessToken: "jwt-1", apiUrl: API, fetchImpl,
    });
    const [, init] = vi.mocked(fetchImpl).mock.calls[1];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-1");
  });

  it("never sends the Xbox token to the GameGPT API", async () => {
    const fetchImpl = routes(() => json(200, HISTORY));
    await importXboxLibrary({ db: fakeDb(), session: SESSION, accessToken: "jwt-1", apiUrl: API, fetchImpl });
    const [, init] = vi.mocked(fetchImpl).mock.calls[1];
    expect(JSON.stringify(init)).not.toContain(SESSION.xstsToken);
  });
});

describe("only the linked Xbox account can be imported", () => {
  it("refuses when this user has no Xbox account linked", async () => {
    const fetchImpl = routes(() => json(200, HISTORY));
    await expect(
      importXboxLibrary({ db: fakeDb({ linkedXuid: null }), session: SESSION, accessToken: "jwt-1", apiUrl: API, fetchImpl }),
    ).resolves.toEqual({ status: "error", reason: "not_linked", httpStatus: 409 });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a sign-in to a different Xbox account than the linked one", async () => {
    const fetchImpl = routes(() => json(200, HISTORY));
    await expect(
      importXboxLibrary({
        db: fakeDb({ linkedXuid: "2533274899999999" }), session: SESSION, accessToken: "jwt-1", apiUrl: API, fetchImpl,
      }),
    ).resolves.toEqual({ status: "error", reason: "mismatch", httpStatus: 409 });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("needs a GameGPT session", async () => {
    await expect(
      importXboxLibrary({
        db: fakeDb({ signedIn: false }), session: SESSION, accessToken: "jwt-1", apiUrl: API,
        fetchImpl: routes(() => json(200, HISTORY)),
      }),
    ).resolves.toMatchObject({ reason: "session", httpStatus: 401 });
  });
});

describe("failures say what happened and save nothing", () => {
  it("passes a private history through as 403", async () => {
    await expect(
      importXboxLibrary({
        db: fakeDb(), session: SESSION, accessToken: "jwt-1", apiUrl: API, fetchImpl: routes(() => json(403, {})),
      }),
    ).resolves.toEqual({ status: "error", reason: "private", httpStatus: 403 });
  });

  it("reports an API failure as import, without its body", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const outcome = await importXboxLibrary({
      db: fakeDb(), session: SESSION, accessToken: "jwt-1", apiUrl: API,
      fetchImpl: routes(() => json(200, HISTORY), () => json(503, { detail: "db down" })),
    });
    expect(outcome).toEqual({ status: "error", reason: "import", httpStatus: 502 });
    expect(JSON.stringify(error.mock.calls)).not.toContain("db down");
    error.mockRestore();
  });

  it("reports a platform_accounts read error as import", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(
      importXboxLibrary({
        db: fakeDb({ readError: true }), session: SESSION, accessToken: "jwt-1", apiUrl: API,
        fetchImpl: routes(() => json(200, HISTORY)),
      }),
    ).resolves.toMatchObject({ reason: "import", httpStatus: 500 });
    error.mockRestore();
  });
});
