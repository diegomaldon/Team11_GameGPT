// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { LibraryItem } from "@/lib/api/types";
import type { OwnedGame } from "@/lib/mock/data";
import { getLibrary } from "@/lib/api/client";
import { useMock } from "@/lib/mock/store";
import LibraryPage from "./page";

vi.mock("@/lib/api/client", () => ({ getLibrary: vi.fn() }));
vi.mock("@/lib/mock/store", () => ({ useMock: vi.fn() }));

const removeGame = vi.fn();

function setup({
  imported = [] as LibraryItem[],
  manual = [] as OwnedGame[],
  hydrated = true,
  fail = false,
} = {}) {
  vi.mocked(useMock).mockReturnValue({
    state: { games: manual },
    hydrated,
    addGame: vi.fn(),
    removeGame,
  } as unknown as ReturnType<typeof useMock>);
  vi.mocked(getLibrary).mockImplementation(() =>
    fail ? Promise.reject(new Error("503")) : Promise.resolve({ items: imported }),
  );
  return render(<LibraryPage />);
}

const rowFor = (title: string) => screen.getByText(title).closest("li")!;

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("Library page: owned titles with per-platform badges", () => {
  it("lists imported and hand-added games in one list", async () => {
    setup({
      imported: [{ title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 129351 }],
      manual: [{ id: "g1", title: "Halo Infinite", platform: "xbox" }],
    });
    const list = await screen.findByRole("list", { name: "Owned games" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(rowFor("Rust")).getByTitle("Steam")).toBeTruthy();
    expect(within(rowFor("Halo Infinite")).getByTitle("Xbox")).toBeTruthy();
  });

  it("shows a game owned on Steam and Xbox once, with both badges", async () => {
    setup({
      imported: [{ title: "Forza Horizon 5", steam_appid: 1551360, platform: "steam", playtime_minutes: 0 }],
      manual: [{ id: "g4", title: "Forza Horizon 5", platform: "xbox" }],
    });
    await screen.findByRole("list", { name: "Owned games" });
    expect(screen.getAllByText("Forza Horizon 5")).toHaveLength(1);
    const row = rowFor("Forza Horizon 5");
    expect(within(row).getByTitle("Steam")).toBeTruthy();
    expect(within(row).getByTitle("Xbox")).toBeTruthy();
  });

  it("shows imported playtime so the user can tell the import is real", async () => {
    setup({
      imported: [
        { title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 129351 },
        { title: "Wallpaper Engine", steam_appid: 431960, platform: "steam", playtime_minutes: 0 },
      ],
    });
    expect(await screen.findByText("2,155 h")).toBeTruthy();
    expect(within(rowFor("Wallpaper Engine")).getByText("Not played yet")).toBeTruthy();
  });

  it("filters by platform, counting a two-platform game under each", async () => {
    setup({
      imported: [
        { title: "Forza Horizon 5", steam_appid: 1551360, platform: "steam", playtime_minutes: 0 },
        { title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 0 },
      ],
      manual: [{ id: "g4", title: "Forza Horizon 5", platform: "xbox" }],
    });
    const xbox = await screen.findByRole("button", { name: /^Xbox/ });
    expect(xbox.textContent).toBe("Xbox1");
    expect(screen.getByRole("button", { name: /^Steam/ }).textContent).toBe("Steam2");

    await userEvent.click(xbox);
    expect(xbox.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("Rust")).toBeNull();
    expect(screen.getByText("Forza Horizon 5")).toBeTruthy();
  });

  it("only offers to remove hand-added copies", async () => {
    setup({
      imported: [{ title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 0 }],
      manual: [{ id: "g1", title: "Halo Infinite", platform: "xbox" }],
    });
    await screen.findByRole("list", { name: "Owned games" });
    expect(within(rowFor("Rust")).queryByRole("button")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Remove Halo Infinite" }));
    expect(removeGame).toHaveBeenCalledWith("g1");
  });
});

describe("Library page: empty state prompts linking a platform", () => {
  it("links to Settings when nothing is owned anywhere", async () => {
    setup();
    expect(await screen.findByText("Your library is empty")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Link a platform" });
    expect(link.getAttribute("href")).toBe("/settings");
    expect(screen.getByRole("button", { name: /Add a game by hand/ })).toBeTruthy();
  });

  it("does not claim the library is empty while it is still loading", () => {
    vi.mocked(useMock).mockReturnValue({
      state: { games: [] },
      hydrated: true,
      addGame: vi.fn(),
      removeGame,
    } as unknown as ReturnType<typeof useMock>);
    vi.mocked(getLibrary).mockReturnValue(new Promise(() => {}));
    render(<LibraryPage />);
    expect(screen.getByText("Loading your library…")).toBeTruthy();
    expect(screen.queryByText("Your library is empty")).toBeNull();
  });

  it("waits for saved hand-added games before deciding the library is empty", async () => {
    setup({ hydrated: false });
    await waitFor(() => expect(getLibrary).toHaveBeenCalled());
    expect(screen.getByText("Loading your library…")).toBeTruthy();
    expect(screen.queryByText("Your library is empty")).toBeNull();
  });

  it("reports a failed load instead of showing the empty state", async () => {
    setup({ fail: true });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Couldn't load your imported games.");
    expect(screen.queryByText("Your library is empty")).toBeNull();
    expect(screen.queryByRole("link", { name: "Link a platform" })).toBeNull();
  });

  it("keeps hand-added games on screen when the import fails, and can retry", async () => {
    setup({ fail: true, manual: [{ id: "g1", title: "Halo Infinite", platform: "xbox" }] });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Games you added by hand are still shown.");
    expect(screen.getByText("Halo Infinite")).toBeTruthy();

    vi.mocked(getLibrary).mockResolvedValue({
      items: [{ title: "Rust", steam_appid: 252490, platform: "steam", playtime_minutes: 0 }],
    });
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Rust")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Library page: renders 1000+ entries without freezing", () => {
  it("shows a 1,500-game library with only a window of rows mounted", async () => {
    const imported = Array.from({ length: 1500 }, (_, i) => ({
      title: `Game ${String(i).padStart(4, "0")}`,
      steam_appid: 10_000 + i,
      platform: "steam",
      playtime_minutes: 0,
    }));
    setup({ imported });
    const list = await screen.findByRole("list", { name: "Owned games" });
    expect(screen.getByRole("button", { name: /^All/ }).textContent).toBe("All1,500");
    const mounted = within(list).getAllByRole("listitem");
    expect(mounted.length).toBeLessThan(40);
    expect(mounted[0].getAttribute("aria-setsize")).toBe("1500");
  });
});
