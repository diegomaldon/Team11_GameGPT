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
{ "synced": 5, "source": "seed" }
```
| Field | Type | Notes |
|-------|------|-------|
| `synced` | int | rows upserted / counted |
| `source` | `"steam"` \| `"seed"` | `"steam"` = real API call; `"seed"` = no-key fallback |

- With `STEAM_API_KEY` set: calls `IPlayerService/GetOwnedGames`, upserts
  `owned_games`, returns `source: "steam"`.
- Without a key: reuses seeded `owned_games`, else a small built-in fallback set,
  returns `source: "seed"`.
- **502** `sync_failed` on a Steam/API error.
