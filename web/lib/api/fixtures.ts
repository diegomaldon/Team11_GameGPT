// Canned responses for fixture mode. See client.ts for how these are used.
//
// Fixture mode lets the frontend run standalone with `npm run dev` and NO API.
// Enable it by setting `NEXT_PUBLIC_USE_FIXTURES=1` in web/.env.local (or the
// shell env). When set, every client call resolves locally instead of hitting
// the network, still simulating the ~1.5s recommend latency.
import type {
  FeedbackRequest,
  LibraryItem,
  LibraryResponse,
  LibrarySyncJob,
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
  markFixtureImported();
  return { synced, source: "seed", total: synced, failed: [] };
}

// ── Fixture library (TM11-50) ──
//
// Empty until a fixture import has run, like a real account before Steam is
// linked, so both the empty state and the imported list can be seen without an
// API. Titles and playtimes are the ones in the recorded Steam fixture
// (api/tests/fixtures/steam/owned_games.json).
//
// NEXT_PUBLIC_FIXTURE_LIBRARY_SIZE pads the list with generated titles, to try
// the library view at 1000+ games by hand.
const IMPORTED_KEY = "gamegpt.fixture.imported";

const FIXTURE_LIBRARY: LibraryItem[] = [
  { title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 129351 },
  { title: "Counter-Strike 2", steam_appid: 730, platform: "steam", playtime_minutes: 72815 },
  {
    title: "The Witcher 3: Wild Hunt \u2014 Remastered",
    steam_appid: 292030,
    platform: "steam",
    playtime_minutes: 13136,
  },
  { title: "Forza Horizon 5", steam_appid: 1551360, platform: "steam", playtime_minutes: 4577 },
  { title: "Rocket League", steam_appid: 252950, platform: "steam", playtime_minutes: 4559 },
  { title: "Firewatch", steam_appid: 383870, platform: "steam", playtime_minutes: 679 },
  { title: "Balatro", steam_appid: 2379780, platform: "steam", playtime_minutes: 671 },
  { title: "Papers, Please", steam_appid: 239030, platform: "steam", playtime_minutes: 139 },
  { title: "Wallpaper Engine", steam_appid: 431960, platform: "steam", playtime_minutes: 0 },
  {
    title: "HITMAN World of Assassination",
    steam_appid: 1659040,
    platform: "steam",
    playtime_minutes: 0,
  },
];

function markFixtureImported(): void {
  try {
    sessionStorage.setItem(IMPORTED_KEY, "1");
  } catch {
    // No storage (private mode, SSR): the list just stays empty on reload.
  }
}

function fixtureImported(): boolean {
  try {
    return sessionStorage.getItem(IMPORTED_KEY) === "1";
  } catch {
    return false;
  }
}

export function fixtureGetLibrary(): LibraryResponse {
  if (!fixtureImported()) return { items: [] };
  const size = Number(process.env.NEXT_PUBLIC_FIXTURE_LIBRARY_SIZE) || 0;
  const padding: LibraryItem[] = [];
  for (let i = FIXTURE_LIBRARY.length; i < size; i++) {
    padding.push({
      title: `Fixture Game ${String(i + 1).padStart(4, "0")}`,
      steam_appid: 9_000_000 + i,
      platform: "steam",
      playtime_minutes: (i * 37) % 600,
    });
  }
  return { items: [...FIXTURE_LIBRARY, ...padding] };
}

// Fixture-mode import job (TM11-49): advances one chunk per poll and includes one
// per-title failure, so the progress bar and the failure list can be seen without an API.
const FIXTURE_TOTAL = 48;
const FIXTURE_CHUNK = 12;
const fixtureJobs = new Map<string, LibrarySyncJob>();

export function fixtureStartSync(steamId: string): LibrarySyncJob {
  const job: LibrarySyncJob = {
    job_id: `fixture-${steamId}-${Date.now()}`,
    state: "fetching",
    total: 0,
    processed: 0,
    synced: 0,
    failed: [],
    source: "seed",
    started_at: new Date().toISOString(),
  };
  fixtureJobs.set(job.job_id, job);
  return { ...job };
}

export function fixtureGetSyncJob(jobId: string): LibrarySyncJob {
  const job = fixtureJobs.get(jobId);
  if (!job) throw new Error(`unknown fixture job ${jobId}`);
  if (job.state === "fetching") {
    Object.assign(job, { state: "importing", total: FIXTURE_TOTAL });
  } else if (job.state === "importing") {
    const processed = Math.min(FIXTURE_TOTAL, (job.processed ?? 0) + FIXTURE_CHUNK);
    const failed =
      processed >= 24
        ? [{ steam_appid: 999999999, title: "Delisted Demo", reason: "invalid appid" }]
        : [];
    Object.assign(job, { processed, failed, synced: processed - failed.length });
    if (processed === FIXTURE_TOTAL) {
      Object.assign(job, { state: "succeeded", finished_at: new Date().toISOString() });
      markFixtureImported();
    }
  }
  return { ...job, failed: [...(job.failed ?? [])] };
}
