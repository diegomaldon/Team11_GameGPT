// @vitest-environment jsdom

// TM11-52 (REQ003): the linked accounts card, against an in-memory platform_accounts.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeAccountsDb, type StoredAccount } from "@/lib/account/fakeAccountsDb";
import type { AccountsDb } from "@/lib/account/linkedAccounts";
import { useAuth } from "@/lib/auth/session";
import { runLibrarySync } from "@/lib/api/client";
import { LinkedAccountsCard } from "./LinkedAccountsCard";

// accountsDb is read once at import, so the mock forwards to whichever fake is current.
const current = vi.hoisted(() => ({ db: null as unknown as AccountsDb }));
vi.mock("@/lib/supabase", () => ({
  supabase: { from: (table: "platform_accounts") => current.db.from(table) },
}));
vi.mock("@/lib/auth/session", () => ({ useAuth: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ runLibrarySync: vi.fn(() => new Promise(() => {})) }));

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => search.params,
}));

const USER = "user-1";
const STEAM_ID = "76561197960287930";

const XUID = "2533274812345678";

const XBOX: StoredAccount = {
  user_id: USER,
  platform: "XBOX",
  platform_user_id: XUID,
  linked_at: "2026-10-01T12:00:00Z",
  last_synced_at: null,
};

const STEAM: StoredAccount = {
  user_id: USER,
  platform: "STEAM",
  platform_user_id: STEAM_ID,
  linked_at: "2026-10-01T12:00:00Z",
  last_synced_at: null,
};

function setup(seed: StoredAccount[] = []) {
  const fake = fakeAccountsDb(USER, seed);
  current.db = fake.db;
  vi.mocked(useAuth).mockReturnValue({
    status: "authenticated",
    user: { id: USER },
    session: { access_token: "jwt" },
  } as unknown as ReturnType<typeof useAuth>);
  const view = render(<LinkedAccountsCard />);
  return { fake, view };
}

const row = (name: string) =>
  within(screen.getByRole("list", { name: "Platforms" })).getByRole("listitem", { name });

/** Presses the button inside the open dialog, not the row button of the same name. */
const pressInDialog = (name: string) =>
  userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name }));

beforeEach(() => {
  vi.clearAllMocks();
  search.params = new URLSearchParams();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AC1 lists each platform with its state and lastSyncedAt", () => {
  it("shows connected platforms with their id and sync time", async () => {
    setup([{ ...STEAM, last_synced_at: new Date(Date.now() - 5 * 60_000).toISOString() }]);
    await screen.findByRole("list", { name: "Platforms" });
    expect(row("Steam").textContent).toContain(`Connected · ${STEAM_ID}`);
    expect(row("Steam").textContent).toContain("Synced 5 min ago");
    expect(row("Xbox").textContent).toContain("Not connected");
    expect(row("Epic Games").textContent).toContain("Not connected");
  });

  it("says Never synced for a link that has not imported yet", async () => {
    setup([STEAM]);
    await screen.findByRole("list", { name: "Platforms" });
    expect(row("Steam").textContent).toContain("Never synced");
  });

  it("shows PlayStation as not supported, with Connect disabled", async () => {
    setup();
    await screen.findByRole("list", { name: "Platforms" });
    expect(row("PlayStation").textContent).toContain("Not supported yet");
    expect(
      within(row("PlayStation")).getByRole("button", { name: "Connect PlayStation" }),
    ).toHaveProperty("disabled", true);
  });
});

describe("AC2 connect and disconnect per platform", () => {
  it("disconnects after confirmation, warning that imported games go too", async () => {
    const { fake } = setup([STEAM]);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Steam" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain(
      "Games imported through this Steam account will be removed",
    );
    expect(fake.rows).toHaveLength(1);

    await pressInDialog("Disconnect");
    await waitFor(() => expect(row("Steam").textContent).toContain("Not connected"));
    expect(fake.rows).toEqual([]);
    expect(screen.getByRole("status").textContent).toBe("Steam disconnected.");
  });

  it("keeps the account when Disconnect is cancelled", async () => {
    const { fake } = setup([STEAM]);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Steam" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(fake.rows).toHaveLength(1);
    expect(row("Steam").textContent).toContain("Connected");
  });

  it("shows a failed disconnect in the dialog and keeps the account", async () => {
    const { fake } = setup([STEAM]);
    fake.fail("delete");
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Steam" }));
    await pressInDialog("Disconnect");
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn't disconnect");
    expect(fake.rows).toHaveLength(1);
  });

  it("connects Epic by account name", async () => {
    const { fake } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Connect Epic Games" }));
    await userEvent.type(screen.getByLabelText("Epic Games account name"), "NinjaGamer");
    await pressInDialog("Connect");

    await waitFor(() => expect(row("Epic Games").textContent).toContain("Connected · NinjaGamer"));
    expect(fake.rows[0]).toMatchObject({ platform: "EPIC", import_method: "MANUAL" });
  });

  it("sends Steam and Xbox to their sign-in pages", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    setup();
    await userEvent.click(await screen.findByRole("button", { name: "Connect Steam" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect Xbox" }));
    expect(assign).toHaveBeenNthCalledWith(1, "/api/steam/login?next=/settings");
    expect(assign).toHaveBeenNthCalledWith(2, "/api/xbox/login?next=/settings");
  });

  it("finishes a verified Steam sign-in, shows it connected and starts an import", async () => {
    search.params = new URLSearchParams("steam=verified");
    const fetchMock = vi.fn(async () => {
      // The server's half: POST /api/steam/link writes the row.
      current.db.from("platform_accounts").insert({ ...STEAM });
      return new Response(JSON.stringify({ steamId: STEAM_ID }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    setup();

    await waitFor(() => expect(row("Steam").textContent).toContain(`Connected · ${STEAM_ID}`));
    expect(fetchMock).toHaveBeenCalledWith("/api/steam/link", expect.objectContaining({
      method: "POST",
    }));
    expect(runLibrarySync).toHaveBeenCalledWith(STEAM_ID, expect.any(Function), expect.anything());
    expect(replace).toHaveBeenCalledWith("/settings");
  });

  it("explains a Steam account already linked elsewhere", async () => {
    search.params = new URLSearchParams("steam=verified");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ reason: "taken" }), { status: 409 })),
    );
    setup();
    expect((await screen.findByRole("alert")).textContent).toContain(
      "already linked to another GameGPT account",
    );
  });
});

