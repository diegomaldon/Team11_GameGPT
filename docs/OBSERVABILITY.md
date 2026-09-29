# Observability — TM11-20

Structured logging and error tracking — enough to debug a failing demo.

Related: [RUNBOOK.md](RUNBOOK.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [security-notes.md](security-notes.md)

---

## Shape of a log line

Every server log line is one JSON object on stdout. Render collects stdout, so
there is nothing to mount, rotate or forget.

```json
{"ts":"2026-09-22T14:03:11.204Z","level":"info","logger":"gamegpt.request",
 "msg":"request.complete","request_id":"0b6f2c...","user_id":"9c2e...",
 "auth":"dev","method":"POST","path":"/api/recommend","status":200,
 "duration_ms":842.3}
```

`request_id`, `user_id` and `auth` are present on **every** line including
`null` values, so `jq` filters never break on a missing key:

```bash
# everything one request did
render logs | jq 'select(.request_id == "0b6f2c...")'

# what actually went wrong
render logs | jq 'select(.level == "error") | {msg, request_id, error}'
```

### Why existing log calls did not need editing

`ContextFilter` reads the request context out of `contextvars` and stamps it
onto every `LogRecord` at the handler. The `log.info` and `log.exception` calls
already scattered through `routers/` and `services/` gained `request_id` and
`user_id` without a single call-site change.

Use `extra=` for structured fields rather than f-strings — `log.info("sync
done", extra={"synced": n})` gives you a queryable field; `log.info(f"synced
{n}")` gives you a string to regex later.

### `auth` is not an authorization claim

The frontend has real Supabase sessions since TM11-26/27, and `lib/api/client.ts`
now attaches the access token — but **the API still has no auth layer**: every
router acts as `DEV_USER_ID`. The middleware reads `sub` out of the JWT if one
arrives and does **not verify the signature**, labelling it
`auth: "jwt-unverified"` so no log line can imply an identity check that did not
happen. Good enough to correlate a session across lines; useless as a security
control, and it must never be used to decide what a caller may read or write.

Verifying properly needs the Supabase JWT secret and a real dependency (PyJWT),
and belongs with the ticket that actually makes the API enforce authorization.
When that lands, `subject_from_bearer` should be replaced rather than extended,
and the `auth` label becomes `"jwt"`.

### The token gets to the client without a second session reader

`lib/auth/session.tsx` states that nothing else should call
`supabase.auth.getSession()` — two readers drift apart the moment a token
refreshes. `lib/api/client.ts` is not a component and cannot use `useAuth()`, so
`lib/auth/token.ts` is a plain module the provider publishes into from `apply()`
(the single funnel every session change already passes through) and the fetch
client reads. One subscriber, one source of truth.

---

## Request id

The browser generates one per API call (`web/lib/observability.ts`), sends it
as `x-request-id`, and the API echoes it back — exposed through CORS so the
frontend can read it. On an error the id is shown to the user as `ref <id>`.

That means a bug report during a demo goes: user reads the ref → `jq
'select(.request_id == "...")'` → the exact request, its duration, its status,
and its stack trace.

If no id arrives, the server mints one (32 hex chars). Inbound ids are capped
at 64 characters — the value is attacker-controlled and lands in every line.

`/api/health` is excluded from the access log. Render polls it every ~30s and
it would otherwise be most of the log volume on an idle demo service.

---

## Error sink

```
browser  ──POST /api/client-error──┐
                                    ├──► sink.report() ──► Sentry  (SENTRY_DSN set)
FastAPI unhandled exception ────────┘                    └──► stdout JSON (unset)
```

Both paths go through `api/observability/sink.py`, so "one place" holds either
way. An unset `SENTRY_DSN` is not an error — it follows the convention already
in `api/config.py` where a blank key falls back to something that still works
offline, which keeps CI and a keyless local run green.

**The frontend has no DSN of its own.** Routing browser errors through the API
means one sink, one config value, and nothing Sentry-shaped in the client
bundle. The cost: client errors that happen while the API is unreachable are
console-only. Acceptable for a demo; a real deployment would want a browser SDK.

What is covered on the client:

| Failure | Caught by |
|---|---|
| React render error in a page | `app/error.tsx` |
| React render error in the root layout | `app/global-error.tsx` |
| Uncaught async throw | `window.addEventListener("error")` |
| Unhandled promise rejection | `window.addEventListener("unhandledrejection")` |

Reports are deduplicated by message and capped at 25 per session, because a
render loop that throws would otherwise DOS our own API with reports.

`/api/client-error` is unauthenticated by necessity — an error report is most
useful exactly when auth is what broke — so it is treated as hostile input:
field-length caps via Pydantic, a 20-per-minute per-IP window, and full
redaction before anything is written. It answers `204` even when rate-limited;
a client that is already failing should not have to handle a failure from the
endpoint it reports failures to.

---

## Redaction

Two independent layers, because either alone has a hole.

**Field names** (`is_secret_key`) catch structured data — headers, an env dump,
a `platform_accounts` row. Exact, but only works when the secret arrives
labelled. Matching normalises case and punctuation, so `x-api-key`, `X_API_KEY`
and `apiKey` all land, while `monkey` does not.

**Value shapes** (`scrub_text`) catch free text — exception messages, stack
traces, an f-string a teammate wrote at 2am. Covers JWTs, `sk-ant-…`, `AIza…`,
`sbp_…`, bare 32-hex strings (the shape of both the Steam and RAWG keys), and
Postgres DSN passwords. DSN handling keeps the host and database and drops only
the password, because a redacted-but-readable connection string is still
debuggable.

URLs are scrubbed per-parameter rather than wholesale: `?key=[redacted]&steamid=765…`
keeps the endpoint and the useful parameters.

### The bug this ticket fixed

`httpx`'s `raise_for_status()` builds a message containing the full request URL.
Two outbound calls put a key in the query string:

- `services/library_sync.py` → `?key=<STEAM_API_KEY>`
- `services/llm.py` → `?key=<GEMINI_API_KEY>`

The Steam one was live: a 403 from Steam raised an exception whose message
contained the key, `routers/library.py` caught it with `log.exception("library
sync failed")`, and the key went to Render's logs in plaintext. The Gemini one
was latent — swallowed by the provider retry loop, one added log call away from
the same outcome.

Both now use `raise_for_status_safe(resp, "steam")`
(`api/observability/upstream.py`), which reports the status and a sanitized URL.
The formatter-level scrub stays as a backstop for the next person who reaches
for `raise_for_status()` out of habit, and `test_exception_text_is_scrubbed_in_the_log_line`
proves the backstop works independently of the fix.

### Rules

- Never log request or response bodies. `send_default_pii=False` and
  `max_request_body_size="never"` enforce the same on the Sentry side.
- Log headers by allow-list only, never wholesale.
- Reach for `extra=`, not string interpolation, so values pass through `redact()`
  as structured data rather than as pre-formatted text.

### Still outstanding

`platform_accounts.access_token` is plaintext in the database
([security-notes.md](security-notes.md), and a follow-up ticket). Redaction
stops it reaching a log; it does not stop it sitting in a table. The field-name
layer covers `access_token`, so a logged row is safe — but do not treat that as
the fix.

---

## Verifying it

```bash
pytest api/tests/test_observability.py -v      # 47 assertions, offline, no keys
```

The suite is wired into CI as the `API tests` job. It is the only acceptance
criterion on this ticket that can be proven rather than screenshotted, which is
why it carries most of the weight.

Manual checks for the ticket:

```bash
# 1. AC-1 — request id and user id on the line
uvicorn api.main:app --port 8000 &
curl -s -D- -H 'x-request-id: demo-1' localhost:8000/api/recommend \
  -H 'content-type: application/json' -d '{"query":"cozy farming"}' | head -1
# the response carries x-request-id: demo-1; the log line carries the same

# 2. AC-2 — a client error reaches the server sink
curl -s -X POST localhost:8000/api/client-error -H 'content-type: application/json' \
  -d '{"message":"TypeError: x is not a function","kind":"error"}'
# -> {"level":"error","msg":"client error: TypeError: x is not a function",...}

# 3. AC-3 — a secret does not survive
STEAM_API_KEY=A1B2C3D4E5F60718293A4B5C6D7E8F90 \
  curl -s -X POST localhost:8000/api/library/sync \
  -H 'content-type: application/json' -d '{"steam_id":"1"}'
# grep the log for the key; it should not appear
```
