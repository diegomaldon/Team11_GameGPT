# TM11-58 ownership check and owned-game filter: real-database check

Run on 2026-10-22 against local Docker `pgvector/pgvector:pg16`, on both database shapes
`DeduplicationService` supports.

**Hosted shape.** Every hosted migration in `supabase/migrations/` (14 files, `20260914…` to
`20261018…`) applied in order. Supabase's `auth` schema, `auth.uid()` and the `anon` /
`authenticated` / `service_role` roles are not in plain Postgres, so minimal stubs for them
were created first. One user with two linked accounts (STEAM and XBOX) and four games:

| Game | Owned on |
|---|---|
| Hades | STEAM, XBOX |
| Stardew Valley | STEAM |
| Celeste | (not owned) |
| Hades II | (not owned; similar title to an owned game) |

**Legacy shape.** A second database built by `python scripts/seed_demo.py` (TM11-88), with
the catalogue embedded via `EMBEDDING_STUB=1 python scripts/embed_games.py`.

## Hosted results

| Call | Result |
|---|---|
| `check_ownership(user, Hades)` | `is_owned=True`, `platforms=('steam', 'xbox')` |
| `check_ownership(user, Stardew Valley)` | `is_owned=True`, `platforms=('steam',)` |
| `check_ownership(user, Celeste)` | `is_owned=False`, `platforms=()` |
| `check_ownership(user, Hades II)` | `is_owned=False`, `platforms=()` |
| `owned_platforms(user, [all four])` | Hades → `('steam', 'xbox')`, Stardew Valley → `('steam',)`; Celeste and Hades II left out. One query, 7.7 ms |
| `filter_owned(user, [Hades, Celeste, Stardew Valley, Hades II])` | `[Celeste, Hades II]`, input order kept |
| `check_ownership(other user, Hades)` | `is_owned=False`: ownership is per user |

This confirms the `owned_games` → `platform_accounts` join runs on the real hosted tables,
types and enum (`platform_type` read back as text and lowercased).

## Legacy results

`DATABASE_URL=…/legacy pytest api/tests/test_seeded_demo_db.py api/tests/test_db_backed.py`:
**12 passed**. That includes `test_dedup_drops_the_seeded_library_from_candidates` and
`test_recommend_and_feedback_work_end_to_end_for_the_demo_user`, which runs `POST /api/recommend`
through `RAGPipeline`, so `filter_owned` runs inside the real request path.

## Offline suite

`pytest api/tests scripts`: **411 passed, 10 skipped** (the skips need a database). The 14
new tests are in `api/tests/test_ownership.py`, named `test_ac01_…`, `test_ac02_…` and
`test_ac03_…`.

## Acceptance criteria

- **AC-01, `checkOwnership` resolves a game across all linked platforms:**
  `DeduplicationService.check_ownership` returns every platform the user owns the game on
  (Hades: Steam and Xbox). A user who owns nothing, another user, and a similar title all
  come back not owned.
- **AC-02, `filterOwnedGames` removes owned titles from any candidate list:**
  `DeduplicationService.filter_owned` (the Python name; `RAGPipeline` already calls it)
  drops every game owned on any platform and keeps the rest in input order. It uses the
  same lookup as the check, so the two can't disagree.
- **AC-03, returns the platforms a title is owned on, for the UI badges:**
  `owned_platforms` and `Ownership.platforms` return lowercase platform names in the web
  library's `PLATFORM_ORDER` (`steam`, `xbox`, `epic`, `playstation`), the values
  `web/lib/library/unified.ts` already renders.

## Not verified here

- **The hosted Supabase project itself.** This check used local Postgres with every hosted
  migration applied, not the hosted project, so it doesn't cover row-level security under
  a real JWT or data that drifted from the migrations.
- **No UI or HTTP endpoint shows the badges yet.** AC-03 is met at the service layer. The
  badge component and any route that exposes `owned_platforms` are separate work.
