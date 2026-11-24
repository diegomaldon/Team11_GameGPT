// @vitest-environment jsdom

// TM11-78 (REQ009): the game detail panel. Each describe block is one acceptance
// criterion; AC2 (reachable from cards, library and history) is proven on those pages'
// own tests. The API is mocked with the same canned games fixture mode serves.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, getGame, REQUEST_TIMEOUT_CODE } from "@/lib/api/client";
import { fixtureGetGame } from "@/lib/api/fixtures";
import type { DetailTarget } from "@/lib/discover/gameDetail";
import { GameDetailPanel } from "./GameDetailPanel";

vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  getGame: vi.fn(),
}));
vi.mock("@/components/discover/GameArt", () => ({ GameArt: () => null }));

const STARDEW = "11111111-1111-4111-8111-111111111111";
const FIREWATCH = "55555555-5555-4555-8555-555555555555";
const RUST = "44444444-4444-4444-8444-444444444444";

/** A promise the test resolves itself, to look at the panel mid-fetch. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function open(target: Partial<DetailTarget> & { title: string }) {
  const onClose = vi.fn();
  const view = render(
    <GameDetailPanel target={{ gameId: null, ...target }} onClose={onClose} />,
  );
  return { ...view, onClose };
}

/** The value under a fact's label, e.g. fact("Critic score") -> "89 / 100". */
function fact(label: string) {
  const dt = within(screen.getByRole("dialog")).getByText(label, { selector: "dt" });
  return dt.nextElementSibling!.textContent;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getGame).mockImplementation(async (id) => fixtureGetGame(id));
});
afterEach(cleanup);

