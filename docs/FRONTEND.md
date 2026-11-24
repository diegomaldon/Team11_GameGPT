# GameGPT — Frontend

Next.js 15 (App Router) + TypeScript + Tailwind CSS. Lives in `web/`. Dark
"Deep Blue Spotlight" design system (TM11-142): near-black navy ground, navy
surfaces, one cream accent, serif headings — no gradients.

## Contents
- [Routes](#routes)
- [What's live vs mocked](#whats-live-vs-mocked)
- [Design system](#design-system)
- [UI overhaul (TM11-142)](#ui-overhaul-tm11-142)
- [Search input (TM11-74)](#search-input-tm11-74)
- [Loading states (TM11-76)](#loading-states-tm11-76)
- [No-results and error states (TM11-77)](#no-results-and-error-states-tm11-77)
- [Result cards (TM11-75)](#result-cards-tm11-75)
- [Game detail panel (TM11-78)](#game-detail-panel-tm11-78)
- [Structure](#structure)
- [API client & types](#api-client--types)
- [Mock store](#mock-store)
- [Library sort, search & paging](#library-sort-search--paging)
- [Fixture mode](#fixture-mode-run-without-an-api)
- [Commands](#commands)

---

## Routes

| Route | File | Purpose |
|-------|------|---------|
| `/signin` | `app/signin/page.tsx` | Sign-in (Google, email and password) on the cover-wall split layout |
| `/register` | `app/register/page.tsx` | Email registration, same split layout |
| `/` | `app/(app)/page.tsx` | **Discover** — featured spotlight, popular strip, "Describe a vibe" with grouped prompts, ranked picks with cover art, 👍/👎 |
| `/library` | `app/(app)/library/page.tsx` | Owned games as a cover grid, title search, sort, platform filters, manual **Add game**, CSV import, Refresh |
| `/settings` | `app/(app)/settings/page.tsx` | Profile, linked accounts (`components/account/LinkedAccountsCard.tsx`), preferences, danger zone |

`(app)` is a route group (no URL segment). Its `layout.tsx` wraps the three
authenticated pages in `AppShell` (header with the centred pill navigation and
the account button) and redirects to `/signin` when signed out.

---

## What's live vs mocked

| Feature | Backing |
|---------|---------|
| **Discover** (recommend + feedback) | 🟢 **Live** — calls the real API at `NEXT_PUBLIC_API_URL` |
| **Game detail panel** and recent searches | 🟢 **Live** — `GET /api/games/{game_id}` and `GET /api/history` (TM11-78) |
| Sign-in / sign-out | 🟡 Mock — sets a flag in `localStorage` |
| Library (list / add / remove) | 🟡 Mock — `localStorage` store |
| Linked accounts (Steam/Xbox/Epic/PlayStation) | 🟢 **Live** — `platform_accounts` via supabase-js, under RLS (TM11-52). Steam and Xbox sign in for real; Epic links by typed account name; PlayStation is shown but can't be linked (no `platform_type` value) |
| Profile / preferences | 🟡 Mock — `localStorage` store |

The mock exists to demonstrate the **full product UI** without an auth/accounts
backend (out of scope for the skeleton). Only Discover exercises the RAG slice.

---

## Design system

- **Type:** DM Serif Display for headings (`font-display`, one weight; faux bold is
  switched off) and DM Sans for everything else, via `next/font` (self-hosted).
- **Colour:** one set of tokens in `app/globals.css`. Components use them as
  `bg-[var(--surface)]`, `text-[var(--ink-faint)]` and so on.

  | Token | Value | Used for |
  |---|---|---|
  | `--bg` | `#050a18` | Page ground, inputs inside cards |
  | `--surface` | `#0a1430` | Cards, panels, the header pill |
  | `--raised` / `--raised-2` | `#0f1c3d` / `#13234a` | Hover, selected filter, chips |
  | `--border` / `--border-strong` | `#1c2c58` / `#2a3c70` | Card edges / secondary buttons (decorative: the text inside carries the meaning) |
  | `--border-input` | `#5a6ea3` | Edges of inputs, selects, the search bar and the off toggle. 3.6:1 on `--surface` and 4:1 on `--bg`, so a control's boundary passes WCAG 1.4.11 |
  | `--ink` / `--ink-soft` / `--ink-faint` | `#e8e1d0` / `#c4cadb` / `#a3acc6` | Body text, from strongest to quietest. `--ink-faint` is still 7:1 on `--surface` |
  | `--heading` | `#f1e7d0` | Serif headings |
  | `--label` | `#cfc3a6` | Form labels, small-caps eyebrows, platform badges |
  | `--accent` / `--accent-hover` | `#f1e7d0` / `#fff4dd` | Primary buttons, active nav tab, focus ring |
  | `--on-accent` | `#050a18` | Text on a cream fill |

- **Tailwind palettes:** `tailwind.config.ts` redefines `neutral`, `accent`, `rose`,
  `red`, `emerald` and `amber` for the dark ground. Low numbers are navy tints and high
  numbers are light inks, so an existing class such as `bg-neutral-100` or
  `bg-rose-50 text-rose-700` still reads correctly. Prefer the tokens for new code.
- **Shape:** buttons, inputs and chips are pills (`rounded-full`); cards are
  `rounded-3xl` with a 1px border and no shadow.
- **Icons:** inline Lucide-style SVGs in `components/icons.tsx` (no emoji as UI).
  Platform glyphs are simplified stylized marks, **not** official brand assets.
- **Game art:** `components/discover/GameArt.tsx` loads Steam art by app id from
  `shared.akamai.steamstatic.com` (allowed in `next.config.mjs`) and falls back to an
  initials tile when there is no app id or the image fails.
- **Primitives:** `components/ui.tsx` — `Button`, `Card`, `Field`, `TextInput`,
  `Select`, `Toggle`, `Modal`, `Badge`, `Avatar`, `EmptyState`, `PageHeader`.
- **A11y/responsive:** cream `focus-visible` rings, `aria-pressed`/`role="switch"`,
  `prefers-reduced-motion` (stops the spotlight and the cover wall), a Pause button
  on the spotlight (WCAG 2.2.2), 44px touch targets, `min-h-dvh`, works at 375px.

---

## UI overhaul (TM11-142)

What changed, page by page. Screenshots of every page before and after, at 1440px
and 375px, are in [`artifacts/sprint8/tm11-142/`](../artifacts/sprint8/tm11-142/README.md).

| Area | Before | After |
|---|---|---|
| Theme | Light: off-white page, white cards, indigo accent, Space Grotesk + Inter | Dark navy ground and surfaces, cream accent, DM Serif Display + DM Sans |
| Navigation | Left sidebar on desktop; top bar and bottom tab bar on phones | One header: wordmark, centred Discover · Library · Settings pill, account button with the user's name (opens email, Account settings, Sign out). On phones the pill takes its own row |
| Discover | Heading, query box, four example prompts, ranked text cards | Rotating spotlight of featured games with Steam key art, a scrolling strip of popular covers, "Describe a vibe" with prompts grouped by mood, genre, a game you love and platform, then ranked picks with cover art |
| Sign in / Register | Centred card | Split layout: scrolling wall of game covers on the left (hidden below 768px), form on the right. Sign-in heading is now "Welcome back." |
| Library | One-line rows with initials | Cover-art grid (`components/library/VirtualGrid.tsx`), still virtualised so a 1,500-game library mounts only a window of cards; platform filters as a pill group |
| Settings | Narrow cards | Full-width cards with serif section headings; same profile, linked accounts, preferences and account actions |

Behaviour is unchanged: recommend and feedback, sign-in and registration, library
import, search, sort, filters and Refresh, and every Settings action work as before.

**Not live data:** the spotlight and popular strip are a curated list of catalogue
games in `lib/discover/featured.ts`, because the API has no popularity endpoint yet.
Replace that list with an API call when one exists.

---

## Search input (TM11-74)

The "Describe a vibe" search on Discover is `components/discover/SearchBox.tsx` (REQ011).

- **Keyboard:** Enter searches, Esc clears the field, and `/` anywhere on the page
  (outside another text field) jumps to it. Enter does nothing while a search is
  running, so it can't start a second one. The field is capped at the API's 500
  characters.
- **Three example prompts** (`EXAMPLE_PROMPTS` in `lib/discover/featured.ts`): one each
  for a mood, a game you love and where you play. Clicking one **fills the field and
  focuses it** without searching, so the player can tweak it, then press Enter. These
  replace TM11-142's eight grouped prompts, which searched straight away. The
  spotlight and popular strip's "Find games like this" still search on click.
- **The searched query stays visible** above the results as "You searched for …",
  in full, not truncated. It also shows while loading ("Searching for …"), next to an
  error, and next to a TM11-66 `all_owned` notice. It doesn't change while the player
  types a new query, and **Edit this search** puts it back in the field.
- **Never blank:** if a search comes back with no results, the page shows the
  TM11-77 no-results state (see below). An API `notice` always wins over the generic
  tip (`NO_RESULTS_MESSAGE`).
- **Without the API:** run with `NEXT_PUBLIC_USE_FIXTURES=1` (see
  [Fixture mode](#fixture-mode-run-without-an-api)). The tests in
  `app/(app)/page.test.tsx` cover each acceptance criterion against the same canned
  response.

---

## Loading states (TM11-76)

A search can take up to REQ040's 10 seconds, so every async surface shows a placeholder
in the shape of what's coming (`components/Skeletons.tsx`).

| Surface | Placeholder | Progress |
|---|---|---|
| Discover search | `ResultsSkeleton`: three cards built like a result card | The heading's place holds a message from `lib/discover/searchProgress.ts` |
| Library | `LibrarySkeleton`: the toolbar's three controls and a cover grid on the page's `GRID_SHAPE` | Announced as "Loading your library…" |
| Game detail | `DetailSkeleton`: cover, title, tags and description lines, for the TM11-78 panel | Announced as "Loading game details…" |
| Library import and Refresh | Unchanged: `SyncProgress` (TM11-49) and `RefreshStatus` (TM11-60) already show per-title and per-platform progress | |

- **Search progress:** the API answers in one response, so the browser can't see which
  stage is running. The message follows the elapsed time against the API's stage budgets
  (`STAGE_BUDGET_MS`): "Reading your request…", then "Searching the catalogue…" from
  500 ms, "Ranking the best matches…" from 1,750 ms, and "This is taking longer than
  usual. Still working…" from 10 s. Each search starts it over.
- **No layout shift:** the placeholders copy the real boxes. Measured in Chromium in
  fixture mode, the library skeleton's toolbar and first card sit at the same position
  and size as the real ones at 1440px and 375px, with a layout-shift score of 0. The
  search heading and the first card start at the same place. A real card can be taller
  than its placeholder when the explanation runs long, but nothing sits below the
  results to be pushed down.
- **Detail panel:** when TM11-78 lands, match `DetailSkeleton`'s boxes to the panel's.
- The shimmer stops under `prefers-reduced-motion` (see `globals.css`).

---

## No-results and error states (TM11-77)

These follow the rainy-day scenarios from our CIS453 use cases (Search Games by Natural
Language, View Past Recommendations, View Game Details).

- **No results** (`components/discover/NoResults.tsx`): "No matches found", a tip to
  rephrase or broaden the search, and the three example queries. Picking one fills the
  search field without searching, like the examples under it. When the API sent a
  `notice` (for example TM11-66 `all_owned`), its message replaces the tip. A notice
  that comes with results (TM11-72 `ranking_degraded`) still shows above them.
- **Service unavailable** (`components/ServiceError.tsx`): a title, a message with an
  estimated retry time, and **Try again**, which re-runs the same query. The wording
  comes from `describeFailure()` in `lib/api/failureState.ts`, never from the error, so
  no host, URL or key reaches the screen.

  | Surface | Unavailable or 5xx | Timed out |
  |---|---|---|
  | Search | "Search is unavailable right now" + "Try again in about 30 seconds." | "Search timed out" + the same retry time |
  | History | "History is temporarily unavailable" + "Try again shortly." | Same, since the database already retried |
  | Detail | "Couldn't load this game's details" + "Try again in about 30 seconds." | Same |

- **Timeouts:** `request()` in `lib/api/client.ts` gives up after
  `RECOMMEND_TIMEOUT_MS` (15 s, REQ040's 10 s plus network) for recommend and
  `READ_TIMEOUT_MS` (10 s) for the library and history reads. It throws `ApiError` with
  `code = REQUEST_TIMEOUT_CODE`. Syncs, CSV uploads and feedback have no limit. A
  library read that times out shows the existing "Couldn't load your imported games"
  banner with Try again.
- **History and detail:** there's no history page (TM11-84) or detail panel (TM11-78)
  on main yet. `getHistory()` is in the client, with its time limit, and those screens
  should show `<ServiceError failure={describeFailure(err, "history" | "detail")} />`
  on a failed load, and `DetailSkeleton` while loading.
- **30 seconds** is `RETRY_ESTIMATE_SECONDS`, a fixed estimate, because the API sends no
  `Retry-After` header.
- Not done: the scenario also mentions "popular categories" next to the examples. The
  ticket's AC asks only for example queries, so they're left out.

---

## Result cards (TM11-75)

Each pick on Discover is a `components/discover/RecommendationCard.tsx` (REQ015).

- **What a card shows:** rank, cover art, title, the stores it's on (`platforms` from
  `POST /api/recommend`, labelled in the library's badge order), the review score and
  the explanation, plus the Steam link and thumbs up/down.
- **Order:** `rankedCards()` in `lib/discover/recommendations.ts` sorts by the
  pipeline's `rank`, not array order, and shows at most 5.
- **Detail panel:** the title is a button that opens `GameDetailPanel`, and so does a
  click anywhere else on the card except the Steam link and the votes (TM11-78; a big
  target on phones). Keyboard and screen-reader users still get the one title button.
  Esc or Close shuts it and focus goes back to the title. See [Game detail panel
  (TM11-78)](#game-detail-panel-tm11-78) for what the panel shows.
- **Missing data:** no art shows the title's initials (`GameArt`), no score says
  "No score yet", no platforms says "Platforms not listed", and no Steam app id drops
  the store link.
- **Size:** the card keeps TM11-142's box (84×126 art, `p-5`), which TM11-76's
  `ResultsSkeleton` is drawn to. Change both together.
- Tests: `RecommendationCard.test.tsx`, `recommendations.test.ts` and the TM11-75
  block in `app/(app)/page.test.tsx`, grouped by acceptance criterion.

---

## Game detail panel (TM11-78)

`components/discover/GameDetailPanel.tsx` (REQ009) shows one game in a wide `Modal`.

- **Where it opens:** a result card's title, a library game's cover, and any game
  under **Recent searches** on Discover (`components/discover/RecentSearches.tsx`, the
  last 3 queries from `GET /api/history`, reloaded after each search). Each surface
  hands the panel a `DetailTarget` (`lib/discover/gameDetail.ts`): the game's id,
  title and art, plus the explanation when there is one. Closing returns focus to the
  button that opened it.
- **What it shows:** fetched from `GET /api/games/{game_id}` (`getGame()` in the
  client): user and critic scores, platforms, release year, developer, which platforms
  the player owns it on, genres then up to 8 tags, the explanation ("Why it fits"),
  the description, and store links.
- **Store links** come only from the API's `purchase_links`. The contract says never
  to build one client-side, so a game without them says so.
- **Missing data:** every missing field reads **Unavailable**, faded. A game with no
  catalogue id (an unmatched import) or one the API answers 404 for shows the same
  layout with every field unavailable and a note that it isn't in the catalogue yet.
  It isn't treated as an error.
- **Loading and errors:** TM11-76's `DetailSkeleton` while the fetch runs. A failed or
  timed-out read shows TM11-77's "Couldn't load this game's details" with Try again.
- **Keyboard:** Esc closes it. The Discover search's `/` shortcut does nothing while a
  dialog is open, so it can't start a search behind the panel.
- **Not here:** page-view logging is TM11-79, ownership and availability badges are
  TM11-80, and the full history page is TM11-84.
- Tests: `GameDetailPanel.test.tsx` and `gameDetail.test.ts`, grouped by acceptance
  criterion, plus the TM11-78 blocks in `app/(app)/page.test.tsx` and
  `app/(app)/library/page.test.tsx` for each surface. API: `api/tests/test_game_detail.py`.

---

## Structure

```
web/
  app/
    layout.tsx            root: fonts, <Providers>, metadata, viewport
    providers.tsx         wraps the app in <MockProvider>
    globals.css           theme tokens, base styles, shimmer, reduced-motion
    signin/page.tsx       sign-in (AuthLayout, no shell)
    register/page.tsx     registration (AuthLayout, no shell)
    (app)/
      layout.tsx          AppShell wrapper + auth gate
      page.tsx            Discover
      library/page.tsx    Library
      settings/page.tsx   Settings
  components/
    AppShell.tsx          header: wordmark, pill nav, account menu
    ui.tsx                UI primitives
    icons.tsx             SVG icon set (incl. platform glyphs)
    auth/AuthLayout.tsx   signed-out split layout with the cover wall
    Skeletons.tsx         loading placeholders: results, library, detail (TM11-76)
    discover/             Spotlight, PopularStrip, GameArt
    library/VirtualGrid.tsx  virtualised cover grid for the library
  lib/
    discover/featured.ts  curated featured games, prompt groups, Steam art URLs
    api/                  typed client, generated types, fixtures
    mock/                 localStorage store + seed data
```

---

## API client & types

- `lib/api/client.ts` — typed fetch wrapper: `recommend()`, `sendFeedback()`,
  `getLibrary()`, `getHistory()`, `syncLibrary()`. Base URL from `NEXT_PUBLIC_API_URL`
  (default `http://localhost:8000`). Throws `ApiError` on non-2xx, and on a timeout for
  recommend, library and history (TM11-77).
- `lib/api/schema.d.ts` — generated from `openapi.json` via `npm run gen:api`
  (`openapi-typescript`). Regenerate whenever the API contract changes.
- `lib/api/types.ts` — convenience aliases over the generated schema.

---

## Mock store

`lib/mock/store.ts` is a small React context store, mirrored to `localStorage`
(key `gamegpt.mock.v1`), that stands in for auth + accounts + library:

```ts
const { state, signIn, signOut, updateProfile,
        linkAccount, unlinkAccount, addGame, removeGame,
        updatePrefs, resetAll } = useMock();
```

Seed data and types live in `lib/mock/data.ts` (dev profile, four platform
accounts, a starter library, and a small catalog for Add-game suggestions).

Since TM11-52 no page reads the store's `accounts`, `linkAccount` or `unlinkAccount`:
Settings → Linked accounts reads `platform_accounts` instead. They are left in place
until the rest of the mock store is retired.

---

## Library sort, search & paging

TM11-51. Logic in `lib/library/view.ts`; the page wires it up.

- **Search is client-side.** `GET /api/library` returns the whole library in
  one response, and hand-added games exist only in the mock store, so a
  server-side search would miss them. The title filter runs over the merged
  list from `lib/library/unified.ts`, on every keystroke, with no request.
  Matching is a substring match after `normalizeTitle`, so case, `™`/`®`,
  Latin accents, punctuation and spaces are ignored (`doom` finds `DOOM™`,
  `pokemon` finds `Pokémon`, `assassins creed` finds `Assassin's Creed`,
  `halflife` finds `Half-Life 2`). It searches within the selected platform filter.
- **Sort:** Most played (default, same order the API returns), Least played,
  Title A–Z, Title Z–A. Playtime ties fall back to A–Z. Titles compare with
  `Intl.Collator` `numeric`, so `Game 2` sorts before `Game 10`.
- **Paging:** none needed; the list is virtualised (`components/library/VirtualList.tsx`,
  TM11-50). Only rows near the viewport are mounted, so 5,000 games render
  like 20, after any sort or search.
- **Saved view:** sort, search and platform filter are saved to
  `sessionStorage` (key `gamegpt.library.view.v1`), so leaving the page and
  coming back in the same tab restores them. A new tab starts from the
  default. Each field is validated on load, and blocked storage just means
  the view isn't remembered. Scroll position isn't saved.

If the library moves server-side (real auth, no mock store), search and sort
should move with it into `GET /api/library` query params, with real paging.

---

## Fixture mode (run without an API)

Set `NEXT_PUBLIC_USE_FIXTURES=1` (e.g. in `web/.env.local`) and every client call
resolves against canned data in `lib/api/fixtures.ts` — `npm run dev` works fully
standalone, still simulating the ~1.5 s recommend latency. Unset it to hit the
real API.

Fixtures follow the contracts in [`docs/API.md`](API.md): the same fields, value
ranges and error codes (thrown as `ApiError`), so a screen built against them
works against the API. `lib/api/fixtures.test.ts` checks the ranges and codes the
generated types can't.

---

## Commands

```bash
cd web
npm install
npm run dev          # dev server on :3000
npm run build        # production build (typecheck + static generation)
npm run start        # serve the production build
npm run gen:api      # regenerate lib/api/schema.d.ts from ../openapi.json
```

Environment: `NEXT_PUBLIC_API_URL` (API base), `NEXT_PUBLIC_USE_FIXTURES` (mock).
