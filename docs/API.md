# GameGPT — API Reference

Base URL (local): `http://localhost:8000`. All endpoints are under `/api`.
The machine-readable contract is [`openapi.json`](../openapi.json) at the repo
root (also served at `/openapi.json`, with interactive docs at `/docs`).

Request/response models are defined in `api/models/schemas.py`. There is **no
auth** — every request acts as the single seeded dev user (`DEV_USER_ID`).
The web client sends `Authorization: Bearer <Supabase token>` when signed in;
the API only logs its unverified `sub` and never uses it to decide access.

`openapi.json` is generated, never hand-edited. After changing a route or a
model, run `python scripts/export_openapi.py` and update this file in the same
pull request. CI fails when `openapi.json` doesn't match the app or a route
isn't documented here (`api/tests/test_api_contract.py`).

## Contracts for the frontend

What the web app builds against (TM11-21). A **planned** contract is agreed
but not served yet, so the frontend can build against a fixture first. When the
route ships, its section loses the `(planned)` marker; CI fails if a planned
route is served, or a served route has no section.

| Area | Endpoint | Status |
|------|----------|--------|
| Library | [`GET /api/library`](#get-apilibrary) | live |
| Library | [`POST /api/library/sync`](#post-apilibrarysync), [`POST /api/library/sync/jobs`](#post-apilibrarysyncjobs), [`GET /api/library/sync/jobs/{job_id}`](#get-apilibrarysyncjobsjob_id) | live |
| Library | [`POST /api/library/csv/preview`](#post-apilibrarycsvpreview), [`POST /api/library/csv/commit`](#post-apilibrarycsvcommit), [`POST /api/library/manual`](#post-apilibrarymanual), [`POST /api/library/xbox`](#post-apilibraryxbox) | live |
| Search | [`GET /api/games/search`](#get-apigamessearch): title autocomplete | live |
| Search | `POST /api/search`: semantic search (TM11-42) | in review, [PR #45](https://github.com/diegomaldon/Team11_GameGPT/pull/45) |
| Search | [`POST /api/recommend`](#post-apirecommend): ranked recommendations with reasons | live |
| Detail | [`GET /api/games/{game_id}`](#get-apigamesgame_id-planned): one game's detail panel | planned (TM11-78, TM11-79) |
| All | [Errors](#errors): the four error shapes and every error code | live |

## Conventions

- Content type is `application/json`.
- UUIDs are strings; `review_score` is a float in `0..1`. Optional fields are
  sent as `null`, not left out.
- Every response carries an `x-request-id` header. The client may send its own
  (at most 64 characters are kept), so a browser error and the request behind it
  share one id. Quote it in bug reports; it matches a server log line.
- Errors are described in [Errors](#errors).

## Errors

Every error response is JSON. Read `detail.error` and `detail.message` when
`detail` is an object, and treat anything else as an unexpected failure.

**1. Handled errors** (every `4xx`/`5xx` a route raises on purpose):
```json
{ "detail": { "error": "already_owned", "message": "That game is already in your library on this platform." } }
```
| Field | Notes |
|-------|-------|
| `detail.error` | stable `snake_case` code. Branch on this, not on `message` |
| `detail.message` | written for users, safe to show as is. Never contains an id, key, URL, stack trace or the uploaded file's contents |

**2. Request validation** (`422`, FastAPI's own shape). `detail` is a list:
```json
{ "detail": [ { "type": "missing", "loc": ["body", "query"], "msg": "Field required", "input": {} } ] }
```
`loc` names the bad field. `msg` is developer text, not for users. Some `422`s
are handled errors instead (shape 1), such as `file_too_large` on CSV upload, so
check whether `detail` is an object or a list.

**3. Unknown route or method** (`404`, `405`, FastAPI's own shape):
```json
{ "detail": "Not Found" }
```

**4. Unexpected server error** (`500`). The body is **not** under `detail`:
```json
{ "error": "internal_error", "message": "Something went wrong. Quote this id if you report it.", "request_id": "9306dd18ef6f4939858b7e66f40d9c55" }
```
The cause is reported to the error sink and never sent to the client.

**Error codes**

| Status | `error` | Endpoint | When |
|--------|---------|----------|------|
| 403 | `steam_profile_private` | `/api/library/sync` | the Steam profile or its game details aren't public |
| 404 | `job_not_found` | `/api/library/sync/jobs/{job_id}` | unknown id, or another user's job |
| 404 | `game_not_found` | `/api/library/manual` | `game_id` isn't in the catalogue |
| 409 | `already_owned` | `/api/library/manual` | already in the library on this platform |
| 413 | `request_too_large` | any | body over 4 MB |
| 422 | `steam_invalid_id` | `/api/library/sync` | not a steamID64 Steam recognises |
| 422 | `file_too_large`, `too_many_rows`, `empty_file`, `no_rows`, `not_text`, `missing_title_column`, `duplicate_column`, `malformed_csv`, `review_mismatch` | `/api/library/csv/*` | see [CSV errors](#post-apilibrarycsvcommit) |
| 500 | `internal_error` | any | an unexpected failure (shape 4) |
| 502 | `recommendation_failed` | `/api/recommend` | the pipeline or LLM failed |
| 502 | `steam_request_rejected` | `/api/library/sync` | Steam refused the request (for example a bad API key) |
| 502 | `sync_failed` | `/api/library/sync` | any other sync failure; nothing was committed |
| 503 | `db_unavailable` | `/api/recommend`, `/api/feedback`, `/api/library` | the database read or write failed |
| 503 | `steam_unavailable` | `/api/library/sync` | Steam isn't responding; retry later |
| 503 | `csv_import_failed` | `/api/library/csv/*` | anything else; the cause is only logged |
| 503 | `search_failed` | `/api/games/search` | anything else; the cause is only logged |
| 503 | `manual_import_failed` | `/api/library/manual` | anything else; the cause is only logged |
| 503 | `import_failed` | `/api/library/xbox` | the write failed; nothing changed |

A background sync (`/api/library/sync/jobs`) never fails its HTTP request for
these. It reports them in the job instead, as `state: "failed"` with the same
code in `error_code` and the message in `error`.

---

## `GET /api/health`

Liveness check; also the Render health-check path.

**200**
```json
{ "status": "ok", "commit": "48bf46f" }
```
`commit` is the deployed git SHA (`GIT_COMMIT` / `RENDER_GIT_COMMIT`), or `"dev"`.

---

## `POST /api/recommend`

Run the RAG slice: embed → vector top-k → drop owned → rank → persist.

**Request**
```json
{ "query": "a chill game I can play while listening to a podcast" }
```
| Field | Type | Notes |
|-------|------|-------|
| `query` | string | 1–500 chars, required |

**200**
```json
{
  "query_id": "5eee89fc-1c2a-4f3b-9a1e-8b0c7d2e5f10",
  "query": "a chill game I can play while listening to a podcast",
  "recommendations": [
    {
      "rank": 1,
      "game_id": "ad9134d9-a3ae-4417-a1c2-381ef709f7ff",
      "title": "My Time at Portia",
      "reason": "Cozy, low-stress crafting and management loops you can half-watch…",
      "steam_appid": 666140,
      "review_score": 0.9
    }
  ]
}
```
| Field | Type | Notes |
|-------|------|-------|
| `query_id` | uuid | Persisted `queries.id` — echo it back in feedback |
| `recommendations[]` | array | 3 items; `rank` 1..n; `reason` never empty |

- Persists one `queries` row and its `recommendations` rows before returning.
- Latency: ~7s on the first call after boot (model warm-up), then dominated by
  LLM latency; **< 10 s** warm.
- **502** `recommendation_failed` if the pipeline errors; **503** `db_unavailable`
  if persistence fails.

**Example**
```bash
curl -s -X POST http://localhost:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"query":"hard roguelike with tight controls"}'
```

---

## `POST /api/feedback`

Persist a thumbs up/down. Stored only — does not affect ranking in the skeleton.

**Request**
```json
{
  "query_id": "5eee89fc-1c2a-4f3b-9a1e-8b0c7d2e5f10",
  "game_id": "ad9134d9-a3ae-4417-a1c2-381ef709f7ff",
  "title": "My Time at Portia",
  "rank": 1,
  "vote": "down"
}
```
| Field | Type | Notes |
|-------|------|-------|
| `query_id` | uuid | required |
| `game_id` | uuid \| null | optional |
| `title` | string | required (denormalized) |
| `rank` | int \| null | optional |
| `vote` | `"up"` \| `"down"` | required |

**204** No Content. **503** `db_unavailable` on persistence failure.

---

## `GET /api/library`

The dev user's owned games (dedup source for recommendations).

Returns the whole library, most played first, with no paging or filter
parameters. The web library view sorts and searches it client-side (TM11-51,
see `docs/FRONTEND.md`).

**200**
```json
{
  "items": [
    { "game_id": "7b0d…", "title": "Hades", "steam_appid": 1145360, "platform": "steam", "playtime_minutes": 3120 },
    { "game_id": null, "title": "Celeste", "steam_appid": 504230, "platform": "epic", "playtime_minutes": 0 }
  ]
}
```
| Field | Type | Notes |
|-------|------|-------|
| `items[].game_id` | uuid \| null | the catalogue game; `null` when the title didn't match one |
| `items[].title` | string | the title as imported |
| `items[].steam_appid` | int \| null | |
| `items[].platform` | string | lowercase: `steam`, `xbox` or `epic` |
| `items[].playtime_minutes` | int | `0` when the platform doesn't report playtime |

Sorted by `playtime_minutes` descending, then `title`. The same game owned on
two platforms is two items.

- **503** `db_unavailable` if the library can't be read.

---

## `POST /api/library/sync`

Import a public Steam library by steamID64.

**Request**
```json
{ "steam_id": "76561197960287930" }
```

**200**
```json
{ "synced": 498, "source": "steam", "total": 500,
  "failed": [{ "steam_appid": 7, "title": "Broken Game", "reason": "DataError: integer out of range" }] }
```
| Field | Type | Notes |
|-------|------|-------|
| `synced` | int | rows upserted / counted |
| `source` | `"steam"` \| `"seed"` | `"steam"` = real API call; `"seed"` = no-key fallback |
| `total` | int | titles the source returned (`synced` + `failed`) |
| `failed` | `SyncFailure[]` | per-title failures (TM11-49); they do not abort the run |
| `import_id` | uuid \| null | `library_imports` row for this run |
| `matched` | int \| null | imported titles joined to a `games` row |
| `unmatched` | int \| null | titles with no `games` row, queued in `unmatched_import_titles` |
| `match_rate` | float \| null | `matched / total`, 0..1 |

The four matching fields are `null` when no import ran (seed path reusing rows
already in `owned_games`). `LibrarySyncJob` carries the same four fields.

**Title matching** (`api/services/title_matching.py`). Each imported title is
matched against `games`, trying these in order:
`appid` (steam_appid) → `exact` title → `normalised` title (case, punctuation,
™/®/©, accents and `&`/"and" folded) → `edition` (suffixes such as
"Game of the Year Edition" or "- Deluxe Edition" removed, matched to the base
game). A tier that hits more than one row is recorded as `ambiguous`, not
guessed. Unmatched titles are kept in `owned_games` with a NULL `game_id`.
They are also upserted into `unmatched_import_titles` (`status = 'pending'`)
for review.

- With `STEAM_API_KEY` set: calls `IPlayerService/GetOwnedGames`, upserts
  `owned_games`, returns `source: "steam"`.
- Without a key: reuses seeded `owned_games`, else a small built-in fallback set,
  returns `source: "seed"`.
- The import is one transaction. A bad title is skipped and listed in `failed`,
  but if the run itself fails (Steam error, DB connection lost) nothing is
  committed and the previous library is unchanged.
- `steam_id` is 1–32 characters.
- **Errors:** **403** `steam_profile_private`, **422** `steam_invalid_id`,
  **502** `steam_request_rejected` or `sync_failed`, **503** `steam_unavailable`.
  See [Error codes](#errors). Nothing is committed on any of them.

---

## `POST /api/library/sync/jobs`

Same import as `POST /api/library/sync`, but run in the background so the UI
can show progress (TM11-49). If the user already has an import running, that
job is returned instead of starting a second one.

**Request:** same as `/api/library/sync`.

**202:** a `LibrarySyncJob` (below), normally in state `queued`.

## `GET /api/library/sync/jobs/{job_id}`

Poll an import. The web client polls every 750 ms (`runLibrarySync` in
`web/lib/api/client.ts`).

**200**
```json
{
  "job_id": "02373f58-8e02-4207-af0b-6ce6ee6cef44",
  "state": "importing",
  "total": 500, "processed": 150, "synced": 149,
  "failed": [{ "steam_appid": 7, "title": "Broken Game", "reason": "DataError: integer out of range" }],
  "source": "steam", "error": null, "error_code": null,
  "import_id": null, "matched": null, "unmatched": null, "match_rate": null,
  "started_at": "2026-10-06T14:31:37Z", "finished_at": null
}
```
`error_code` is set with `error` when the job fails: one of the Steam codes in
[Error codes](#errors), or `sync_failed`. The four matching fields are `null`
until the import has matched the titles, then mean the same as in
`POST /api/library/sync`.

| `state` | Meaning |
|---------|---------|
| `queued` | accepted, not started |
| `fetching` | waiting on the Steam API (`total` is still 0) |
| `importing` | writing `owned_games`; `processed` goes up by one chunk (50 titles) at a time |
| `succeeded` | committed; there may still be per-title entries in `failed` |
| `failed` | rolled back, so the previous library is unchanged; `error` is a safe user-facing message (the cause is only logged) |

- **404** `job_not_found`: unknown id, or another user's job.
- Jobs live in the API process's memory, so a restart forgets them. The client
  treats a 404 mid-poll as "lost track". An import that was cut off by a restart
  never committed.

---

## `POST /api/library/csv/preview`

Review a library CSV before anything is saved (TM11-55, REQ004). For platforms
with no library API (Epic, Xbox), or any list the user keeps themselves.

The browser reads the file and sends its text; the server checks everything.

**Request**
```json
{ "platform": "epic", "csv_text": "title,steam_appid\nHades,1145360\nCeleste,\n" }
```
| Field | Type | Notes |
|-------|------|-------|
| `platform` | `"xbox"` \| `"epic"` | every row is owned on this platform. Steam uses `POST /api/library/sync` |
| `csv_text` | string | the whole file, at most 1 MB |

**File format.** Comma-separated, UTF-8, header row first. A `title` column is
required; `steam_appid` is optional; other columns are ignored. At most 2,000
games and 200 characters per title.

**200** (nothing written)
```json
{
  "platform": "epic",
  "rows": [
    { "row_number": 2, "title": "Hades", "status": "matched",
      "game_id": "7b0d…", "game_title": "Hades", "message": null },
    { "row_number": 3, "title": "Celeste?", "status": "unmatched",
      "game_id": null, "game_title": null,
      "message": "No game found with this title. Saved for review." }
  ],
  "matched": 1, "needs_review": 1, "skipped": 0
}
```
| `status` | Meaning |
|----------|---------|
| `matched` | will be added on commit |
| `already_owned` | already in the library on this platform; skipped |
| `duplicate` | same game or title as an earlier row; skipped |
| `ambiguous` | matches several games; goes to the review queue |
| `unmatched` | no game found; goes to the review queue |
| `invalid` | the row itself is bad (empty or overlong title, bad `steam_appid`); `message` says why |

`row_number` is the spreadsheet row (the header is row 1). Matching is the same
as for Steam imports (see Title matching above).

## `POST /api/library/csv/commit`

Add the matched rows the user kept.

**Request:** the preview body plus the rows the user unticked.
```json
{ "platform": "epic", "csv_text": "title,steam_appid\nHades,1145360\nCeleste,\n",
  "excluded_rows": [3] }
```

**200**
```json
{ "added": 1, "needs_review": 0, "skipped": 1, "import_id": "5c1e…" }
```
| Field | Notes |
|-------|-------|
| `added` | games newly added to `owned_games` |
| `needs_review` | ambiguous and unmatched rows written to `unmatched_import_titles` |
| `skipped` | unticked, already owned, duplicate and invalid rows |
| `import_id` | `library_imports` row (`source = 'csv'`); `null` if only the report failed to save |

The server runs the whole review again on `csv_text`, so the commit adds exactly
what a preview of the same file would have shown as `matched`. The client can
only leave rows out. A game already owned is never added twice, even when two
uploads race (`owned_games_user_platform_manual_game_key`).

**Errors (both routes)**
| Status | `error` | When |
|--------|---------|------|
| 413 | `request_too_large` | body over 4 MB (any route) |
| 422 | `file_too_large`, `too_many_rows` | over 1 MB or 2,000 games |
| 422 | `empty_file`, `no_rows`, `not_text` | nothing to read, or a binary file |
| 422 | `missing_title_column`, `duplicate_column`, `malformed_csv` | bad header or broken quoting |
| 422 | `review_mismatch` | `excluded_rows` names a row the file doesn't have |
| 503 | `csv_import_failed` | anything else; the cause is only logged |

`message` is always safe to show and never repeats the file's contents. Logs
carry counts only, never titles.

---

## `GET /api/games/search`

Catalogue games for the Add game autocomplete (TM11-54, REQ004). Writes nothing.

| Query | Type | Notes |
|-------|------|-------|
| `q` | string, required | part of a title, at most 100 characters; under 2 characters (after trimming) returns no items |
| `limit` | integer | 1–20, default 8 |

**200**
```json
{ "items": [
  { "game_id": "7b0d…", "title": "Hades", "steam_appid": 1145360 },
  { "game_id": "a41c…", "title": "Hades II", "steam_appid": null }
] }
```
Case-insensitive substring match on `games.title`. Titles that start with `q`
come first, then shorter titles. `%` and `_` are matched literally.

- **422**: `q` missing or too long, `limit` out of range.
- **503** `search_failed`: anything else; the cause is only logged.

## `GET /api/games/{game_id}` (planned)

**Not served yet.** The contract for the game detail panel (REQ009, use case
2.20), agreed so TM11-78 (layout) and TM11-79 (data wiring) can build against a
fixture first. Every field maps to a column `public.games` already has; nothing
here needs a migration. Read-only.

| Path | Type | Notes |
|------|------|-------|
| `game_id` | uuid | from a recommendation, a search result or a library item |

**200**
```json
{
  "game_id": "bf6fddc6-a4be-4461-8eb9-827239d8dd35",
  "title": "Stardew Valley",
  "description": "You've inherited your grandfather's old farm plot in Stardew Valley…",
  "genres": ["Simulation", "RPG"],
  "tags": ["Farming Sim", "Cozy", "Multiplayer"],
  "release_date": "2016-02-26",
  "developers": ["ConcernedApe"],
  "publishers": ["ConcernedApe"],
  "header_image_url": "https://cdn.akamai.steamstatic.com/steam/apps/413150/header.jpg",
  "review_score": 0.98,
  "critic_score": 0.89,
  "steam_appid": 413150,
  "available_platforms": ["steam", "xbox"],
  "purchase_links": { "steam": "https://store.steampowered.com/app/413150" },
  "owned_on": ["steam"]
}
```
| Field | Type | Notes |
|-------|------|-------|
| `description` | string \| null | |
| `genres`, `tags` | string[] | `[]` when unknown, never `null` |
| `release_date` | string \| null | ISO date, `YYYY-MM-DD` |
| `developers`, `publishers` | string[] | `[]` when unknown |
| `header_image_url` | string \| null | https |
| `review_score`, `critic_score` | float \| null | `0..1`, like everywhere else in this API. Stored as `0..100` |
| `steam_appid` | int \| null | |
| `available_platforms` | string[] | lowercase `steam`, `xbox`, `epic`: where the game can be bought |
| `purchase_links` | object | keyed by lowercase platform. A key is present only when the metadata source supplied a validated link (TM11-37), so `{}` is normal. Never build a link client-side |
| `owned_on` | string[] | platforms the user owns it on, in badge order (`steam`, `xbox`, `epic`), from `DeduplicationService.owned_platforms` (TM11-58). `[]` when not owned |

**Errors**
| Status | `error` | When |
|--------|---------|------|
| 404 | `game_not_found` | no catalogue game with this id |
| 422 | | `game_id` isn't a uuid (shape 2 in [Errors](#errors)) |
| 503 | `game_detail_failed` | anything else; the cause is only logged |

- Register the route after `GET /api/games/search`. Otherwise `search` is read as
  a `game_id` and answers 422.
- Page-view logging (TM11-79) is a separate write and not part of this response.

## `POST /api/library/manual`

Add one catalogue game to the library by hand (TM11-54, REQ004). For platforms
with no library API.

**Request**
```json
{ "platform": "epic", "game_id": "7b0d…" }
```
| Field | Type | Notes |
|-------|------|-------|
| `platform` | `"epic"` \| `"xbox"` | where the user owns the game. Steam has its own import |
| `game_id` | uuid | from `GET /api/games/search`. Free-typed titles can't be added; a CSV upload queues those for review |

**201**
```json
{ "game_id": "7b0d…", "title": "Hades", "platform": "epic", "import_method": "MANUAL" }
```
The row is written to `owned_games` with `import_method = 'MANUAL'`. Every
other write keeps the column default, `OAUTH`.

**Errors**
| Status | `error` | When |
|--------|---------|------|
| 404 | `game_not_found` | `game_id` isn't in the catalogue |
| 409 | `already_owned` | already in the library on this platform, including a race between two adds (`owned_games_user_platform_manual_game_key`) |
| 422 | | `platform` not `epic`/`xbox`, or `game_id` not a uuid |
| 503 | `manual_import_failed` | anything else; the cause is only logged |

The same game on two platforms is two entries, not a duplicate.

---

## `POST /api/library/xbox`

Write an Xbox title history to the library (TM11-56, REQ014). Called by the web
app's `POST /api/xbox/import`, which signs the user in to Xbox and fetches the
titles; this route never talks to Microsoft. See
[auth-xbox.md → Importing the library](auth-xbox.md#importing-the-library).

**Request**
```json
{ "titles": [{ "title_id": "2043073184", "name": "Halo Infinite" }] }
```
| Field | Type | Notes |
|-------|------|-------|
| `titles[].title_id` | decimal string, 1–32 chars | the Xbox titleId. Stored in `owned_games.external_id` |
| `titles[].name` | string, 1–300 chars | stored as the row's `title` and matched to the catalogue |

At most 5,000 titles. A titleId listed twice is imported once.

**200**
```json
{
  "total": 4, "added": 4, "updated": 0, "already_owned": 0,
  "matched": 3, "unmatched": 1, "match_rate": 0.75, "import_id": "9c1e…"
}
```
- Each title becomes an `owned_games` row with `platform = 'xbox'`, matched with
  the same title matcher as the Steam sync. Unmatched titles are still written
  (`game_id` null) and queued for review.
- **Idempotent.** Rows are keyed on `(user_id, 'xbox', external_id)`, so a rerun
  updates rows (`updated`) and adds none.
- `already_owned` counts titles whose game is already in the library on Xbox from
  a CSV upload or a manual add. Those rows are left alone, so the game isn't
  listed twice.

**Errors**
| Status | `error` | When |
|--------|---------|------|
| 422 | | a titleId that isn't decimal, a blank name, or more than 5,000 titles |
| 503 | `import_failed` | the write failed. It runs in one transaction, so nothing changed; the cause is only logged |

---

## `POST /api/client-error`

Report a browser error to the server's error sink, so the frontend needs no
Sentry DSN of its own (`api/routers/errors.py`). Unauthenticated on purpose: a
report matters most when auth is what broke.

**Request**
```json
{ "message": "TypeError: x is undefined", "stack": "at Discover (page.tsx:42)",
  "kind": "error", "url": "https://gamegpt.example/discover", "user_agent": "Mozilla/5.0 …" }
```
| Field | Type | Notes |
|-------|------|-------|
| `message` | string | required, at most 1,000 chars |
| `stack` | string \| null | at most 8,000 chars |
| `kind` | string | default `"error"`, at most 64 chars |
| `url` | string \| null | at most 2,000 chars |
| `user_agent` | string \| null | at most 500 chars |

**204** No Content, always, including when the caller is rate limited
(20 reports a minute per IP). A client that is already failing shouldn't have
to handle a failure from the endpoint it reports to. Everything is redacted
before it is logged.

- **422**: a field over its limit, or `message` missing.