describe("AC3 accurate after a refresh and with zero platforms linked", () => {
  it("shows every platform as not connected, with a prompt, when nothing is linked", async () => {
    setup();
    expect(await screen.findByText(/No platforms linked yet/)).toBeTruthy();
    for (const name of ["Steam", "Xbox", "Epic Games", "PlayStation"]) {
      expect(row(name).textContent).not.toContain("Connected");
    }
  });

  it("re-reads the database on a fresh load, so a disconnect stays disconnected", async () => {
    const { fake, view } = setup([STEAM]);
    await userEvent.click(await screen.findByRole("button", { name: "Disconnect Steam" }));
    await pressInDialog("Disconnect");
    await waitFor(() => expect(fake.rows).toEqual([]));

    // A page refresh: the card mounts again from scratch over the same table.
    view.unmount();
    current.db = fake.db;
    render(<LinkedAccountsCard />);
    expect(await screen.findByText(/No platforms linked yet/)).toBeTruthy();
    expect(row("Steam").textContent).toContain("Not connected");
  });

  it("does not claim zero platforms while still loading", () => {
    setup([STEAM]);
    expect(screen.getByText("Loading linked accounts…")).toBeTruthy();
    expect(screen.queryByText(/No platforms linked yet/)).toBeNull();
  });

  it("reports a failed load instead of showing nothing linked, and can retry", async () => {
    const fake = fakeAccountsDb(USER, [STEAM]);
    fake.fail("select");
    current.db = fake.db;
    vi.mocked(useAuth).mockReturnValue({
      status: "authenticated",
      user: { id: USER },
      session: { access_token: "jwt" },
    } as unknown as ReturnType<typeof useAuth>);
    render(<LinkedAccountsCard />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Couldn't load your linked accounts.");
    expect(screen.queryByText(/No platforms linked yet/)).toBeNull();

    fake.heal();
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(row("Steam").textContent).toContain("Connected"));
  });
});

describe("TM11-56 Xbox library import", () => {
  it("offers Import games on a linked Xbox account and signs in again to run it", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    setup([XBOX]);

    await userEvent.click(await screen.findByRole("button", { name: "Import games" }));

    expect(assign).toHaveBeenCalledWith("/api/xbox/login?next=/settings&intent=import");
  });

  it("does not offer Import games before Xbox is linked", async () => {
    setup();
    await screen.findByRole("button", { name: "Connect Xbox" });
    expect(screen.queryByRole("button", { name: "Import games" })).toBeNull();
  });

  it("runs the import on return, shows the result and stamps the sync time", async () => {
    search.params = new URLSearchParams("xbox=import-ready");
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          total: 2, added: 2, updated: 0, already_owned: 0, matched: 2, unmatched: 0,
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { fake } = setup([XBOX]);

    expect((await screen.findByText("Imported 2 games from Xbox."))).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/xbox/import", expect.objectContaining({
      method: "POST",
    }));
    await waitFor(() => expect(fake.rows[0].last_synced_at).not.toBeNull());
    expect(replace).toHaveBeenCalledWith("/settings");
  });

  it("explains a sign-in to a different Xbox account", async () => {
    search.params = new URLSearchParams("xbox=import-ready");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ reason: "mismatch" }), { status: 409 })),
    );
    const { fake } = setup([XBOX]);

    expect((await screen.findByRole("alert")).textContent).toContain(
      "different Xbox account than the one linked",
    );
    expect(fake.rows[0].last_synced_at).toBeNull();
  });
});
