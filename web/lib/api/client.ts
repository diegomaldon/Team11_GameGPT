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
import {
  fixtureFeedback,
  fixtureRecommend,
  fixtureSyncLibrary,
} from "./fixtures";
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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function post<TResponse>(path: string, body: unknown): Promise<TResponse> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(`POST ${path} failed`, res.status);
  return res.json() as Promise<TResponse>;
}

/** POST /api/recommend — natural-language query in, ranked recommendations out. */
export async function recommend(query: string): Promise<RecommendResponse> {
  if (USE_FIXTURES) {
    await sleep(1500); // mirror the API's real ~1.5s latency
    return fixtureRecommend(query);
  }
  return post<RecommendResponse>("/api/recommend", { query });
}

/** POST /api/feedback — persist a thumbs up/down. Returns 204 (no body). */
export async function sendFeedback(body: FeedbackRequest): Promise<void> {
  if (USE_FIXTURES) {
    fixtureFeedback(body);
    return;
  }
  const res = await fetch(`${API_URL}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError("POST /api/feedback failed", res.status);
}

/** GET /api/library — the current user's owned games. */
export async function getLibrary(): Promise<LibraryResponse> {
  if (USE_FIXTURES) {
    return { items: [] };
  }
  const res = await fetch(`${API_URL}/api/library`);
  if (!res.ok) throw new ApiError("GET /api/library failed", res.status);
  return res.json() as Promise<LibraryResponse>;
}

/** POST /api/library/sync — pull a public Steam library by steamID64. */
export async function syncLibrary(steamId: string): Promise<LibrarySyncResponse> {
  if (USE_FIXTURES) {
    await sleep(600);
    return fixtureSyncLibrary(steamId);
  }
  return post<LibrarySyncResponse>("/api/library/sync", { steam_id: steamId });
}
