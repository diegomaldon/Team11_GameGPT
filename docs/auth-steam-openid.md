# Steam sign-in (OpenID)

E4 Platform Linking & Library Sync · REQ010 (first half) · TM11-44 · saving the link: TM11-52

## The flow

Steam does not do OAuth2 — it speaks **OpenID 2.0**, so unlike the Google flow there is no
PKCE code and nothing supabase-js can redeem. It is still two halves, because it leaves the
site, but both halves run **server-side** in Next Route Handlers rather than in the browser:

1. `GET /api/steam/login` (`web/app/api/steam/login/route.ts`) — called from the "Connect"
   button on Settings → Linked accounts. Mints a random `state` nonce, stores it in an
   httpOnly cookie, and redirects the browser to `steamcommunity.com` with a realm and
   `return_to` built from the request's own origin.
2. `GET /api/steam/callback` (`web/app/api/steam/callback/route.ts`) — where Steam sends the
   user back. Checks the nonce, verifies the assertion **server-to-server** with Steam, pulls
   out the steamID64, seals it in a short-lived httpOnly cookie, and redirects back to
   `/settings?steam=verified`.
3. `POST /api/steam/link` (`web/app/api/steam/link/route.ts`, TM11-52) — called by the
   Settings page with the user's bearer token. Opens the sealed cookie and upserts the
   user's `platform_accounts` row, acting as the user so RLS limits the write to their row.

The OpenID rules live as pure functions in `web/lib/auth/steam.ts` (`buildSteamAuthUrl`,
`parseSteamCallback`, `buildVerificationBody`, `verifySteamAssertion`, `extractSteamId`), so
the route handlers stay thin and the rules are unit-tested without a browser or network.

### Why it is server-side, unlike Google

Google runs entirely in the browser because supabase-js owns the exchange and the session.
Steam owns neither: the identity it asserts (`openid.claimed_id`) is only trustworthy after we
**echo the whole response back** with `openid.mode=check_authentication` and Steam answers
`is_valid:true`. That is a server-to-server call, and the anti-CSRF nonce belongs in an
httpOnly cookie the page cannot read — both reasons to keep the flow off the client. The repo
had no Route Handlers before this; `web/app/api/steam/*` is the first.

### Why the steamID64 is never trusted early (AC1)

Anyone can craft a URL with a forged `openid.claimed_id` and open the callback. So
`parseSteamCallback` reads the fields but does not believe them; `extractSteamId` is only
called **after** `verifySteamAssertion` returns true. Verification treats a non-200, a
missing `is_valid:true`, or a thrown fetch all as "not verified" — it never fails open.

### The state nonce (AC2)

`/login` generates `crypto.randomUUID()`, sets it as the `steam_openid_state` httpOnly cookie
(`SameSite=Lax`, so it survives Steam's top-level redirect back), and echoes the same value on
`return_to`. Steam preserves `return_to` verbatim, so the callback receives both the nonce and
the openid.* fields. The callback rejects the request unless the returned `state` matches the
cookie, which stops an attacker from replaying someone else's Steam assertion at the callback.
Only the `openid.*` fields are sent back to Steam for verification — our `state`/`next` are
stripped, because Steam neither signed nor expects them.

### Every failure returns to linked accounts with a message (AC3)

Steam reports a cancelled sign-in as `openid.mode=cancel` on a normal page load, not an HTTP
error. So the callback maps **every** outcome — verified, cancelled, bad nonce, failed
verification, malformed identity — to a redirect back to `/settings?steam=…`. The Linked
accounts card (`web/components/account/LinkedAccountsCard.tsx`, `useSteamCallbackResult`)
reads that param, shows a banner via `describeSteamResult`, and on `verified` calls
`POST /api/steam/link`, then kicks off a library import. It strips the params so a reload
does not replay the outcome.

## Works on the deployed environment, not just localhost (AC4)

The realm and `return_to` are built from `originFromRequest`
(`web/lib/auth/request-origin.ts`), never a hardcoded host. Behind Vercel's proxy the
incoming request URL is the internal one, so the helper reads `x-forwarded-host` /
`x-forwarded-proto` first and falls back to the request origin for plain `next dev`. That is
what lets the identical code redirect to `http://localhost:3000/api/steam/callback` in
development and `https://<deployed-host>/api/steam/callback` in production with no
per-environment configuration.

Steam's OpenID realm accepts any `return_to` under the realm's host, so — unlike Google —
there is **no dashboard allow-list to maintain** and **no client secret**. OpenID 2.0 needs
neither. Two related secrets exist: `STEAM_API_KEY`, used by the separate library-sync backend
(`api/services/library_sync.py`) to read owned games, and `STEAM_LINK_SECRET` (web,
server-only, TM11-52), which signs the cookie described below. Without
`STEAM_LINK_SECRET` the callback returns `steam=error&reason=config` rather than saving
anything.

## Where the steamID64 lands

In `public.platform_accounts`, with `platform='STEAM'`, `platform_user_id=<steamID64>`,
`import_method='OAUTH'` (`supabase/migrations/20260915120200_create_core_tables.sql`). No new
migration is required; the enum and table already carry Steam.

Until TM11-52 the callback put the steamID64 in the redirect URL
(`?steam=linked&steamid=…`) and the page recorded it only in the browser's mock store, so a
link never reached the database. Saving it straight from the URL would let anyone link any
Steam account, because the URL is just text the browser sends. The callback knows the Steam
identity but not the GameGPT user (the Supabase session lives in the browser, not a cookie),
so it does what the Xbox flow does (`docs/adr/0001-xbox-account-linking.md`):

- seal the steamID64 into an HMAC-signed, 10-minute, httpOnly cookie scoped to `/api/steam`
  (`web/lib/auth/steamLink.ts`);
- the page calls `POST /api/steam/link` with its bearer token;
- the route opens the cookie, upserts the row as that user (`web/lib/account/linkSteam.ts`)
  and clears the cookie on every response.

A Steam account already linked by another user hits `unique (platform, platform_user_id)`
and comes back as `reason=taken`. Re-linking a different Steam account replaces the user's
row (`unique (user_id, platform)` is the upsert target).

## Testing

TM11-52 adds `web/lib/auth/steamLink.test.ts` (sealing, tampering, expiry),
`web/lib/account/linkSteam.test.ts` (the upsert and its errors),
`web/app/api/steam/callback/route.test.ts` and `web/app/api/steam/link/route.test.ts`.

`web/lib/auth/steam.test.ts`, grouped by acceptance criterion — the redirect it builds
(AC1/AC4), reading and verifying the assertion including a forged/failed-verification
assertion (AC1), the state nonce being kept out of the verify POST (AC2), and every cancelled
or failed outcome mapping to a linked-accounts message (AC3).

The Steam side of the round trip is not covered by unit tests; it needs a real Steam account
and the deployed callback host. Verified manually — screenshots in `/artifacts`.
