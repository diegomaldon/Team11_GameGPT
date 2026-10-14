# TM11-52 — Linked accounts management page

Evidence for [TM11-52](https://syr-team-rxkvdczq.atlassian.net/browse/TM11-52) (REQ003).
Captured 2026-10-13 with Playwright (Chromium) against `npm run dev`. Supabase's REST
endpoint for `platform_accounts` was answered from an in-memory table kept by the test, so a
reload reads back what the page wrote. Spec: `web/e2e/linked-accounts.spec.ts`.

## Acceptance criteria

| Acceptance criterion | Evidence |
| --- | --- |
| Lists each supported platform with connected state and lastSyncedAt | `tm11-52-ac1-connected.png` — Steam "Connected · 76561197960287930 · Synced 2 h ago", Xbox and Epic "Not connected". PlayStation is listed as "Not supported yet" with Connect disabled (it has no `platform_type` value). `toLinkedAccounts` / `formatLastSynced` in `web/lib/account/linkedAccounts.ts` |
| Connect and disconnect actions per platform | `tm11-52-ac2-confirm.png` — Disconnect asks first and says imported games go too (`owned_games` cascades). Steam now saves its link (`POST /api/steam/link`); Xbox uses TM11-53's flow; Epic links by typed name (`MANUAL`). E2E: disconnect, Epic connect, and a verified Steam sign-in that imports and stamps `last_synced_at` |
| State accurate after a page refresh and with zero platforms linked | `tm11-52-ac3-zero.png` — no rows: all four platforms not connected plus "No platforms linked yet", same after a reload. E2E reloads after a disconnect and after an Epic connect and the page matches the table both times |

`tm11-52-375.png` — the card at 375 px, no horizontal scroll.

## What changed underneath

- The card read the browser-only mock store, which gave every new user a connected Steam
  account ("alexr"). It now reads `platform_accounts` through supabase-js under RLS.
- Steam linking never reached the database. The callback now seals the verified steamID64 in
  an httpOnly cookie and `POST /api/steam/link` writes the row as the signed-in user, the
  same pattern as Xbox. Details in `docs/auth-steam-openid.md`.
- `last_synced_at` was never written. The page stamps it when a Steam import succeeds,
  because the backend import runs as the dev user and can't reach this user's row.

## Tests

- Vitest: 310/310, 66 new across `steamLink`, `linkSteam`, `steamClient`, `linkedAccounts`,
  `LinkedAccountsCard`, the two Steam route handlers, and `steam.test.ts`.
- Playwright (Chromium): 6/6 in `web/e2e/linked-accounts.spec.ts`.
- pytest: 276 passed, 2 skipped (no backend changes).

## Not verified

- **Real Steam round trip and the deployed site.** Needs `STEAM_LINK_SECRET` set on the
  deployed web host and a real Steam account. Only the browser half was driven end to end.
- **RLS against hosted Supabase.** The policy `platform_accounts_own` is unchanged; the tests
  use a fake that behaves like it.
- **Safari/WebKit:** Playwright's WebKit build crashes on launch on the capture machine.
- `last_synced_at` uses the browser's clock, and only Steam has an import to stamp it.
