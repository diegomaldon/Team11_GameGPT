// Canned responses for fixture mode. See client.ts for how these are used.
//
// Fixture mode lets the frontend run standalone with `npm run dev` and NO API.
// Enable it by setting `NEXT_PUBLIC_USE_FIXTURES=1` in web/.env.local (or the
// shell env). When set, every client call resolves locally instead of hitting
// the network, still simulating the ~1.5s recommend latency.
import type {
  FeedbackRequest,
  LibrarySyncResponse,
  RecommendResponse,
} from "./types";

// A stable fake query_id so feedback in fixture mode has something to echo.
const FIXTURE_QUERY_ID = "00000000-0000-4000-8000-000000000001";

export function fixtureRecommend(query: string): RecommendResponse {
  return {
    query_id: FIXTURE_QUERY_ID,
    query,
    recommendations: [
      {
        rank: 1,
        game_id: "11111111-1111-4111-8111-111111111111",
        title: "Stardew Valley",
        reason:
          "A relaxed farming sim with no fail state — easy to play with one hand while a podcast runs in the background.",
        steam_appid: 413150,
        review_score: 98,
      },
      {
        rank: 2,
        game_id: "22222222-2222-4222-8222-222222222222",
        title: "Dorfromantik",
        reason:
          "A calm tile-placement puzzler. Quiet, low-stakes, and pauses whenever you need to focus on what you're listening to.",
        steam_appid: 1455840,
        review_score: 96,
      },
      {
        rank: 3,
        game_id: "33333333-3333-4333-8333-333333333333",
        title: "Slay the Spire",
        reason:
          "Turn-based deckbuilding means you set the pace, so it fits comfortably around a podcast without demanding constant attention.",
        steam_appid: 646570,
        review_score: 97,
      },
    ],
  };
}

export function fixtureFeedback(body: FeedbackRequest): void {
  // Best-effort: just log it so the vote is observable during standalone dev.
  console.info("[fixtures] feedback recorded", body);
}

export function fixtureSyncLibrary(steamId: string): LibrarySyncResponse {
  // Deterministic count derived from the id so the UI shows something plausible.
  const synced = 12 + (steamId.length % 7);
  return { synced, source: "seed" };
}
