import { describe, expect, it } from "vitest";
import { fakeAccountsDb, type StoredAccount } from "./fakeAccountsDb";
import {
  AccountsError,
  disconnectPlatform,
  formatLastSynced,
  linkManualPlatform,
  loadLinkedAccounts,
  markSynced,
  toLinkedAccounts,
} from "./linkedAccounts";

/** TM11-52 (REQ003): linked accounts read from and written to platform_accounts. */

const USER = "user-1";
const NOW = new Date("2026-10-13T20:00:00Z");

const STEAM: StoredAccount = {
  user_id: USER,
  platform: "STEAM",
  platform_user_id: "76561197960287930",
  linked_at: "2026-10-01T12:00:00Z",
  last_synced_at: "2026-10-13T17:00:00Z",
};

describe("toLinkedAccounts: AC1 every platform with its state and lastSyncedAt", () => {
  it("lists Steam, Xbox, Epic and PlayStation in that order", () => {
    expect(toLinkedAccounts([]).map((a) => a.platform)).toEqual([
      "steam",
      "xbox",
      "epic",
      "playstation",
    ]);
  });

  it("marks only platforms with a row as connected, carrying id and sync time", () => {
    const [steam, xbox] = toLinkedAccounts([STEAM]);
    expect(steam).toMatchObject({
      connected: true,
      accountId: "76561197960287930",
      linkedAt: "2026-10-01T12:00:00Z",
      lastSyncedAt: "2026-10-13T17:00:00Z",
    });
    expect(xbox).toMatchObject({ connected: false, accountId: null, lastSyncedAt: null });
  });

  it("AC3 shows nothing connected when the user has no rows", () => {
    expect(toLinkedAccounts([]).every((a) => !a.connected)).toBe(true);
  });

  it("offers a way to connect every platform but PlayStation", () => {
    expect(toLinkedAccounts([]).map((a) => a.connectVia)).toEqual([
      "steam",
      "xbox",
      "manual",
      null,
    ]);
  });

  it("never treats PlayStation as connected, whatever the rows say", () => {
    const rows = [{ ...STEAM, platform: "PLAYSTATION" }];
    expect(toLinkedAccounts(rows).find((a) => a.platform === "playstation")?.connected).toBe(
      false,
    );
  });
});

describe("loadLinkedAccounts: AC3 the page shows what is stored", () => {
  it("reads only the signed-in user's rows", async () => {
    const other = { ...STEAM, user_id: "user-2", platform: "XBOX", platform_user_id: "999" };
    const { db } = fakeAccountsDb(USER, [STEAM, other]);
    const accounts = await loadLinkedAccounts(db);
    expect(accounts.filter((a) => a.connected).map((a) => a.platform)).toEqual(["steam"]);
  });

  it("throws a readable error when the read fails", async () => {
    const fake = fakeAccountsDb(USER);
    fake.fail("select");
    await expect(loadLinkedAccounts(fake.db)).rejects.toThrow(
      "Couldn't load your linked accounts.",
    );
  });
});

describe("disconnectPlatform: AC2 disconnect", () => {
  it("deletes the user's row for that platform only", async () => {
    const xbox = { ...STEAM, platform: "XBOX", platform_user_id: "2533274812345678" };
    const fake = fakeAccountsDb(USER, [STEAM, xbox]);
    await disconnectPlatform(fake.db, USER, "steam");
    expect(fake.rows.map((r) => r.platform)).toEqual(["XBOX"]);
  });

  it("can't delete another user's row", async () => {
    const theirs = { ...STEAM, user_id: "user-2" };
    const fake = fakeAccountsDb(USER, [theirs]);
    await disconnectPlatform(fake.db, USER, "steam");
    expect(fake.rows).toHaveLength(1);
  });

  it("refuses PlayStation, which has no database value", async () => {
    const { db } = fakeAccountsDb(USER);
    await expect(disconnectPlatform(db, USER, "playstation")).rejects.toMatchObject({
      reason: "unsupported",
    });
  });

  it("surfaces a failed delete", async () => {
    const fake = fakeAccountsDb(USER, [STEAM]);
    fake.fail("delete");
    await expect(disconnectPlatform(fake.db, USER, "steam")).rejects.toBeInstanceOf(
      AccountsError,
    );
  });
});

describe("linkManualPlatform: AC2 connect Epic by account name", () => {
  it("inserts an EPIC row recorded as MANUAL", async () => {
    const fake = fakeAccountsDb(USER);
    await linkManualPlatform(fake.db, USER, "epic", "  NinjaGamer_7 ", NOW);
    expect(fake.rows).toEqual([
      {
        user_id: USER,
        platform: "EPIC",
        platform_user_id: "NinjaGamer_7",
        import_method: "MANUAL",
        linked_at: "2026-10-13T20:00:00.000Z",
        last_synced_at: null,
      },
    ]);
  });

  it.each(["", "ab", "a".repeat(33), "bad<name>"])("rejects the name %j", async (name) => {
    const fake = fakeAccountsDb(USER);
    await expect(linkManualPlatform(fake.db, USER, "epic", name)).rejects.toMatchObject({
      reason: "invalid",
    });
    expect(fake.rows).toEqual([]);
  });

  it("reports a name another user already linked as taken", async () => {
    const theirs = { ...STEAM, user_id: "user-2", platform: "EPIC", platform_user_id: "Ninja" };
    const { db } = fakeAccountsDb(USER, [theirs]);
    await expect(linkManualPlatform(db, USER, "epic", "Ninja")).rejects.toMatchObject({
      reason: "taken",
    });
  });
});

describe("markSynced: AC1 lastSyncedAt is recorded", () => {
  it("stamps last_synced_at on the user's row", async () => {
    const fake = fakeAccountsDb(USER, [{ ...STEAM, last_synced_at: null }]);
    await markSynced(fake.db, USER, "steam", NOW);
    expect(fake.rows[0].last_synced_at).toBe("2026-10-13T20:00:00.000Z");
  });
});

describe("formatLastSynced", () => {
  it.each([
    [null, "Never synced"],
    ["not a date", "Never synced"],
    ["2026-10-13T19:59:40Z", "Synced just now"],
    ["2026-10-13T19:55:00Z", "Synced 5 min ago"],
    ["2026-10-13T17:00:00Z", "Synced 3 h ago"],
    ["2026-10-02T09:00:00Z", "Synced Oct 2, 2026"],
  ])("%s -> %s", (iso, expected) => {
    expect(formatLastSynced(iso, NOW)).toBe(expected);
  });
});
