import type { AccountsDb, PlatformAccountRow } from "./linkedAccounts";

/**
 * Test helper: an in-memory platform_accounts table behind the AccountsDb slice. TM11-52.
 *
 * Behaves like the real table seen through RLS: reads return only `userId`'s rows, and the
 * two unique keys (user_id, platform) and (platform, platform_user_id) raise 23505. Rows for
 * other users can be seeded to exercise "already linked elsewhere".
 */

export type StoredAccount = PlatformAccountRow & { user_id: string; import_method?: string };

type DbError = { code?: string; message?: string };
type Filtered = ReturnType<ReturnType<AccountsDb["from"]>["delete"]>;

export function fakeAccountsDb(userId: string, seed: StoredAccount[] = []) {
  const rows: StoredAccount[] = seed.map((r) => ({ ...r }));
  const failures = new Map<string, DbError>();

  const mine = () =>
    rows
      .filter((r) => r.user_id === userId)
      .map(({ platform, platform_user_id, linked_at, last_synced_at }) => ({
        platform,
        platform_user_id,
        linked_at,
        last_synced_at,
      }));

  const result = <T,>(op: string, data: T | null = null) =>
    Promise.resolve<{ data: T | null; error: DbError | null }>(
      failures.has(op) ? { data: null, error: failures.get(op)! } : { data, error: null },
    );

  /** A builder that collects .eq() filters and applies `run` to matching rows when awaited. */
  function filtered(op: string, run: (row: StoredAccount) => void): Filtered {
    const filters: [string, string][] = [];
    const builder: Filtered = {
      eq(column, value) {
        filters.push([column, value]);
        return builder;
      },
      then(onFulfilled, onRejected) {
        if (!failures.has(op)) {
          // RLS: a write only ever touches the caller's rows.
          const hits = rows.filter(
            (r) =>
              r.user_id === userId &&
              filters.every(([c, v]) => (r as Record<string, unknown>)[c] === v),
          );
          hits.forEach(run);
        }
        return result<unknown>(op).then(onFulfilled, onRejected);
      },
    };
    return builder;
  }

  const db: AccountsDb = {
    from: () => ({
      select: () => result("select", mine()),
      insert: (row) => {
        const r = row as StoredAccount;
        const clash = rows.some(
          (x) =>
            (x.user_id === r.user_id && x.platform === r.platform) ||
            (x.platform === r.platform && x.platform_user_id === r.platform_user_id),
        );
        if (!failures.has("insert") && clash) {
          return Promise.resolve({ data: null, error: { code: "23505", message: "duplicate" } });
        }
        if (!failures.has("insert")) {
          rows.push({
            ...r,
            linked_at: r.linked_at ?? null,
            last_synced_at: r.last_synced_at ?? null,
          });
        }
        return result("insert");
      },
      update: (patch) => filtered("update", (r) => Object.assign(r, patch)),
      delete: () => filtered("delete", (r) => rows.splice(rows.indexOf(r), 1)),
    }),
  };

  return {
    db,
    rows,
    /** Make every later `op` call fail with `error`. */
    fail(op: "select" | "insert" | "update" | "delete", error: DbError = { message: "boom" }) {
      failures.set(op, error);
    },
    heal() {
      failures.clear();
    },
  };
}
