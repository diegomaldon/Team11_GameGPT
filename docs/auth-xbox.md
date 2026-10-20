# Xbox account linking

E2 Platform Linking & Library Sync · REQ014 · TM11-53. Why this path was chosen:
[ADR 0001](adr/0001-xbox-account-linking.md).

## The flow

Steam speaks OpenID. Xbox needs three server-side token exchanges and then a separate,
authenticated write. All of it runs in Next Route Handlers under `web/app/api/xbox/`:

1. **`GET /api/xbox/login`.** Called by **Connect** on Settings → Linked accounts. Mints a
   `state` nonce and a PKCE verifier, stores both in httpOnly cookies scoped to `/api/xbox`,
   and redirects to Microsoft sign-in (`scope=XboxLive.signin`, `prompt=select_account`).
2. **`GET /api/xbox/callback`.** Where Microsoft sends the user back.
   - Checks the state against the cookie.
   - Exchanges the code (with the verifier and client secret) for a Microsoft token.
   - Trades that token for an Xbox Live user token, then an XSTS token.
   - Reads the XUID and gamertag from the XSTS claims.
   - Seals them into a 10-minute HMAC-signed httpOnly cookie and redirects to
     `/settings?xbox=verified`.
3. **`POST /api/xbox/link`.** The Settings page calls this with its Supabase bearer token.
   The route opens the sealed cookie, then upserts `platform_accounts` **as that user**
   (their own JWT, so RLS applies; no service-role key) and returns the gamertag.

### Why a sealed cookie and not the URL

The callback knows the Xbox identity but not who the GameGPT user is, because the Supabase
session lives in the browser. If the XUID came back in the URL, anyone could hand-craft
`/settings?xbox=linked&xuid=…` and link someone else's Xbox account. The signed cookie can
only be minted by our callback after Microsoft has vouched for the user.

### The row written (AC1)

| Column | Value |
|---|---|
| `platform` | `XBOX` |
| `platform_user_id` | XUID from the XSTS claims |
| `import_method` | `OAUTH` |
| `linked_at` | now |
| `access_token` | not written (see the ADR) |

- `unique (user_id, platform)` is the upsert target, so re-linking replaces the user's
  Xbox account.
- `unique (platform, platform_user_id)` means an XUID can belong to only one GameGPT user.
  A second user trying to link it gets **409 `taken`**.

### Every failure returns to Settings with a message (AC2)

| What happened | `reason` | Message (abridged) |
|---|---|---|
| User pressed "No" on consent | `cancelled` result | "Xbox sign-in was cancelled…" |
| Microsoft error, or code exchange rejected | `auth` | "Microsoft sign-in didn't finish…" |
| XSTS `XErr 2148916233` | `no_profile` | "…doesn't have an Xbox profile yet. Sign in once at xbox.com…" |
| XSTS `XErr 2148916238` | `child` | "…child account. A parent needs to allow Xbox Live…" |
| XSTS `XErr 2148916235` | `region` | "Xbox Live isn't available in this account's country or region…" |
| XSTS `XErr 2148916236` / `2148916237` | `verification` | "…needs adult verification on xbox.com…" |
| Any other XSTS refusal | `unsupported` | "…can't be used with Xbox Live…" |
| XUID already linked elsewhere | `taken` | "That Xbox account is already linked to a different GameGPT account." |
| State mismatch, or link cookie expired | `state` / `expired` | "…couldn't be verified as yours or took too long…" |
| Microsoft or Xbox unreachable / 5xx | `network` | "Couldn't reach Xbox…" |
| Server has no Azure app configured | `config` | "Xbox connection isn't set up on this server yet." |
| GameGPT session expired before the link | `session` | "Your GameGPT session expired…" |

## Importing the library

