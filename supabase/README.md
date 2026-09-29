# GameGPT — core database schema

Schema for the seven core tables from the CIS453 structure diagram, section 3.

## There are two copies of the same SQL. Apply ONE.

| | `sql/` | `supabase/migrations/` |
|---|---|---|
| For | pasting into the Supabase SQL Editor | `supabase db push` / `db reset` |
| Ordering | numbered filenames, run by hand | timestamp prefixes, CLI orders them |
| Use when | working against the hosted project right now | rebuilding on a clean database |

The SQL inside is **identical**. Only the filenames and the extra helper scripts differ.

> **Do not apply both to the same database.** These scripts are one-shot — no
> `if not exists` guards, no `drop policy` preambles. Applying the second set
> over the first fails immediately with `type "platform_type" already exists`.
> That's the intended behaviour; it's louder than silently double-applying.

### Not in `migrations/`, on purpose

`sql/00_reset.sql` and `sql/06_verify.sql` are deliberately excluded from the
migrations folder. The CLI applies *every* file in `migrations/` in filename
order — `00_reset.sql` would sort first and drop the entire schema before the
rest ran.

---

## Path A — hosted project, SQL Editor

Dashboard → **SQL Editor** → **New query**. Paste and run one at a time, in
order, confirming each succeeds before the next:

1. `sql/01_extensions.sql`
2. `sql/02_enums.sql`
3. `sql/03_tables.sql`
4. `sql/04_rls_and_grants.sql`

Then optionally `sql/05_seed.sql`, then `sql/06_verify.sql` (read-only).

If a script errors partway, run `sql/00_reset.sql` and start again from 01.

## Path B — clean database, CLI

Needs Docker running for the local stack.

```bash
npm install -D supabase
npx supabase login
npx supabase init                              # generates config.toml
npx supabase link --project-ref <20-char-ref>  # Project Settings > General
```

`supabase init` will offer to create `supabase/migrations/` and `supabase/seed.sql`.
Both already exist here — keep these, don't let it overwrite them.

```bash
npx supabase start       # local Postgres
npx supabase db reset    # applies migrations, then seed.sql
```

To push to the hosted project:

```bash
npx supabase db push     # applies migrations only; seed.sql is NOT run
```

Seed the hosted project by pasting `supabase/seed.sql` into the SQL Editor.

---

## Design decisions worth knowing

**`public.users` is a profile table, not a credential store.** `User4.passwordHash`
from the diagram is omitted. REQ001 puts auth under Supabase, which keeps the
hash in `auth.users.encrypted_password`. `public.users.user_id` is a FK to
`auth.users.id` with `on delete cascade`.

**`Query4.timestamp` is named `created_at`.** `timestamp` is a Postgres type
name; as a column identifier it forces quoting in every ORM downstream.

**Embedding dimension is 1536**, assuming OpenAI `text-embedding-3-small`. It
appears in `games.embedding` and `queries.embedding_vector` — change both
together. Both nullable, so swapping models later is a small migration.

**Four columns added beyond the diagram** — `steam_appid`, `igdb_id`, `rawg_id`
as upsert keys for the metadata importer (without them, a second import run
duplicates every row), and `release_date` / `developers` / `publishers` /
`header_image_url` because REQ009 and use case 2.20 promise developer and
release date in the detail panel while `Game4` has no properties for them.
That last one is a genuine gap in the structure diagram, not a preference.

**The grants in `04` are load-bearing.** Supabase stopped auto-exposing
public-schema tables to the Data API for new projects on 2026-05-30; existing
projects follow on 2026-10-30. Without those `grant` statements, tables exist
in Postgres and render fine in the Table Editor but return permission errors to
every `supabase-js` call. `grant` and RLS are separate gates — `grant` decides
whether a role can touch the table, RLS decides which rows it sees.

## ERD

`docs/schema.dbml` → paste into [dbdiagram.io](https://dbdiagram.io/d) → arrange
→ Export → PNG.

Database → **Schema Visualizer** in the dashboard is a good live cross-check,
but it renders one schema at a time, so it won't show the
`users.user_id → auth.users.id` link.
