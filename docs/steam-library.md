# Steam library import

How GameGPT reads a user's owned games from Steam.

Ticket: [TM11-46](https://syr-team-rxkvdczq.atlassian.net/browse/TM11-46) · REQ010 ·
Epic TM11-4 Platform Linking & Library Sync

| Acceptance criterion | Where it lives |
| --- | --- |
| Returns owned appids with playtime for a given Steam ID | `SteamClient.get_owned_games` → `list[OwnedGame]` |
| A private profile returns a typed error the UI can explain | `SteamPrivateProfileError` → HTTP 403 + `steam_profile_private` |
| Rate limits respected | `AsyncRateLimiter`, 1 req/s default, applied to retries too |
| Unit tested against a recorded fixture | `api/tests/test_steam_client.py`, 38 tests |

## Why this needs a client at all

`IPlayerService/GetOwnedGames` needs only an API key and a public steamID64 — no
OAuth, no user consent flow. That makes it easy to call badly. Three things make
a naive call wrong:

1. **A private profile looks like success.** Steam answers `200 OK`, not `403`.
2. **Playtime is the interesting half of the payload** and is trivially dropped.
3. **The API key travels in the query string**, so any logged URL is a secret.

## Private vs. empty — the only signal there is

A private profile and a public account that owns nothing both come back `200`.
The difference is one key:

```json
{"response": {}}                  // private, or no such account
{"response": {"game_count": 0}}   // public, visible, owns nothing
```

So **a missing `game_count`** is what identifies a private profile — not the
status code, not an empty `games` array. (`games` is also absent when
`game_count` is `0`, which is why it cannot be the test.)

Conflating the two tells a user with a private profile that they own no games,
and sends them looking for a bug in the import instead of at their Steam privacy
settings. `test_private_is_distinguished_from_empty` pins this.

Setting a profile to public requires **both** toggles: Steam → Profile → Edit
Profile → Privacy Settings → *My profile* **and** *Game details* → Public. Game
details alone is not enough, which is why the error message names both.

## Error contract

`POST /api/library/sync` turns every Steam failure into a stable code. The
frontend branches on `error`; `message` is written for a person and is safe to
render verbatim — it never contains an id, a key, or a URL.

| Exception | HTTP | `error` | Meaning |
| --- | --- | --- | --- |
| `SteamPrivateProfileError` | 403 | `steam_profile_private` | Visible to Steam, not to us. The user can fix it. |
| `SteamInvalidSteamIDError` | 422 | `steam_invalid_id` | Not a 17-digit steamID64. No request was made. |
| `SteamPermanentError` | 502 | `steam_request_rejected` | Steam rejected us, usually a bad key. Not the user's problem. |
| `SteamTransientError` | 503 | `steam_unavailable` | Down or throttling, after retries. Try again. |
| anything else | 502 | `sync_failed` | Unrelated bug. No detail leaks. |

4xx means someone can fix it; 5xx means retry. That split is what lets the
library view show a useful message instead of a spinner that never resolves.

## Rate limiting

Steam publishes a ceiling of **100,000 calls per key per day** — about 1.16/s
sustained — and no documented per-second limit. The client paces at **1 req/s**
(`_STEAM_MIN_INTERVAL`), which stays under the ceiling even if a caller loops.

Pacing is applied **inside** the retry loop, so a retry storm is throttled too.
That is the moment it matters most: a 429 answered by three immediate retries is
how a key gets suspended.

A `429` with `Retry-After` honours the server's number instead of the local
backoff curve. `500/502/503/504` and network errors retry with exponential
backoff (4 attempts). `400/401/403/404` do not retry — they will not get better.

## Playtime

`playtime_forever` is **whole minutes**, lifetime. `0` means owned but never
played, which is normal and is not an error.

On re-sync, `upsert_owned_games` takes `greatest(existing, incoming)`. Playtime
only grows, so a partial or failed sync can never zero out real hours.

## Recording the fixture

The fixtures under `api/tests/fixtures/steam/` come from the live API:

```bash
export STEAM_API_KEY=...        # steamcommunity.com/dev/apikey
python3 scripts/record_steam_fixture.py 76561197960287930
```

Stdlib only, so it needs no virtualenv. It copies out only the `response`
object and refuses to write a file containing the key.

| Fixture | Shape |
| --- | --- |
| `owned_games.json` | a public library with playtime, including a 0-minute title |
| `private_profile.json` | `{"response": {}}` |
| `empty_public_library.json` | `{"response": {"game_count": 0}}` |

Tests never touch the network: `httpx.MockTransport` serves these files, and an
injected `sleep`/`monotonic` makes backoff and pacing instant and deterministic.
The whole suite runs in well under a second with no API key.

## Known gap

**There are two `owned_games` tables in this repo and they disagree.**

| | `0001_init.sql` | `20260915120200_create_core_tables.sql` |
| --- | --- | --- |
| Shape | `user_id, platform, steam_appid, title` | `user_id, platform_account_id, game_id, playtime_minutes, …` |
| Used by | `api/db/repositories.py` | the hosted Supabase project |

`repositories.py` writes columns the hosted database does not have. This is not
failing today only because `DATABASE_URL` is unset by default, so
`Settings.db_enabled` is `False` and that code path never runs.

`20261006120000_owned_games_playtime.sql` adds `playtime_minutes` with
`if not exists`, so it is correct against either schema — a no-op on the hosted
project, and the missing column on a dev box built from `0001_init.sql`.

Reconciling the two properly is its own story: the core table requires
`platform_account_id` and `game_id` NOT NULL, so library sync would first have
to resolve or create a `platform_accounts` row and a `games` row per title.
That is not a 3-point client ticket.
