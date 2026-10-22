# ADR 0001: Xbox account linking access path

- **Status:** Accepted (go), Sprint 5
- **Story:** TM11-53 (REQ014). Unblocks TM11-56 (Xbox library import, Sprint 6)
- **Decider:** Noah Merhai

## Context

TM11-53 says "only start this if the Sprint 00 ADR returned a go". That ADR was planned
("issue 1007") but never written, so there was no recorded decision. This document is that
decision.

REQ014 needs a GameGPT user to link their Xbox account, so a later story can read the games
they own. Linking needs a stable Xbox identity (the XUID) that we have verified belongs to
the person who is signed in.

## Options

| Option | How it works | Verdict |
|---|---|---|
| **A. Microsoft identity platform + Xbox Live XSTS** | OAuth 2.0 authorization code + PKCE against `login.microsoftonline.com/consumers` with scope `XboxLive.signin`. Trade the Microsoft token at `user.auth.xboxlive.com` for an Xbox Live user token, then at `xsts.auth.xboxlive.com` for an XSTS token whose claims carry the XUID and gamertag. | **Chosen** |
| B. OpenXBL (xbl.io), third-party proxy | The user signs in through OpenXBL, and we call its REST API with an app key. | Rejected. A third party holds our users' Xbox sessions, the free tier is rate-capped, and the service could disappear mid-semester. |
| C. Official Xbox Services API (GDK / partner program) | Supported Microsoft SDK for titles in the Xbox partner programs. | Rejected. It needs a published or partner title, which a course project can't get. |
| D. No-go: manual import only (TM11-54) | Users type their Xbox games in by hand. | Kept as the fallback if A stops working. |

## Decision

**Go with option A.** It uses only Microsoft's own endpoints, needs no third party, and
answers both TM11-53 acceptance criteria:

- **AC1:** the XSTS claims give a verified XUID, which is written to `platform_accounts` as
  `platform = 'XBOX'`, `platform_user_id = <XUID>`, `import_method = 'OAUTH'`.
- **AC2:** XSTS rejects accounts that can't use Xbox Live with specific `XErr` codes (no
  Xbox profile, child account, unsupported region, adult verification required). Each maps
  to its own message in `web/lib/auth/xboxMessages.ts`. A declined consent screen maps to
  "cancelled", not an error.

Because this is a go, AC3 (re-scope into manual import) does not apply. TM11-53 keeps its
points, and REQ014 is unchanged.

## Consequences

- **Setup.** We need an Azure app registration (Microsoft Entra, "personal Microsoft
  accounts" audience) and a client secret. Microsoft only redirects to registered URIs, so
  each environment's `/api/xbox/callback` must be added to that registration. Steam's
  OpenID needed no allow-list; this one does.
- **Secrets.** `XBOX_CLIENT_ID` and `XBOX_CLIENT_SECRET` are server-only env vars, never
  `NEXT_PUBLIC_`. The secret also keys the HMAC that seals the verified identity between
  the callback and the link request.
- **No tokens stored yet.** Linking needs only the XUID, so no Microsoft or Xbox token is
  written (`platform_accounts.access_token` stays null). TM11-56 will need a refresh token to
  read the library offline. Storing it, and how (encrypted column vs. re-auth on each
  import), is that story's decision.
- **Revocation.** The Microsoft identity platform has no revocation endpoint, which
  `web/lib/account/revoke.ts` already reports honestly on account deletion. Not storing
  tokens means there is nothing to revoke.
- **Risk.** The `XboxLive.signin` + XSTS exchange is the same route Microsoft's own
  launchers and the widely used community libraries take, but it is not documented as a
  public API for non-game apps. If Microsoft blocks it for our app registration, fall back
  to option D and record the change on TM11-53 / TM11-56.

## Verification status

Unit tests cover every hop with fake Microsoft and Xbox responses
(`web/lib/auth/xbox.test.ts`, `web/lib/account/linkXbox.test.ts`,
`web/lib/auth/xboxClient.test.ts`). A live round trip needs the Azure app registration
above and a real Xbox account. That registration doesn't exist yet, so the live flow is
**not yet verified**. See `docs/auth-xbox.md` → "Setting up the Azure app".

## Addendum: TM11-56 library import

- **Status:** Accepted, Sprint 6. **Decider:** Maceo Morgan

The Consequences above left "store a refresh token, or re-auth on each import" to
TM11-56.

**Decision: re-auth on each import. No token is stored.** **Import games** runs the
same Microsoft sign-in again. The callback encrypts the XSTS token and user hash
(AES-256-GCM) into a 5-minute httpOnly cookie, and `POST /api/xbox/import` uses them for
one titlehub call and drops them.

- **Why.** `platform_accounts.access_token` is plaintext today (marked SECURITY DEBT in
  the core migration). A stored refresh token would be a long-lived credential for the
  user's Microsoft account in that column. Re-auth costs one extra click and keeps
  "nothing to revoke" true.
- **Cost.** No background or scheduled Xbox refresh. Each import is user-initiated.
  Revisit if a sync-on-a-schedule story appears, together with moving tokens into
  Supabase Vault.
- **Data source.** titlehub's title history, not purchases (there is no public purchase
  API). See [auth-xbox.md → Importing the library](../auth-xbox.md#importing-the-library).
