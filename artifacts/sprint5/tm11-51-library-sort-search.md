# TM11-51 — Library sorting, search and pagination

Evidence for [TM11-51](https://syr-team-rxkvdczq.atlassian.net/browse/TM11-51).
Captured 2026-10-13 with Playwright (Chromium) against `npm run dev`, with
`GET /api/library` answered by a 1,500-game fixture plus one hand-added Xbox game
(1,501 rows). Spec: `web/e2e/library.spec.ts`.

## Acceptance criteria

| Acceptance criterion | Evidence |
| --- | --- |
| Sortable by title and playtime | Sort menu: Most played (default), Least played, Title A–Z, Title Z–A. `sortRows` in `web/lib/library/view.ts`; 5 unit tests in `view.test.ts`, page test in `page.test.tsx`, E2E `AC1 sorts by playtime and by title` |
| Title search filters client-side or server-side as documented | Client-side, documented in `docs/FRONTEND.md` → "Library sort, search & paging" (and a note under `GET /api/library` in `docs/API.md`). `tm11-51-ac2-search.png` — "game 014" narrows 1,501 rows to 10. Case, ™, accents and punctuation are ignored |
| Paginated or virtualised | Virtualised (`VirtualList`, from TM11-50). E2E `AC3` scrolls a 1,501-row library and asserts fewer than 60 rows are ever mounted; page test checks the same after a sort and a 500-match search |
| State survives navigating away and back | `tm11-51-ac4-restored.png` — set Title A–Z, Steam filter and "game 12", went to Settings through the sidebar, came back: all three restored. Also survives a reload. Saved in `sessionStorage`, key `gamegpt.library.view.v1` |

`tm11-51-375-search-sort.png` — the search box and sort menu at 375 px, no horizontal scroll.

## Why search is client-side

`GET /api/library` returns the whole library unpaged, and hand-added games exist only
in the browser's mock store. A server-side search would never see them.
If the library moves fully server-side, search and sort should move into
query parameters on `GET /api/library`, with real paging.

## Not verified

- **Safari/WebKit:** Playwright's WebKit build segfaults on launch on the capture
  machine (macOS 26), before any page loads. Only Chromium was run.
- **Deployed site:** checked on localhost only.
- **Scroll position** isn't restored on return. Only sort, search and filter are.
