# GameGPT

CIS454 — Software Implementation Project. A cross-platform game-discovery app:
link your gaming accounts, describe a vibe in natural language, and get 3–5
ranked recommendations drawn from a RAG pipeline over a game knowledge base,
with the games you already own filtered out.

This repo is a **walking skeleton** — one vertical slice, end to end:

```
query box → POST /api/recommend → embed → vector top-k → drop owned → LLM ranks 3
          → persist → render cards → thumbs up/down → POST /api/feedback
```

## Layout

```
/api          FastAPI: routers/ services/ models/ db/ main.py
/web          Next.js App Router + minimal Tailwind
/scripts      seed_games.py  embed_games.py
/supabase     migrations/
/docs         ARCHITECTURE.md
```

## Run it locally (no keys required)

The skeleton runs with an empty `.env` — every external service has a fixture
or stub fallback.

```bash
cp .env.example .env

# API  (from repo root)
python -m venv .venv && . .venv/Scripts/activate   # Windows Git Bash
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000
# → http://localhost:8000/api/health

# Web  (separate terminal)
cd web
npm install
npm run dev
# → http://localhost:3000
```

## Deploy

Both providers auto-deploy from `main` once the repo is connected — no manual
step per push.

**API → Render.** New → Blueprint, point it at this repo. `render.yaml` is read
automatically. Set the `sync: false` env vars (`DATABASE_URL`, keys, `DEV_USER_ID`)
per environment under the service's *Environment* tab, and create separate
*Environment Groups* for staging vs production. Auto-deploy is on by default;
if it isn't, toggle it under *Settings → Build & Deploy → Auto-Deploy*.

> ⚠️ **Render free tier sleeps after ~15 min idle and takes ~1 min to wake.**
> That will stall a live demo. Upgrade `plan: free` → `starter` in `render.yaml`
> before the first presentation, or pick a host that doesn't cold-start.

**Web → Vercel.** Import the repo, set the **Root Directory** to `web`. Add
`NEXT_PUBLIC_API_URL` (the Render URL) as a project env var, scoped separately
to **Preview** and **Production**. Deployments from `main` are enabled in
`vercel.json`.

## Environment variables

Every var is declared in `.env.example` with an empty value. **No real secret is
ever committed.** Blank keys trigger fallbacks:

| Var | Blank behavior |
|-----|----------------|
| `ANTHROPIC_API_KEY` | LLM ranking uses a deterministic stub |
| `OPENAI_API_KEY` | Embeddings use a deterministic hashed vector |
| `STEAM_API_KEY` | `/api/library/sync` returns seeded owned-games rows |
| `RAWG_API_KEY` | `seed_games.py` reads the committed JSON fixture |
| `DATABASE_URL` | required for the full slice; see `/supabase` |
