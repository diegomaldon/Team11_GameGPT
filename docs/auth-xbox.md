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
cd web && npx vitest run lib/auth/xbox.test.ts lib/account/linkXbox.test.ts lib/auth/xboxClient.test.ts
```

Grouped by acceptance criterion:
- The authorize URL, PKCE, the code exchange, the user-token and XSTS hops, and every XErr
  mapping, against fake Microsoft and Xbox responses.
- The sealed identity cookie, including a forged payload, a different key, and expiry.
- The `platform_accounts` upsert, including `taken` (23505), no session, and a DB error.
- The browser call to `/api/xbox/link`.

The live round trip is not covered by tests. It needs the Azure app above and a real
Microsoft account with an Xbox profile.
