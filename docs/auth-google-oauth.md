# Google sign-in

E2 Identity & Account Management · REQ002 · TM11-26

## The flow

OAuth leaves the site, so the code is in two halves (`web/lib/auth/oauth.ts`):

1. `startGoogleSignIn()` — called from `/signin`. Asks Supabase for a Google redirect and
   hands the browser over. The page the user was trying to reach rides along on the
   callback URL as `?next=`, validated by `safeNext()` on the way out and again on the
   way back.
2. `completeOAuthSignIn()` — runs at `/auth/callback`. Trades the single-use PKCE code
   for a session, or maps whatever went wrong to a message worth showing.

The session that comes out is handled the same as any other — see
[auth-sessions.md](./auth-sessions.md).

### Why `detectSessionInUrl` is off

The client used to let supabase-js spot `?code=` and redeem it automatically. The code is
single-use, so that raced the explicit exchange at `/auth/callback` and whichever call
lost reported a failed sign-in that had actually succeeded. Which one lost depended on
module import order.

`web/lib/supabase.ts` now sets `detectSessionInUrl: false`, and
`completeOAuthSignIn()` is the only thing that redeems a code — for Google and for email
confirmation links, which land on the same route.

## Provider setup (required in both environments)

Google sign-in does not work from a checkout alone. Each Supabase project needs the
provider turned on, and the Google OAuth client needs our callback on its allow list.
Dev and prod are separate projects and need this done twice, with separate credentials.

**1. Google Cloud Console** — APIs & Services → Credentials → Create OAuth client ID →
Web application. Add one authorised redirect URI per environment:

```
https://<dev-project-ref>.supabase.co/auth/v1/callback
https://<prod-project-ref>.supabase.co/auth/v1/callback
```

This is Supabase's URL, not ours. Google talks to Supabase; Supabase then redirects to us.

**2. Supabase dashboard** (each project) — Authentication → Providers → Google. Enable it
and paste that project's client ID and secret.

**3. Supabase dashboard** (each project) — Authentication → URL Configuration → Redirect
URLs. Add where *we* run:

```
http://localhost:3000/auth/callback     (dev)
https://<deployed-host>/auth/callback   (prod)
```

Miss this one and GoTrue refuses to send the user back at all — you get
`redirect_uri_mismatch`, which the callback page reports as a configuration problem
rather than blaming the user.

The client secret belongs in the Supabase dashboard only. It is not an app env var and
must never be committed; `web/.env.example` deliberately has no entry for it.

### Checking it

Provider not enabled for a project surfaces as `Unsupported provider: provider is not
enabled`, which `startGoogleSignIn()` maps to "Google sign-in isn't set up for this
environment yet." Seeing that message means step 2 was missed for whichever project the
app is pointed at.

## Provisioning a users row

`supabase/migrations/20260922120000_provision_users_row.sql` extends the existing
`handle_new_user()` trigger to write `public.users` alongside `public.user_profiles`,
both inside the transaction that creates the account.

`auth_provider` comes from `raw_app_meta_data.provider`, which GoTrue sets — `'google'`
maps to `GOOGLE`, everything else to `EMAIL`. It is read from *app* metadata rather than
*user* metadata on purpose: user metadata is whatever the client passed to `signUp()` and
can be forged by anyone hitting the Supabase API directly.

That migration also backfills every account created before it existed. `public.users` had
been empty since it was created — nothing had ever written to it, including the REQ001
password signups.

## Collision with an existing password account

Someone registers with `diego@example.com` and a password. Later they click "Continue
with Google" with the same address.

**What happens:** GoTrue links the Google identity to the existing `auth.users` row,
because Google asserts the email is verified. Same user, same `user_id`, one account.
No `auth.users` INSERT happens, so the trigger does not fire.

**What that means for us:** the `public.users` row is untouched and still says
`auth_provider = 'EMAIL'`. That is intended, not a bug. The column records how the
account was **first created** and is never updated afterwards.

Flipping it on link would turn a stable fact about account origin into a race between
whichever provider was used most recently. Nothing in the app wants that. To ask "can
this person sign in with Google?", read `auth.identities` — that is the table that
actually tracks it.

The reverse order behaves the same way: Google first, then registering with the same
email, and the row keeps `GOOGLE`.

### The case that does not auto-link

If Google ever returns an unverified email, GoTrue creates a *separate* account rather
than linking, and the `users_email_key` unique index on `lower(email)` rejects the second
row. The trigger's `on conflict do nothing` swallows it: the account exists with no
`public.users` row.

That is deliberate. Raising instead would abort the whole signup and lock the person out
of an account they just created. A missing row is visible and repairable; a failed signup
is neither. In practice Google only issues verified emails for normal consumer accounts,
so this is an edge worth knowing about rather than designing around.

## Testing

`web/lib/auth/oauth.test.ts`, grouped by acceptance criterion — the redirect it builds,
the `next` it refuses to carry off-site, and every mapped callback error.

The Supabase side of the flow is not covered by unit tests; it needs a configured project
and a real Google account. Verified manually against dev, screenshots in `/artifacts`.
