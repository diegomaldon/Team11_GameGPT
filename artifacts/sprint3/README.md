# Sprint 3 — Account deletion with full data cascade

Evidence for [TM11-31](https://syr-team-rxkvdczq.atlassian.net/browse/TM11-31) (REQ005).
Captured 2026-09-29 against the GameGPT Supabase project, signed in with a real Google
account. The account deleted below was a real one; the user id throughout is
`33bf52f3-2dd0-4a46-8290-b789b6e51572`.

## Acceptance criteria

| Acceptance criterion | Evidence |
| --- | --- |
| Settings action with explicit confirmation | `tm11-31-ac1-confirm-modal.png` — the modal with `delet` typed and **Delete everything** still disabled. The button only enables on an exact `DELETE`, so a mis-click cannot destroy an account |
| Removes user, platform accounts, owned games, queries, recommendations and feedback | `tm11-31-ac4-footprint-before.png` → `tm11-31-ac4-footprint-after.png` — every table drops to 0 |
| | `tm11-31-ac2-signed-out.png` — the app itself, back at sign-in with the session gone |
| Platform tokens revoked where the provider allows | `docs/account-deletion.md` → "Token revocation by provider", plus `web/lib/account/revoke.test.ts` (9 tests). No screenshot: Steam issues no token to revoke and Xbox publishes no revocation endpoint, so there is nothing visible to capture |
| Verified by querying every table for the deleted user id | The two footprint screenshots. Same query, same uuid, taken either side of the deletion |

## Reading the footprint screenshots

`public.account_data_footprint(uuid)` returns one row per table that can hold user data.
Both screenshots show the query text above the results, so the pair is self-contained:
same function, same id, before and after.

Before — 7 of 8 tables hold a row:

```
auth.users                     1
public.owned_games             1
public.platform_accounts       1
public.queries                 1
public.recommendation_feedback 1
public.recommendations         1
public.user_profiles           0
public.users                   1
```

After — all 8 are zero.

Two notes on that "before" column, so the numbers are not read as more than they are:

- **The rows were seeded by hand.** `NEXT_PUBLIC_USE_FIXTURES=1` runs the frontend on
  canned game data, so browsing the app writes nothing to Postgres. One row per table was
  inserted directly before the capture. Without it the comparison would be 0 → 0 and would
  demonstrate nothing.
- **`public.user_profiles` reads 0 on both sides.** That row was never provisioned for this
  account — a gap in the Sprint 2 signup trigger, not a deletion failure. The function still
  checks the table, which is the point of querying all of them rather than the ones expected
  to be populated.

## AC2 screenshot

`tm11-31-ac2-signed-out.png` shows `localhost:3000/signin?next=%2Fsettings`. That URL is
itself evidence: after `delete_my_account()` ran, the orphaned session was cleared and
`<RequireAuth>` bounced the now-unauthenticated `/settings` visit back to sign-in with a
return path — the protected-route guard from TM11-27 behaving correctly against a user that
no longer exists.

## Known gaps

- The access token minted before deletion stays cryptographically valid until it expires.
  Supabase has no server-side revocation list. Covered in `docs/account-deletion.md`.
- The **Linked accounts** card in `tm11-31-ac1-confirm-modal.png` still renders mock
  platform data (Steam shown as connected to `alexr`). That card is TM11-45, a separate
  ticket, and is unrelated to what this screenshot is evidence of.

## Related

- Migration: `supabase/migrations/20260928120000_account_deletion.sql`
- Write-up: `docs/account-deletion.md`
- Tests: `web/lib/account/delete.test.ts` (12), `web/lib/account/revoke.test.ts` (9)
