// TM11-78. Fetched game details are kept for the session so the panel opens instantly
// the second time, and Discover can prefetch its picks.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getGame } from "@/lib/api/client";
import { fixtureGetGame } from "@/lib/api/fixtures";
import {
  CACHE_MAX_GAMES,
  CACHE_TTL_MS,
  clearGameCache,
  loadGame,
  peekGame,
  prefetchGames,
} from "./gameDetailCache";

vi.mock("@/lib/api/client", () => ({ getGame: vi.fn() }));

const STARDEW = "11111111-1111-4111-8111-111111111111";
const RUST = "44444444-4444-4444-8444-444444444444";

beforeEach(() => {
  vi.clearAllMocks();
  clearGameCache();
  vi.mocked(getGame).mockImplementation(async (id) => fixtureGetGame(id));
});

describe("a game opened twice", () => {
  it("is fetched once, and the second open reads the cache", async () => {
    await loadGame(STARDEW);
    const again = await loadGame(STARDEW);

    expect(again.title).toBe("Stardew Valley");
    expect(getGame).toHaveBeenCalledTimes(1);
  });

  it("shares one request when opened again before the first answer", async () => {
    await Promise.all([loadGame(STARDEW), loadGame(STARDEW)]);
    expect(getGame).toHaveBeenCalledTimes(1);
  });

  it("can be read synchronously once it has arrived, so the panel skips its skeleton", async () => {
    const pending = loadGame(STARDEW);
    expect(peekGame(STARDEW)).toBeUndefined(); // still loading
    await pending;
    expect(peekGame(STARDEW)?.title).toBe("Stardew Valley");
  });
});

describe("what isn't kept", () => {
  it("a failed read, so Try again really asks the API again", async () => {
    vi.mocked(getGame).mockRejectedValueOnce(new Error("503"));
    await expect(loadGame(STARDEW)).rejects.toThrow("503");

    await loadGame(STARDEW);
    expect(getGame).toHaveBeenCalledTimes(2);
  });

  it(`an entry older than ${CACHE_TTL_MS / 60000} minutes`, async () => {
    await loadGame(STARDEW, 0);
    expect(peekGame(STARDEW, CACHE_TTL_MS + 1)).toBeUndefined();

    await loadGame(STARDEW, CACHE_TTL_MS + 1);
    expect(getGame).toHaveBeenCalledTimes(2);
  });

  it(`more than ${CACHE_MAX_GAMES} games: the oldest goes first`, async () => {
    vi.mocked(getGame).mockImplementation(async (id) => ({ ...fixtureGetGame(STARDEW), game_id: id }));
    for (let i = 0; i <= CACHE_MAX_GAMES; i++) await loadGame(`game-${i}`);

    expect(peekGame("game-0")).toBeUndefined();
    expect(peekGame(`game-${CACHE_MAX_GAMES}`)).toBeDefined();
  });

  it("anything, after a clear (the library changed, so owned_on may be stale)", async () => {
    await loadGame(RUST);
    clearGameCache();
    expect(peekGame(RUST)).toBeUndefined();
  });
});

describe("prefetching", () => {
  it("loads each game once, skipping picks with no catalogue id", async () => {
    prefetchGames([STARDEW, null, RUST, STARDEW, undefined]);
    await vi.waitFor(() => expect(peekGame(RUST)).toBeDefined());

    expect(getGame).toHaveBeenCalledTimes(2);
    expect(peekGame(STARDEW)).toBeDefined();
  });

  it("doesn't throw or leave a rejection unhandled when a read fails", async () => {
    vi.mocked(getGame).mockRejectedValue(new Error("503"));
    expect(() => prefetchGames([STARDEW])).not.toThrow();
    await vi.waitFor(() => expect(getGame).toHaveBeenCalledTimes(1));
    expect(peekGame(STARDEW)).toBeUndefined();
  });
});
