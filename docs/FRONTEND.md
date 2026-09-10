# GameGPT — Frontend

Next.js 15 (App Router) + TypeScript + Tailwind CSS. Lives in `web/`. Clean,
modern, light design system with one solid indigo accent — no gradients.

## Contents
- [Routes](#routes)
- [What's live vs mocked](#whats-live-vs-mocked)
- [Design system](#design-system)
- [Structure](#structure)
- [API client & types](#api-client--types)
- [Mock store](#mock-store)
- [Fixture mode](#fixture-mode-run-without-an-api)
- [Commands](#commands)

---

## Routes

| Route | File | Purpose |
|-------|------|---------|
| `/signin` | `app/signin/page.tsx` | Demo sign-in (Google/email, simulated) |
| `/` | `app/(app)/page.tsx` | **Discover** — query box, ranked cards, 👍/👎 |
| `/library` | `app/(app)/library/page.tsx` | Owned games, platform filters, manual **Add game** |
| `/settings` | `app/(app)/settings/page.tsx` | Profile, linked accounts, preferences, danger zone |

`(app)` is a route group (no URL segment). Its `layout.tsx` wraps the three
authenticated pages in `AppShell` (desktop sidebar + mobile bottom nav) and
redirects to `/signin` when signed out.

---

## What's live vs mocked

| Feature | Backing |
|---------|---------|
| **Discover** (recommend + feedback) | 🟢 **Live** — calls the real API at `NEXT_PUBLIC_API_URL` |
| Sign-in / sign-out | 🟡 Mock — sets a flag in `localStorage` |
| Library (list / add / remove) | 🟡 Mock — `localStorage` store |
| Linked accounts (Steam/Xbox/Epic/PlayStation) | 🟡 Mock — simulated connect flow |
| Profile / preferences | 🟡 Mock — `localStorage` store |

The mock exists to demonstrate the **full product UI** without an auth/accounts
backend (out of scope for the skeleton). Only Discover exercises the RAG slice.

---

## Design system

- **Type:** Space Grotesk (display) + Inter (body), via `next/font` (self-hosted).
- **Color:** near-black primary (`--ink`), one solid indigo accent
  (`accent.600 = #4f46e5`), white surfaces on an off-white page. Tokens in
  `app/globals.css` + `tailwind.config.ts`.
- **Icons:** inline Lucide-style SVGs in `components/icons.tsx` (no emoji as UI).
  Platform glyphs are simplified stylized marks, **not** official brand assets.
- **Primitives:** `components/ui.tsx` — `Button`, `Card`, `Field`, `TextInput`,
  `Select`, `Toggle`, `Modal`, `Badge`, `Avatar`, `EmptyState`, `PageHeader`.
- **A11y/responsive:** `focus-visible` rings, `aria-pressed`/`role="switch"`,
  `prefers-reduced-motion`, 44px touch targets, `min-h-dvh`, works at 375px.

---

## Structure

```
web/
  app/
    layout.tsx            root: fonts, <Providers>, metadata, viewport
    providers.tsx         wraps the app in <MockProvider>
    globals.css           tokens, base styles, shimmer, reduced-motion
    signin/page.tsx       standalone sign-in (no shell)
    (app)/
      layout.tsx          AppShell wrapper + auth gate
      page.tsx            Discover
      library/page.tsx    Library
      settings/page.tsx   Settings
  components/
    AppShell.tsx          sidebar + mobile bottom nav + account chip
    ui.tsx                UI primitives
    icons.tsx             SVG icon set (incl. platform glyphs)
  lib/
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

---

## Fixture mode (run without an API)

Set `NEXT_PUBLIC_USE_FIXTURES=1` (e.g. in `web/.env.local`) and every client call
resolves against canned data in `lib/api/fixtures.ts` — `npm run dev` works fully
standalone, still simulating the ~1.5 s recommend latency. Unset it to hit the
real API.

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