describe("AC1: shows description, genre tags, platforms, user and critic scores", () => {
  it("fetches the game by id and shows every field", async () => {
    open({ gameId: STARDEW, title: "Stardew Valley" });
    const dialog = await screen.findByTestId("game-detail");

    expect(getGame).toHaveBeenCalledWith(STARDEW);
    expect(screen.getByRole("dialog", { name: "Stardew Valley" })).toBeTruthy();
    expect(dialog.textContent).toContain("You've inherited your grandfather's old farm plot");
    const chips = within(dialog).getByRole("list", { name: "Genres and tags" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Simulation",
      "RPG",
      "Farming Sim",
      "Cozy",
      "Life Sim",
      "Pixel Graphics",
      "Multiplayer",
    ]);
    expect(fact("Platforms")).toBe("Steam, Xbox");
    expect(fact("User score")).toBe("98% positive");
    expect(fact("Critic score")).toBe("89 / 100");
    expect(fact("Released")).toBe("2016");
    expect(fact("Developer")).toBe("ConcernedApe");
  });

  it("links to a store only from the API's purchase links", async () => {
    open({ gameId: STARDEW, title: "Stardew Valley" });
    const link = await screen.findByRole("link", { name: /view on steam/i });
    expect(link.getAttribute("href")).toBe("https://store.steampowered.com/app/413150");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("says which platforms the player owns it on", async () => {
    open({ gameId: RUST, title: "Rust" });
    await screen.findByTestId("game-detail");
    expect(fact("In your library")).toBe("Steam");
  });

  it("shows why it was recommended when it was", async () => {
    open({ gameId: STARDEW, title: "Stardew Valley", reason: "A calm farm for your evenings." });
    const dialog = await screen.findByTestId("game-detail");
    expect(within(dialog).getByRole("heading", { name: "Why it fits" })).toBeTruthy();
    expect(dialog.textContent).toContain("A calm farm for your evenings.");
  });

  it("holds the panel's shape with a skeleton while the game loads", async () => {
    const pending = deferred<ReturnType<typeof fixtureGetGame>>();
    vi.mocked(getGame).mockReturnValueOnce(pending.promise);
    open({ gameId: STARDEW, title: "Stardew Valley" });

    expect(screen.getByRole("status", { name: "Loading game details…" })).toBeTruthy();
    pending.resolve(fixtureGetGame(STARDEW));
    await screen.findByTestId("game-detail");
    expect(screen.queryByRole("status", { name: "Loading game details…" })).toBeNull();
  });

  it("fetches again when another game is opened in its place", async () => {
    const { rerender, onClose } = open({ gameId: STARDEW, title: "Stardew Valley" });
    await screen.findByTestId("game-detail");

    rerender(<GameDetailPanel target={{ gameId: RUST, title: "Rust" }} onClose={onClose} />);

    await screen.findByRole("dialog", { name: "Rust" });
    expect(await screen.findByText(/brutal multiplayer survival game/)).toBeTruthy();
    expect(getGame).toHaveBeenLastCalledWith(RUST);
  });
});

describe("AC3: missing fields render as unavailable rather than blank or broken", () => {
  it("says Unavailable for each field the game doesn't have", async () => {
    // Firewatch's fixture has no critic score, tags, platforms or store links.
    open({ gameId: FIREWATCH, title: "Firewatch" });
    const dialog = await screen.findByTestId("game-detail");

    expect(fact("Critic score")).toBe("Unavailable");
    expect(fact("Platforms")).toBe("Unavailable");
    expect(fact("User score")).toBe("92% positive"); // what it has still shows
    const stores = within(dialog).getByRole("heading", { name: "Where to buy" }).parentElement!;
    expect(stores.textContent).toContain("Unavailable");
    expect(within(dialog).queryByRole("link")).toBeNull();
  });

  it("shows the same layout, all unavailable, for a game with no catalogue id", async () => {
    open({ gameId: null, title: "Some Unmatched Import" });
    const dialog = await screen.findByTestId("game-detail");

    expect(getGame).not.toHaveBeenCalled();
    expect(dialog.textContent).toContain("isn't in our catalogue yet");
    for (const label of ["User score", "Critic score", "Platforms", "Released", "Developer"]) {
      expect(fact(label)).toBe("Unavailable");
    }
    expect(within(dialog).getByRole("heading", { name: "About" }).parentElement!.textContent).toBe(
      "AboutUnavailable",
    );
  });

  it("treats a game the API doesn't know (404) as missing, not as an error", async () => {
    open({ gameId: "99999999-9999-4999-8999-999999999999", title: "Gone Game" });
    const dialog = await screen.findByTestId("game-detail");

    expect(screen.queryByRole("alert")).toBeNull();
    expect(dialog.textContent).toContain("isn't in our catalogue yet");
    expect(fact("User score")).toBe("Unavailable");
  });

  it("keeps the platforms a card already knew while the rest is unknown", async () => {
    open({ gameId: null, title: "Card Only", platforms: ["xbox", "steam"] });
    await screen.findByTestId("game-detail");
    expect(fact("Platforms")).toBe("Steam, Xbox");
  });

  it("never shows a raw value for a blank field", async () => {
    vi.mocked(getGame).mockResolvedValueOnce({
      ...fixtureGetGame(STARDEW),
      description: null,
      genres: [],
      tags: [],
      release_date: "not-a-date",
      developers: ["  "],
      review_score: null,
    });
    open({ gameId: STARDEW, title: "Stardew Valley" });
    const dialog = await screen.findByTestId("game-detail");

    expect(fact("Released")).toBe("Unavailable");
    expect(fact("Developer")).toBe("Unavailable");
    expect(fact("User score")).toBe("Unavailable");
    expect(dialog.textContent).not.toMatch(/null|undefined|NaN/);
  });
});

describe("When the details can't be read (TM11-77 detail scenario)", () => {
  it("says so with a retry, and the retry loads the game", async () => {
    vi.mocked(getGame).mockRejectedValueOnce(
      new ApiError("GET /api/games/x failed", 503, null, "game_detail_failed"),
    );
    const user = userEvent.setup();
    open({ gameId: STARDEW, title: "Stardew Valley" });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Couldn't load this game's details");
    expect(alert.textContent).not.toContain("game_detail_failed");

    await user.click(within(alert).getByRole("button", { name: "Try again" }));
    await screen.findByTestId("game-detail");
    expect(getGame).toHaveBeenCalledTimes(2);
  });

  it("treats a timeout the same way", async () => {
    vi.mocked(getGame).mockRejectedValueOnce(
      new ApiError("GET /api/games/x timed out", 0, null, REQUEST_TIMEOUT_CODE),
    );
    open({ gameId: STARDEW, title: "Stardew Valley" });
    expect((await screen.findByRole("alert")).textContent).toContain("Try again");
  });
});

it("closes on Escape and on the Close button", async () => {
  const user = userEvent.setup();
  const { onClose } = open({ gameId: STARDEW, title: "Stardew Valley" });
  await screen.findByTestId("game-detail");

  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(2);
});
