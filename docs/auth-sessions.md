# Sessions and protected routes

E2 Identity & Account Management · REQ001 / REQ002 · TM11-27

How a GameGPT session is stored, refreshed, and ended, and what the auth gate does and
does not protect.

## Where the session lives

`web/lib/supabase.ts` creates the browser client with `persistSession: true`, so the
session is written to `localStorage` under a Supabase-managed key. That is what makes it
survive a reload and a browser restart — nothing in our code copies it anywhere.

`web/lib/auth/session.tsx` is the only thing that reads it. On mount it calls
`getSession()` once, then subscribes to `onAuthStateChange` and takes every session it is
handed. Everything else in the app goes through `useAuth()`.

Do not call `supabase.auth.getSession()` from a component. Two independent readers drift
apart the moment a token refreshes, and the one that missed the event starts sending a
stale JWT.

## Refresh

`autoRefreshToken: true` means supabase-js refreshes the access token on its own timer,
shortly before it expires, and emits `TOKEN_REFRESHED`. The provider swaps in the new
session without passing through a signed-out state, so nothing above it re-renders as
anonymous. There is no refresh code of ours to maintain.

The timer only runs while the tab is alive. A tab left open past expiry refreshes on its
next event; a tab that was closed goes through the `getSession()` path on next load, which
refreshes if the stored access token has already expired.

## The gate

`web/components/auth/RequireAuth.tsx` wraps the `(app)` route group. Three states:

| `status`        | What renders                                      |
| --------------- | ------------------------------------------------- |
| `loading`       | Loading placeholder — no decision yet              |
| `anonymous`     | Nothing; redirects to `/signin?next=…`            |
| `authenticated` | The children                                      |

`loading` is a real state, not a detail. Treating "we have not checked yet" as "signed
out" is what makes an auth gate flash the sign-in page at people who are in fact signed
in.

**This gate is cosmetic.** It decides what renders in a browser the user controls, and
anyone can walk past it with devtools. The real boundary on user data is row level
security in Postgres (`supabase/migrations/20260915120300_rls_and_grants.sql`): a stale or
forged client cannot read another user's rows because the database will not return them.
The gate exists so signed-out visitors get sent somewhere useful instead of watching empty
pages fail to load.

Making it a genuine server-side gate means moving the session from `localStorage` into
cookies so Next middleware can read it, which means replacing `supabase-js` with
`@supabase/ssr` across the app. Worth doing before launch. Not coupled to this story.

## Returning to the intended page

The gate puts the path you were trying to reach into `?next=`, and `/signin` sends you
there afterwards. The query string is preserved, so `/library?filter=steam` comes back
whole.

`next` is attacker-controlled — anyone can mail out `/signin?next=https://evil.example`.
Every read of it goes through `safeNext()` in `web/lib/auth/redirect.ts`, which accepts
only same-origin paths and refuses absolute URLs, protocol-relative `//host` values, the
`/\host` variant, control characters, and the auth routes themselves (returning to
`/signin` after signing in is a loop, not a return). Anything rejected falls back to `/`.

If you add a route that reads `next`, route it through `safeNext`. Do not parse it again.

## Sign-out

`signOut()` calls Supabase with `scope: 'global'`, which revokes every refresh token for
that user rather than only clearing this browser. The default `'local'` leaves a stolen
refresh token valid, which does not meet "revokes the session".

If the call fails — offline, or the token was already revoked — the local state is cleared
anyway. Leaving someone marked signed in because the network was down is the wrong
failure mode.

## Testing

- `web/lib/auth/session.test.tsx` — persistence, silent refresh, sign-out, listener cleanup
- `web/lib/auth/redirect.test.ts` — return-to-page and the open-redirect rejections
- `web/lib/auth/signin.test.ts` — password sign-in result mapping

Tests are grouped by acceptance criterion so the run output reads as a checklist.
