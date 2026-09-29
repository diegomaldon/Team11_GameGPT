# Account deletion

E2 Identity & Account Management · REQ005

A signed-in user can delete their account and everything attached to it, at any
time, from Settings.

## The cascade already existed

Every user-bearing table was declared with `on delete cascade` in
`20260915120200_create_core_tables.sql`, and both `public.users` and
`public.user_profiles` hang off `auth.users` the same way:

```
auth.users
  ├── public.user_profiles            (id)
  └── public.users                    (user_id)
        ├── public.platform_accounts  (user_id)
        │     └── public.owned_games  (platform_account_id)
        ├── public.owned_games        (user_id)
        ├── public.queries            (user_id)
        │     └── public.recommendations              (query_id)
        │           └── public.recommendation_feedback (recommendation_id)
        └── public.recommendation_feedback            (user_id)
```

Deleting one row from `auth.users` removes all of it. What was missing was a way
for a user to trigger that. The anon key cannot touch `auth.users`, and putting
the service-role key in the browser to get around that would be far worse than
the problem — it bypasses RLS for every table in the database.

## How it works

`delete_my_account()` (migration `20260928120000`) is `SECURITY DEFINER` and
takes **no arguments**. The row it deletes is chosen by `auth.uid()`, never by
anything the caller passes. A `delete_account(uuid)` signature would be one
missing authorization check away from letting any signed-in user delete anyone
else, and `SECURITY DEFINER` means that call would succeed.

It raises rather than returning quietly when `auth.uid()` is null. Without that
guard, `delete ... where id is null` deletes nothing and reports success, which
is the worst possible result for a destructive call.

`POST /api/account/delete` wraps it. The route exists because revoking platform
tokens means talking to external providers, which has no business happening from
the browser. It runs as the caller — their JWT, the anon key, RLS still on — so
no service-role key exists anywhere in this path.

Order matters: **tokens are revoked first.** Once the `auth.users` row is gone,
the `platform_accounts` rows have cascaded away and we no longer know what to
revoke.

## Token revocation, honestly

"Revoked where the provider allows" is doing real work in that criterion. The
three platforms do not behave the same way:

| Platform | Revocable | Why |
| --- | --- | --- |
| Steam | No | OpenID 2.0. Steam asserts an identity and issues no access token, so there is nothing to revoke. |
| Epic | Yes | OAuth 2.0 with a revocation endpoint. |
| Xbox | No | Microsoft identity platform has no revocation endpoint; tokens expire, or the user revokes them from their Microsoft account. |

Every linked account gets an explicit outcome — `revoked`, `no_token`,
`unsupported` (with the reason), or `failed` — and the route returns the list.
Reporting "revoked" for Steam would be a lie; silently doing nothing for Xbox
would be a different one.

**As of this sprint nothing writes `platform_accounts.access_token`.** Steam
OpenID (TM11-44) stores an identity, not a token. So in practice every outcome
today is `no_token`. The revocation path is built and tested so that it works
the moment a provider that issues tokens is wired up, rather than being
remembered later.

Revocation failures never block deletion. REQ005 says "at any time", and a
provider outage must not trap someone in an account they want gone. The token is
destroyed on our side either way — the row is deleted regardless of what the
provider says.

## Confirmation

A second click is not a decision, so the modal requires typing `DELETE`. The
check is case-sensitive (producing capitals is most of what makes the gesture
deliberate) but trims whitespace, because a trailing space from a paste is not a
reason to refuse someone.

## Verifying it worked

`account_data_footprint(uuid)` returns a row per table for one user id. Run it
before and after with the same uuid; afterwards every count must be `0`.

```sql
-- before: find the id and see where the data lives
select id, email from auth.users where email = 'you@example.com';
select * from public.account_data_footprint('<that-uuid>');

-- after deleting from Settings, same uuid
select * from public.account_data_footprint('<that-uuid>');
```

Checking the eight tables by hand invites forgetting one, which is exactly the
failure this is meant to catch. Note that `recommendations` has no `user_id` —
it hangs off `queries` — so the function joins rather than filtering directly.
Leaving it out would let orphaned rows pass the check.

The function is `SECURITY INVOKER` and has no grant to `authenticated`: run it
from the SQL editor or as the service role. One that returned per-user row
counts for an arbitrary uuid to any signed-in user would be a quiet enumeration
oracle.

## Testing

- `web/lib/account/revoke.test.ts` — per-provider behaviour, and that a failing
  or hanging provider cannot block deletion
- `web/lib/account/delete.test.ts` — confirmation matching, and that no failure
  path ever reports success

Grouped by acceptance criterion so the run output reads as a checklist. The
Postgres side needs a real database and is verified with
`account_data_footprint`; screenshots in `/artifacts`.

## Known gap

The JWT the client holds stays cryptographically valid until it expires (one
hour by default), even though the user row is gone. Every table it could reach
is empty and the refresh token died with the account, so it grants nothing — but
it is not *invalid*, and the client signs out immediately for that reason.
