# Steam sign-in (OpenID)

E4 Platform Linking & Library Sync · REQ010 (first half) · TM11-44

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
   out the steamID64, and redirects back to `/settings` carrying the outcome.

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
accounts card (`web/app/(app)/settings/page.tsx`, `useSteamCallbackResult`) reads that param,
shows a banner via `describeSteamResult`, records the link on success, kicks off a library
import (`syncLibrary`), then strips the params so a reload does not replay the outcome or leave
the steamID64 sitting in the URL.

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
neither. The only related secret is `STEAM_API_KEY`, used by the separate library-sync backend
(`api/services/library_sync.py`) to read owned games once we have the steamID64 — not by this
sign-in.

## Where the steamID64 lands

On success the flow hands the verified steamID64 to the client, which records the linked
account and calls `syncLibrary(steamId)`. In the data model this maps onto
`public.platform_accounts` with `platform='STEAM'`, `platform_user_id=<steamID64>`,
`import_method='OAUTH'` (`supabase/migrations/20260915120200_create_core_tables.sql`) — no new
migration is required; the enum and table already carry Steam.

## Testing

`web/lib/auth/steam.test.ts`, grouped by acceptance criterion — the redirect it builds
(AC1/AC4), reading and verifying the assertion including a forged/failed-verification
assertion (AC1), the state nonce being kept out of the verify POST (AC2), and every cancelled
or failed outcome mapping to a linked-accounts message (AC3).

The Steam side of the round trip is not covered by unit tests; it needs a real Steam account
and the deployed callback host. Verified manually — screenshots in `/artifacts`.
