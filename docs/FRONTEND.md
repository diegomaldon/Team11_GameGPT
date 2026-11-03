# GameGPT — Frontend

Next.js 15 (App Router) + TypeScript + Tailwind CSS. Lives in `web/`. Dark
"Deep Blue Spotlight" design system (TM11-142): near-black navy ground, navy
surfaces, one cream accent, serif headings — no gradients.

## Contents
- [Routes](#routes)
- [What's live vs mocked](#whats-live-vs-mocked)
- [Design system](#design-system)
- [UI overhaul (TM11-142)](#ui-overhaul-tm11-142)
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
  `getLibrary()`, `syncLibrary()`. Base URL from `NEXT_PUBLIC_API_URL`
  (default `http://localhost:8000`). Throws `ApiError` on non-2xx.
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