TM11-56 (REQ014). A linked Xbox row on Settings → Linked accounts has an **Import
games** button. The decision behind the flow is recorded in the
[ADR addendum](adr/0001-xbox-account-linking.md#addendum-tm11-56-library-import).

1. **`GET /api/xbox/login?intent=import`.** The same Microsoft sign-in as linking. The
   intent goes in an `xbox_oauth_intent` cookie.
2. **`GET /api/xbox/callback`.** Runs the same three hops, but keeps the XSTS token and
   user hash. It seals `{xuid, gamertag, uhs, xstsToken}` into a **5-minute** httpOnly
   cookie (`xbox_import_session`, its own HMAC key) and redirects to
   `/settings?xbox=import-ready`.
3. **`POST /api/xbox/import`.** The page calls this with its Supabase bearer token.
   - The route opens the cookie (single-use, cleared on every response).
   - It reads the user's `platform_accounts` XBOX row with their own JWT, so RLS applies.
     The session's XUID must match it, otherwise the result is `not_linked` or `mismatch`.
   - It reads the title history from titlehub with `Authorization: XBL3.0 x=<uhs>;<xsts>`
     and keeps entries with `type: "Game"` (apps are dropped).
   - It posts `{title_id, name}` for each game to the API's
     [`POST /api/library/xbox`](API.md#post-apilibraryxbox), which matches them with the
     shared title matcher and writes `owned_games` rows with `platform = 'xbox'`.
4. The page shows the result and stamps `last_synced_at` on the Xbox row.

**Idempotent.** Each row is keyed on the Xbox titleId (`owned_games.external_id`,
migration `20261020120000`), so importing again updates rows and adds none. A game
already added on Xbox by CSV or by hand is left alone (`already_owned`).

**Server-only env.** `POST /api/xbox/import` reaches the API at `API_URL`, or
`NEXT_PUBLIC_API_URL` when that's empty.

### What "owned" means here

Xbox has no public purchase-history API for third-party apps. The import reads the
**title history**: every game the account has launched, on console or PC. A game that
was bought but never played isn't imported, and a Game Pass title the user tried is.
Users can fill gaps with the TM11-55 CSV upload or a TM11-54 manual add.

### Import failures

| What happened | `reason` | Message (abridged) |
|---|---|---|
| No Xbox account linked | `not_linked` | "Connect your Xbox account first…" |
| Signed in to a different Xbox account | `mismatch` | "…a different Xbox account than the one linked here…" |
| Privacy settings hide game history (titlehub 403) | `private` | "Your Xbox privacy settings hide your game history…" |
| Session cookie missing, forged or older than 5 minutes, or titlehub 401 | `expired` | "…took too long. Start again…" |
| titlehub down / unreachable | `network` | "Couldn't reach Xbox…" |
| titlehub junk, or the API rejected the import | `import` | "Couldn't import your Xbox games. Your library is unchanged…" |

### Known limits

- **Not verified live.** As with linking, a real round trip needs the Azure app and a
  real Xbox account. titlehub is covered by fake responses only.
- **The API side follows the existing schema gap.** `owned_games.platform` and
  `external_id` exist only in the `0001_init.sql` shape, and
  `repositories.list_catalogue_games()` reads `games.game_id`, which exists only in the
  hosted shape. So, like the Steam sync and the CSV upload, the import can't run end
  to end against either database yet. See [steam-library.md → Known
  gap](steam-library.md#known-gap).

## Setting up the Azure app

1. Microsoft Entra admin center → App registrations → New registration.
   - Supported account types: **Personal Microsoft accounts only**.
   - Redirect URI (Web): `http://localhost:3000/api/xbox/callback`, then add the deployed
     `https://<host>/api/xbox/callback`.
2. Certificates & secrets → New client secret.
3. Put the values in `web/.env.local` and on Vercel. These are **server-only, never
   `NEXT_PUBLIC_`**:
   ```
   XBOX_CLIENT_ID=<Application (client) ID>
   XBOX_CLIENT_SECRET=<secret value>
   ```
Without them, **Connect** returns straight to Settings with "Xbox connection isn't set up on
this server yet." instead of failing halfway.

## Testing

```
cd web && npx vitest run lib/auth/xbox.test.ts lib/account/linkXbox.test.ts lib/auth/xboxClient.test.ts \
  lib/library/xboxImport.test.ts app/api/xbox
python -m pytest api/tests/test_xbox_import.py -v     # the API side (TM11-56)
```

Grouped by acceptance criterion:
- The authorize URL, PKCE, the code exchange, the user-token and XSTS hops, and every XErr
  mapping, against fake Microsoft and Xbox responses.
- The sealed identity cookie, including a forged payload, a different key, and expiry.
- The `platform_accounts` upsert, including `taken` (23505), no session, and a DB error.
- The browser call to `/api/xbox/link`.

The live round trip is not covered by tests. It needs the Azure app above and a real
Microsoft account with an Xbox profile.
