// Typed fetch client for the GameGPT API.
//
// Base URL comes from NEXT_PUBLIC_API_URL (default http://localhost:8000) — it
// is never hardcoded to a deployed host.
//
// FIXTURE MODE (develop without a running API):
//   Set NEXT_PUBLIC_USE_FIXTURES=1 (e.g. in web/.env.local) and every call
//   below resolves against canned data in fixtures.ts instead of the network.
//   `npm run dev` then works fully standalone. Leave it unset to hit the real
//   API at NEXT_PUBLIC_API_URL.
//
// OBSERVABILITY (TM11-20): every call goes through `request()`, which stamps an
// `x-request-id` and attaches the current Supabase access token. Both exist so a
// server log line can name the user and be traced back to the click that caused
// it. A fetch added outside `request()` silently loses both.
import {
  fixtureFeedback,
  fixtureRecommend,
  fixtureSyncLibrary,
} from "./fixtures";
import { getAccessToken } from "../auth/token";
import { newRequestId, setLastRequestId } from "../observability";
import type {
  FeedbackRequest,
  LibraryResponse,
  LibrarySyncResponse,
  RecommendResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "1";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    /** Quote this in a bug report; it matches a server log line. */
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<TResponse>(
  path: string,
  init: RequestInit = {},
): Promise<TResponse | null> {
  const requestId = newRequestId();
  setLastRequestId(requestId);

  // Read, never subscribe: lib/auth/session.tsx is the only session subscriber
  // and publishes here on every change, including TOKEN_REFRESHED.
  const token = getAccessToken();

  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "x-request-id": requestId,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });

  // Prefer the server's id: on a proxy hop or a retry they can differ, and the
  // one in the logs is the server's.
  setLastRequestId(res.headers.get("x-request-id") ?? requestId);

  if (!res.ok) {
    throw new ApiError(
      `${init.method ?? "GET"} ${path} failed`,
      res.status,
      res.headers.get("x-request-id"),
    );
  }
  return res.status === 204 ? null : ((await res.json()) as TResponse);
}

/** POST /api/recommend — natural-language query in, ranked recommendations out. */
export async function recommend(query: string): Promise<RecommendResponse> {
  if (USE_FIXTURES) {
    await sleep(1500); // mirror the API's real ~1.5s latency
    return fixtureRecommend(query);
  }
  return (await request<RecommendResponse>("/api/recommend", {
    method: "POST",
    body: JSON.stringify({ query }),
  })) as RecommendResponse;
}

/** POST /api/feedback — persist a thumbs up/down. Returns 204 (no body). */
export async function sendFeedback(body: FeedbackRequest): Promise<void> {
  if (USE_FIXTURES) {
    fixtureFeedback(body);
    return;
  }
  await request<void>("/api/feedback", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** GET /api/library — the current user's owned games. */
export async function getLibrary(): Promise<LibraryResponse> {
  if (USE_FIXTURES) {
    return { items: [] };
  }
  return (await request<LibraryResponse>("/api/library")) as LibraryResponse;
}

/** POST /api/library/sync — pull a public Steam library by steamID64. */
export async function syncLibrary(steamId: string): Promise<LibrarySyncResponse> {
  if (USE_FIXTURES) {
    await sleep(600);
    return fixtureSyncLibrary(steamId);
  }
  return (await request<LibrarySyncResponse>("/api/library/sync", {
    method: "POST",
    body: JSON.stringify({ steam_id: steamId }),
  })) as LibrarySyncResponse;
}
