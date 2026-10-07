# Sprint 4 — Idempotent `owned_games` upsert

Evidence for **TM11-47** (UC05 Refresh Linked Libraries).
Captured 2026-10-06 against `main` at commit `c8241d8`.

> **Re-running a sync must not duplicate a library.**
>
> - **AC-01** `owned_games` rows written with `playtimeMinutes` and `importedAt`.
> - **AC-02** re-running the import leaves the row count unchanged and updates playtime.
> - **AC-03** rows attributed to the correct `platform_account`.

---

## Starting state

Worth recording, because it is not what it looked like from the board. Two of
the three criteria had partial work on an unmerged branch, and one had none at
all anywhere.

| | On `main` | On `origin/TM11-46-steam-owned-games-client` | On `origin/noah/TM11-49-import-progress` |
| --- | --- | --- | --- |
| `playtime_minutes` written | no | **yes** | no |
| `imported_at` written | no | no | no |
| `platform_account_id` written | no | no | no |

`imported_at` existed only as a column default in the hosted schema — nothing in
the repository had ever written to it. `platform_account_id` was written by no
code path on any branch. TM11-46 deferred that work explicitly, in the body of
its own migration:

> "Reconciling the two schemas is a real piece of work: the core table requires
> `platform_account_id` and `game_id` NOT NULL … That is a story of its own, not
> a 3-point client ticket."

This ticket is that story, scoped to `owned_games`.

---

## Acceptance criteria

| Acceptance criterion | Evidence |
| --- | --- |
| **AC-01** rows written with `playtimeMinutes` and `importedAt` | `supabase/migrations/20261006130000_owned_games_attribution.sql` adds `imported_at`; `api/db/repositories.py` → `_UPSERT_OWNED_GAMES_SQL` writes both columns. Tests: `test_upsert_statement_writes_playtime_and_imported_at`, `test_playtime_coercion` (8 cases) |
| | `api/services/library_sync.py` maps Steam's `playtime_forever` into the row — it was being read off the wire and dropped before this ticket. Test: `test_sync_maps_steam_playtime_and_attributes_rows` |
| **AC-02** re-run leaves row count unchanged, updates playtime | `on conflict (user_id, platform, steam_appid) do update set …` with `greatest()` on playtime. Tests: `test_resync_leaves_row_count_unchanged_and_updates_playtime`, `test_resync_never_moves_playtime_backwards`, and `test_owned_games_upsert_is_idempotent_requires_db` against real Postgres |
| **AC-03** rows attributed to the correct `platform_account` | `ensure_platform_account()` resolves the account from the steamID64 **before** the first write; `upsert_owned_games()` carries it. Tests: `test_rows_are_attributed_to_the_linked_account`, `test_upsert_statement_carries_platform_account` |
| | Rows that predate attribution — the five seeded titles in `supabase/seed.sql` — are claimed by the migration's backfill and by `attach_orphan_owned_games()`. Tests: `test_orphan_rows_are_adopted_by_the_linked_account`, `test_seed_path_still_attributes_existing_rows` |

Design write-up, including the per-column rules and what was rejected:
[`docs/library-sync-idempotency.md`](../../../docs/library-sync-idempotency.md).

---

## Verification status

**The acceptance criteria have not been verified against a database.**

`test_owned_games_upsert_is_idempotent_requires_db` is the authoritative
evidence for AC-02, and it *skips* when `DATABASE_URL` is unset or the host is
unreachable — the default state of this repo, and the same constraint that left
TM11-25 and TM11-33 on mock coverage only in Sprint 2.

What is actually demonstrated today:

- Statement-level assertions against the real SQL constant the service executes.
- An in-memory model of that statement's semantics (`FakeOwnedGames`), re-run
  twice to show stable row count and advancing playtime.

That is a model of Postgres, not Postgres. To upgrade this to real evidence:

```bash
export DATABASE_URL='postgresql://…'
npx supabase db push
pytest api/tests/test_owned_games_upsert.py -v
```

and confirm `test_owned_games_upsert_is_idempotent_requires_db` reports
`PASSED`, not `SKIPPED`. A screenshot of that line belongs in this folder.

This is the Sprint 2 standing risk repeating: *"four of seven Sprint 2 stories
were marked Done while unmerged or behind a stub."* Running the DB-backed test
before the Done transition is cheaper than defending the story afterwards.

---

## Known gaps

- **`game_id` resolution is still open.** The core table requires it NOT NULL,
  so sync would have to resolve or create a `games` row per title. That is the
  larger half of TM11-46's deferred debt and remains unticketed.
- **Two Steam accounts owning the same appid** collapse to one row under the
  skeleton schema's `(user_id, platform, steam_appid)` constraint, and the later
  sync's account wins. Pinned by a test rather than fixed; the core schema's
  `unique (platform_account_id, game_id)` does not have this problem.
- **Three branches touch this write path and none are merged.** `TM11-49` adds a
  second write path with its own upsert constant carrying neither playtime nor
  attribution. Whoever merges it should point `import_owned_games` at
  `_UPSERT_OWNED_GAMES_SQL`. See the merge hazard table in
  `docs/library-sync-idempotency.md`.

---

## Changed files

| File | Change |
| --- | --- |
| `supabase/migrations/20261006130000_owned_games_attribution.sql` | new — `imported_at`, `platform_account_id`, index, backfill |
| `api/db/repositories.py` | `_UPSERT_OWNED_GAMES_SQL` constant, `ensure_platform_account()`, `attach_orphan_owned_games()`, `_playtime_minutes()`, reads expose both columns |
| `api/services/library_sync.py` | resolves the account before writing, maps `playtime_forever`, attributes seeded rows |
| `api/models/schemas.py` | `LibraryItem.playtime_minutes`, `LibraryItem.imported_at` |
| `openapi.json` | regenerate with the API running; hand-edited here to match |
| `api/tests/test_owned_games_upsert.py` | new — 15 tests across three layers |
| `docs/library-sync-idempotency.md` | new — design write-up |
