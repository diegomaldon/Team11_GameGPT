# Idempotent `owned_games` upsert

Why re-running a library sync updates the user's library instead of duplicating
it, and what the write path does with playtime and platform attribution.

Ticket: **TM11-XX** · UC05 Refresh Linked Libraries · E4 Platform Linking & Library Sync

Related: [`docs/steam-library.md`](steam-library.md) (TM11-46, the client that
fetches the data), [`docs/account-deletion.md`](account-deletion.md) (the
cascade that `platform_account_id` participates in).

---

## The statement

One statement writes `owned_games`, and it lives as a module constant in
[`api/db/repositories.py`](../api/db/repositories.py) rather than inline:

```sql
insert into owned_games
    (user_id, platform, platform_account_id, steam_appid, title,
     playtime_minutes, imported_at)
values (%s, %s, %s, %s, %s, %s, now())
on conflict (user_id, platform, steam_appid) do update set
    title               = coalesce(excluded.title, owned_games.title),
    platform_account_id = coalesce(excluded.platform_account_id,
                                   owned_games.platform_account_id),
    playtime_minutes    = greatest(excluded.playtime_minutes,
                                   owned_games.playtime_minutes),
    imported_at         = now()
```

It is a constant so there is exactly one place the rule is defined, and so the
tests can assert against the same string the service runs instead of a copy
that drifts. That matters more than usual here — see
[Merge hazard](#merge-hazard) below.

### Per-column rules, and why

| Column | Rule | Reason |
| --- | --- | --- |
| conflict target | `(user_id, platform, steam_appid)` | The unique constraint declared in `0001_init.sql`. It is what makes a re-sync update in place, so the row count is stable across any number of runs. |
| `title` | `coalesce` | A sync that cannot name a title should not erase one already stored. |
| `platform_account_id` | `coalesce` | The keyless offline fallback has no account to name. A plain assignment would detach rows a real sync had already attributed correctly. |
| `playtime_minutes` | `greatest` | Steam's `playtime_forever` is cumulative and never decreases, so a re-sync should move playtime forward and never backward. It also means the 0-minute fallback rows cannot zero out real hours. |
| `imported_at` | `now()`, unconditional | "When did a sync last see this row" is only true if it moves on *every* run, including runs that change nothing else. |

`do nothing` was considered and rejected for the conflict action. It keeps the
row count stable — satisfying half of AC-02 — while silently never updating
playtime, which fails the other half. There is a test pinning this
(`test_upsert_statement_is_idempotent_on_the_unique_constraint`).

### The cost of `greatest`

A genuine downward correction to playtime will not take. Steam has no mechanism
to reduce `playtime_forever`, so this is not reachable today, but it is a real
constraint rather than an oversight: if a future non-Steam importer needs to
correct a figure downward, it needs its own statement or an explicit override.

---

## Attribution

`platform_accounts` is resolved from the steamID64 **before** any row is
written, by `ensure_platform_account()`. The ordering is not incidental: the
steamID64 is the only thing that identifies which library the rows came from,
and once the upsert has run that information is gone.

```
POST /api/library/sync { steam_id }
        │
        ├─ ensure_platform_account(user, 'steam', steam_id) ──► platform_account_id
        │     insert … on conflict … do update set external_id = excluded.external_id
        │     returning id
        │
        ├─ live key?  ─ yes ─► GetOwnedGames ─► upsert_owned_games(…, platform_account_id)
        │
        └─ no key ─► rows already seeded? ─► attach_orphan_owned_games(…)
                                  └─ no ──► upsert fallback rows (attributed)
```

`do update set external_id = excluded.external_id` is a deliberate no-op write.
`do nothing` would skip the row on conflict and `RETURNING` would hand back zero
rows — which is exactly the common case, a user re-syncing an account they
already linked.

### Rows that predate attribution

The five seeded titles in `supabase/seed.sql`, and anything written before this
ticket, carry no account. Two things close that gap:

- **The migration backfills** where the answer is unambiguous: the user has
  exactly one linked account on that platform. Where a user has two Steam
  accounts linked, which library a pre-attribution row came from is genuinely
  unknown, so those rows are left null rather than guessed at.
- **`attach_orphan_owned_games()`** claims the remaining null rows for the
  account on the next sync. It only touches rows where `platform_account_id is
  null`, so it can never move a row from one account to another.

---

## The two schemas

This ticket is the `owned_games` half of a reconciliation that TM11-46 deferred
by name:

> "Reconciling the two schemas is a real piece of work: the core table requires
> `platform_account_id` and `game_id` NOT NULL … That is a story of its own, not
> a 3-point client ticket."

| | `0001_init.sql` | `20260915120200_create_core_tables.sql` |
| --- | --- | --- |
| Shape | `id, user_id, game_id, platform, steam_appid, title, created_at` | `owned_game_id, user_id, platform_account_id, game_id, playtime_minutes, imported_at, …` |
| Used by | `api/db/repositories.py` — dev box, CI | the hosted Supabase project |

`20261006130000_owned_games_attribution.sql` is written to be correct against
both: a no-op on the hosted project where both columns already exist, and an
add-column on a database built from `0001_init.sql`. The `platform_accounts`
primary key is named differently in each (`id` vs `platform_account_id`), so the
foreign key is resolved from the catalog at runtime rather than hardcoded.

`platform_account_id` is added **nullable** even though the core table declares
it NOT NULL. A NOT NULL add-column against the already-populated skeleton table
would fail outright. The backfill closes what it can; the write path always
supplies an id.

### Still not reconciled

`game_id` resolution. The core table requires it NOT NULL, which means sync
would have to resolve or create a `games` row per title before inserting. That
remains open and is the larger half of the original debt.

---

## Known limits

- **Two Steam accounts, one appid.** A title owned on both linked accounts
  collapses to a single row under `(user_id, platform, steam_appid)`, and the
  later sync's account wins. This is a property of the skeleton schema's unique
  constraint, not of this change. There is a test pinning the behaviour
  (`test_two_steam_accounts_do_not_claim_each_others_rows`) so it is recorded
  rather than discovered later. The core schema's
  `unique (platform_account_id, game_id)` does not have this problem, which is
  one more argument for finishing the reconciliation.
- **`created_at` vs `imported_at`.** Both are kept and they mean different
  things: when the row first appeared, versus when a sync last touched it.
  "Owned since" and "last seen in a sync" are different questions and UC05
  needs the second one.

---

## Verification status

Three layers of test, in `api/tests/test_owned_games_upsert.py`:

1. **Statement tests** — assert the real SQL constant names the right columns
   and conflict target. Proves the write path intends the right thing.
2. **Semantics model** — `FakeOwnedGames` models what Postgres does with that
   one statement. Demonstrates AC-02 end to end with no database. This tests
   the model as much as the code, and is only meaningful because layer 1 pins
   the statement it models.
3. **`test_owned_games_upsert_is_idempotent_requires_db`** — the real statement
   against real Postgres. **This is the authoritative evidence.**

> **A skip is not a pass.** Layer 3 skips when `DATABASE_URL` is unset or the
> host is unreachable, which is the default state of this repo — the same
> constraint that left TM11-25 and TM11-33 covered by mock tests only in
> Sprint 2. A green suite does not mean AC-02 was verified against a database.
> Check whether that test skipped before moving the story to Done.

To run it for real:

```bash
export DATABASE_URL='postgresql://…'
npx supabase db push          # applies 20261006130000_…
pytest api/tests/test_owned_games_upsert.py -v
```

---

## Merge hazard

Three branches touch this write path and none of them are merged:

| Branch | What it does to the upsert |
| --- | --- |
| `origin/TM11-46-steam-owned-games-client` | adds `playtime_minutes` to the inline statement |
| `origin/noah/TM11-49-import-progress` | adds a **second** write path, `import_owned_games`, with its own private `_OWNED_UPSERT` constant carrying neither playtime nor attribution |
| this ticket (`main`) | consolidates to one `_UPSERT_OWNED_GAMES_SQL` constant with all three |

If all three land without coordination there will be three copies of the upsert
rule, two of them silently wrong. **Whoever merges TM11-49 should point
`import_owned_games` at `_UPSERT_OWNED_GAMES_SQL`** rather than keeping
`_OWNED_UPSERT`. TM11-46's playtime change becomes redundant on merge and should
resolve in favour of the constant.
