# Sprint 2 — E2 Identity & Account Management

Evidence for TM11-26 and TM11-27. Captured 2026-09-22 against the GameGPT Supabase
project, signed in with a real Google account.

## TM11-26 — Google OAuth sign-in

| Acceptance criterion | Evidence |
| --- | --- |
| Provider configured | `tm11-26-ac1-google-oauth-client.png` — Google Cloud OAuth client with the Supabase callback registered |
| | `tm11-26-ac1-supabase-provider-enabled.png` — provider enabled in Supabase, client ID set, secret hidden |
| | `tm11-26-ac1-redirect-allowlist.png` — our callback URL on the redirect allowlist |
| First sign-in provisions a users row with authProvider GOOGLE | `tm11-26-ac2-google-signin-success.png` — signed in through Google |
| | `tm11-26-ac2-users-row-google.png` — `public.users` row, `auth_provider = GOOGLE`, name from the Google profile |
| Collision with an existing password account handled deterministically | `docs/auth-google-oauth.md` → "Collision with an existing password account" |
| Callback errors surface a usable message | `tm11-26-ac4-cancelled-signin.png` — cancelled at Google's consent screen, app explains it and offers a way back |

`tm11-26-signin-page.png` is the sign-in page itself, for context.

## TM11-27 — Session persistence, refresh and protected routes

| Acceptance criterion | Evidence |
| --- | --- |
| Session survives refresh and browser restart | `tm11-27-ac1-session-persists.png` — still signed in after quitting and reopening the browser |
| Expired tokens refresh silently | `tm11-27-ac2-token-refresh.png` — `POST /auth/v1/token?grant_type=refresh_token` → 200 with the UI unchanged. Captured with the access token TTL temporarily lowered to 60s; it was restored to 3600s afterwards |
| Unauthenticated access redirects to sign-in, then returns | `tm11-27-ac3-protected-route-redirect.png` — `/library` while signed out lands on `/signin?next=%2Flibrary` |
| Sign-out clears client state and revokes the session | `web/lib/auth/session.test.tsx`, "AC4" block — asserts `signOut({ scope: 'global' })` and that local state clears even when the revoke call fails |

## Tests

87 unit tests, grouped by acceptance criterion so the run output reads as a checklist:

- `web/lib/auth/session.test.tsx` — persistence, silent refresh, sign-out, listener cleanup
- `web/lib/auth/redirect.test.ts` — return-to-page and open-redirect rejections
- `web/lib/auth/oauth.test.ts` — the redirect built, the `next` refused, every mapped callback error
- `web/lib/auth/signin.test.ts` — password sign-in result mapping

## Known gap

TM11-26 AC1 says "both environments". GameGPT currently runs against a single Supabase
project, so this is configured once, for localhost. The deployed origin still needs adding
to the redirect allowlist before the app will authenticate anywhere but local.
