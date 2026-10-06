# GameGPT — API Reference

Base URL (local): `http://localhost:8000`. All endpoints are under `/api`.
The machine-readable contract is [`openapi.json`](../openapi.json) at the repo
root (also served at `/openapi.json`, with interactive docs at `/docs`).

Request/response models are defined in `api/models/schemas.py`. There is **no
auth** — every request acts as the single seeded dev user (`DEV_USER_ID`).

## Conventions

- Content type is `application/json`.
- Errors return a structured body: `{"detail": {"error": "<code>", "message": "<text>"}}`
  with status `502` (a downstream/LLM/Steam failure) or `503` (DB unavailable).
- UUIDs are strings; `review_score` is a float in `0..1`.

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

**200**
```json
{
  "items": [
    { "game_id": null, "title": "Celeste", "steam_appid": 504230, "platform": "steam" }
  ]
}
```

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
- **502** `sync_failed` on a Steam/API error.

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
  "source": "steam", "error": null,
  "started_at": "2026-10-06T14:31:37Z", "finished_at": null
}
```
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

