// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError, addManualGame, searchGames } from "@/lib/api/client";
import { AddGameModal } from "./AddGameModal";

vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/api/client")>()),
  searchGames: vi.fn(),
  addManualGame: vi.fn(),
}));

const HADES = { game_id: "g-hades", title: "Hades", steam_appid: 1145360 };
const HADES_II = { game_id: "g-hades-2", title: "Hades II", steam_appid: null };

const onAdded = vi.fn();
const onClose = vi.fn();

function renderModal() {
  return render(<AddGameModal open onClose={onClose} onAdded={onAdded} />);
}

async function typeTitle(text: string, user = userEvent.setup()) {
  await user.type(screen.getByRole("combobox", { name: "Title" }), text);
  return user;
}

/**
 * The suggestions, once loaded. Scoped to the listbox: the Platform select's
 * own <option>s are on the page from the start, so a page-wide "option" query
 * would resolve to those before any suggestion arrives.
 */
async function findSuggestions() {
  const list = await screen.findByRole("listbox", { name: "Matching games" });
  return within(list).findAllByRole("option");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(searchGames).mockResolvedValue({ items: [HADES, HADES_II] });
  vi.mocked(addManualGame).mockImplementation(async (platform, gameId) => ({
    game_id: gameId,
    title: gameId === HADES.game_id ? "Hades" : "Hades II",
    platform,
    import_method: "MANUAL",
  }));
});
afterEach(cleanup);

describe("AddGameModal: autocomplete against the games table (TM11-54)", () => {
  it("suggests catalogue games as the user types", async () => {
    renderModal();
    await typeTitle("hades");

    const options = await findSuggestions();
    expect(options.map((o) => o.textContent)).toEqual(["Hades", "Hades II"]);
    // Debounced: one search for the whole word, not one per keystroke.
    expect(searchGames).toHaveBeenCalledTimes(1);
    expect(vi.mocked(searchGames).mock.calls[0][0]).toBe("hades");
  });

  it("doesn't search for a single character", async () => {
    renderModal();
    await typeTitle("h");
    await new Promise((r) => setTimeout(r, 400));
    expect(searchGames).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("says so when nothing matches", async () => {
    vi.mocked(searchGames).mockResolvedValue({ items: [] });
    renderModal();
    await typeTitle("zzzz");
    expect(await screen.findByText(/No games found/)).toBeTruthy();
  });

  it("supports picking with the keyboard", async () => {
    renderModal();
    const user = await typeTitle("hades");
    await findSuggestions();
    await user.keyboard("{ArrowDown}{Enter}");

    expect(screen.getByRole("combobox", { name: "Title" })).toHaveProperty("value", "Hades II");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("only adds a game picked from the suggestions", async () => {
    renderModal();
    const user = await typeTitle("My Homebrew Game");
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    expect(screen.getByText("Pick a game from the suggestions.")).toBeTruthy();
    expect(addManualGame).not.toHaveBeenCalled();
  });
});

describe("AddGameModal: stored against the right platform (TM11-54)", () => {
  it.each([
    ["Epic Games", "epic"],
    ["Xbox", "xbox"],
  ])("adds the picked game on %s", async (label, platform) => {
    renderModal();
    const user = await typeTitle("hades");
    await user.click((await findSuggestions())[0]);
    await user.selectOptions(screen.getByLabelText("Platform"), label);
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(addManualGame).toHaveBeenCalledWith(platform, HADES.game_id);
    expect(onAdded.mock.calls[0][0]).toMatchObject({ platform, import_method: "MANUAL" });
  });

  it("offers only platforms without a library API", () => {
    renderModal();
    const options = Array.from(
      (screen.getByLabelText("Platform") as HTMLSelectElement).options,
    ).map((o) => o.value);
    expect(options).toEqual(["epic", "xbox"]);
  });
});

describe("AddGameModal: duplicate entry prevented (TM11-54)", () => {
  it("says the game is already owned and stays open", async () => {
    vi.mocked(addManualGame).mockRejectedValue(
      new ApiError("POST /api/library/manual failed", 409),
    );
    renderModal();
    const user = await typeTitle("hades");
    await user.click((await findSuggestions())[0]);
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    expect(
      await screen.findByText("That game is already in your library on this platform."),
    ).toBeTruthy();
    expect(onAdded).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for an unexpected failure", async () => {
    vi.mocked(addManualGame).mockRejectedValue(new Error("network down"));
    renderModal();
    const user = await typeTitle("hades");
    await user.click((await findSuggestions())[0]);
    await user.click(screen.getByRole("button", { name: "Add to library" }));

    expect(await screen.findByText("Something went wrong. Nothing was changed.")).toBeTruthy();
  });
});
