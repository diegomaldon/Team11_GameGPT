"""Before and after samples of recommendation explanations (TM11-70, REQ015).

For each of the 20 TM11-63 benchmark prompts this asks the LLM to rank the same
candidates twice, once with the TM11-69 ranking prompt TM11-70 revises (PR #61)
and once with the current one, and records every reason with the checks in
api/services/explanation_quality.py. The written review of the results is
docs/explanation-quality.md.

Candidates come from the 167-game seed catalogue (scripts/fixtures/games.json),
retrieved the way the pipeline does it: the local embedding model, the query
parser, and HybridRetriever's merge at the tuned weights, so a named game and
its series are never candidates. No database is needed. Both prompts see
exactly the same candidates, so any difference is the prompt's.

Only Gemini is called, never the deterministic fallback: a reason the fallback
wrote would say nothing about the prompt. A prompt that still fails after the
retries is recorded as failed. The model runs at temperature 0.2, so a rerun
gives similar but not identical wording.

The free Gemini tier allows 20 requests a day per model and every prompt costs
two (one per version), so `--ids` runs a subset that fits. The committed
artifact covers five prompts; docs/explanation-quality.md says which and why.

Usage (repo root, venv active, GEMINI_API_KEY set):
    python scripts/eval_explanations.py
    python scripts/eval_explanations.py --ids genre-01,mood-02 --out artifacts/sprint10
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from unittest import mock
from uuid import NAMESPACE_URL, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.models import GameCandidate, Recommendation  # noqa: E402
from api.services.explanation_quality import (  # noqa: E402
    check_explanation,
    summarise,
)

ARTIFACT_NAME = "tm11-70-explanations"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "games.json"
CANDIDATES_K = 20  # what retrieval hands the LLM, as in RAGPipeline
PICKS = 3          # RAGPipeline's n
ATTEMPTS = 2
# LLMService gives Gemini 30 s, which a slower model can need for twelve
# candidates; a timed-out call still spends quota, so the script waits longer.
LLM_TIMEOUT_SECONDS = 120.0
# Seconds between calls, and the first retry's wait (it grows per attempt). Back
# to back, the free Gemini tier answers most calls with 429 or 503.
PACE_SECONDS = 5.0
BACKOFF_SECONDS = 15.0


# TM11-69's prompt (PR #61), verbatim: the ranking prompt TM11-70 revises.
_SYSTEM_BEFORE = (
    "You are GameGPT's recommendation ranker. You are given a player's request and a "
    "numbered list of candidate games retrieved from our catalogue. Choose the games "
    "that best fit the request and rank them, best first. Only choose games from the "
    "candidate list, and copy each one's index and title exactly. Never suggest a "
    "game that is not on the list. Respond with only a JSON object, no prose and no "
    "code fences."
)


def build_messages_before(query: str, pool: list[GameCandidate], want: int):
    """LLMService's prompt before TM11-70 (TM11-69's), verbatim, for the comparison."""
    catalog = [
        {
            "index": i,
            "title": c.title,
            "genres": c.genres,
            "tags": c.tags,
            "description": (c.description or "")[:300],
            "review_score": c.review_score,
        }
        for i, c in enumerate(pool)
    ]
    user = (
        f"Request: {query}\n\n"
        f"Candidates (JSON):\n{json.dumps(catalog)}\n\n"
        f"Return exactly {want} games as a JSON object of the form\n"
        '{"recommendations": [{"rank": 1, "index": <int>, "title": <string>, '
        '"explanation": <string>}]}\n'
        f"Rules:\n"
        f"- `rank` runs 1 to {want}, best match first.\n"
        f"- `index` and `title` are copied from one candidate above; each game "
        f"appears once.\n"
        f"- `explanation` is one or two sentences saying why this game fits the "
        f"request. Name something specific about the game."
    )
    return _SYSTEM_BEFORE, user


# ─────────────────────────── report (pure) ───────────────────────────


def _summary(checks) -> dict:
    s = summarise(checks)
    return {"explanations": s.explanations, "passing": s.passing,
            "using_request": s.using_request, "tag_lists": s.tag_lists,
            "with_stock_phrases": s.with_stock_phrases, "mean_words": s.mean_words}


def build_report(rows: Sequence[dict], meta: dict) -> dict:
    """Checks every reason in `rows` and summarises them per prompt version.

    Each row: {"id", "category", "prompt", "before": [pick], "after": [pick]},
    a pick being {"title", "reason", "genres", "tags"}, or a version is None when
    it failed.
    """
    out_rows = []
    checks: dict[str, list] = {"before": [], "after": []}
    top: dict[str, list] = {"before": [], "after": []}
    for row in rows:
        out = {k: row[k] for k in ("id", "category", "prompt")}
        for version in ("before", "after"):
            picks = row[version]
            if picks is None:
                out[version] = None
                continue
            scored = []
            for i, pick in enumerate(picks):
                c = check_explanation(row["prompt"], pick["reason"], pick["genres"], pick["tags"])
                checks[version].append(c)
                if i == 0:
                    top[version].append(c)
                scored.append({
                    "title": pick["title"], "reason": pick["reason"], "passes": c.passes,
                    "request_words": list(c.request_words),
                    "labels_restated": list(c.labels_restated),
                    "stock_phrases": list(c.stock_phrases), "words": c.word_count,
                })
            out[version] = scored
        out_rows.append(out)
    return {
        **meta,
        "summary": {v: {"all": _summary(checks[v]), "top_pick": _summary(top[v])}
                    for v in ("before", "after")},
        "per_query": out_rows,
    }


def _flags(pick: dict) -> str:
    flags = []
    if not pick["request_words"]:
        flags.append("no request words")
    if len(pick["labels_restated"]) >= 2:
        flags.append("labels: " + ", ".join(pick["labels_restated"]))
    if pick["stock_phrases"]:
        flags.append("stock: " + ", ".join(f'"{p}"' for p in pick["stock_phrases"]))
    return "; ".join(flags) or "pass"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(r: dict) -> str:
    def row(label: str, s: dict) -> str:
        return (f"| {label} | {s['passing']}/{s['explanations']} | "
                f"{s['using_request']}/{s['explanations']} | {s['tag_lists']} | "
                f"{s['with_stock_phrases']} | {s['mean_words']} |")

    lines = [
        "# TM11-70 explanation quality: before and after the prompt change",
        "",
        f"Run {r['run_at']} with `{r['llm_model']}` on the {r['catalogue_games']}-game seed "
        f"catalogue, against the {r['benchmark_queries']} TM11-63 benchmark prompts. Written by "
        "`scripts/eval_explanations.py`; the review is `docs/explanation-quality.md`.",
        "",
        f"Both prompts ranked the same {r['candidates_k']} candidates per prompt (local "
        f"`{r['embedding_model']}`, query parser, hybrid merge) and returned {r['picks']} "
        "picks each. **Passes** = uses a word from the request, restates fewer than two of "
        "the game's genre/tag labels, and has no stock phrase "
        "(`api/services/explanation_quality.py`).",
        "",
        "| | passes | uses the request | tag lists | stock phrases | mean words |",
        "|---|---|---|---|---|---|",
        row("Before, every pick", r["summary"]["before"]["all"]),
        row("After, every pick", r["summary"]["after"]["all"]),
        row("Before, top pick", r["summary"]["before"]["top_pick"]),
        row("After, top pick", r["summary"]["after"]["top_pick"]),
        "",
        "## Top pick per prompt",
        "",
        "| Id | Prompt | Before | After |",
        "|---|---|---|---|",
    ]
    for q in r["per_query"]:
        def show(picks):
            if not picks:
                return "*failed*"
            p = picks[0]
            return f"**{_cell(p['title'])}**: {_cell(p['reason'])} *({_flags(p)})*"
        lines.append(f"| {q['id']} | {_cell(q['prompt'])} | {show(q['before'])} | "
                     f"{show(q['after'])} |")
    lines += ["", "Every pick, with its checks, is in the `.json` next to this file."]
    return "\n".join(lines) + "\n"


# ─────────────────────────── live run ───────────────────────────


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = ast.literal_eval(value) if value.startswith("[") else [value]
    return [str(v) for v in value or []]


def load_catalogue() -> list[GameCandidate]:
    games = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out = []
    for g in games:
        score = g.get("review_score")
        appid = g.get("steam_appid")
        out.append(GameCandidate(
            game_id=uuid5(NAMESPACE_URL, f"gamegpt-seed:{g['title']}"),
            title=g["title"], description=g.get("description"),
            genres=_as_list(g.get("genres")), tags=_as_list(g.get("tags")),
            developer=g.get("developer"),
            review_score=float(score) if score not in (None, "") else None,
            steam_appid=int(appid) if appid not in (None, "") else None,
            platforms=["steam"],  # the seed catalogue is Steam's (TM11-159)
        ))
    return out


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def _rank(
    llm, llm_module, query: str, candidates: list[GameCandidate],
) -> list[Recommendation] | None:
    for attempt in range(ATTEMPTS):
        await asyncio.sleep(PACE_SECONDS)
        try:
            return await llm._rank_with_gemini(
                query, candidates, PICKS, tally=llm_module._UsageTally())
        except Exception as exc:  # noqa: BLE001 - recorded, then retried
            # UpstreamError's message has the key redacted (observability/upstream.py).
            detail = str(exc).split(" for ")[0][:80]
            print(f"  attempt {attempt + 1} failed: {type(exc).__name__}: {detail}",
                  file=sys.stderr)
            await asyncio.sleep(BACKOFF_SECONDS * (attempt + 1))
    return None


async def collect(ids: Sequence[str] = ()) -> tuple[list[dict], dict]:
    from api.services import llm as llm_module
    from api.services.embedding import STUB_MODEL_NAME, EmbeddingService
    from api.services.game_document import build_game_document
    from api.services.hybrid_retrieval import merge_and_score, metadata_filters
    from api.services.query_benchmark import load_query_benchmark
    from api.services.query_parser import TitleIndex, parse_query
    from api.services.title_matching import CatalogueGame

    real_client = httpx.AsyncClient

    def slow_client(*args, **kwargs):
        return real_client(*args, **{**kwargs, "timeout": LLM_TIMEOUT_SECONDS})

    patcher = mock.patch.object(llm_module.httpx, "AsyncClient", slow_client)
    patcher.start()
    llm = llm_module.LLMService(anthropic_api_key=None)
    if not llm._gemini_key:
        raise SystemExit("eval_explanations: GEMINI_API_KEY is not set")
    embedder = EmbeddingService()
    if embedder.model_name == STUB_MODEL_NAME:
        raise SystemExit("eval_explanations: the stub embedding can't retrieve candidates")

    catalogue = load_catalogue()
    by_id = {c.game_id: c for c in catalogue}
    docs = await embedder.embed_documents(
        [build_game_document(c.model_dump()) for c in catalogue])
    index = TitleIndex(CatalogueGame(c.game_id, c.title) for c in catalogue)
    benchmark = load_query_benchmark()
    if ids:
        unknown = set(ids) - {q.id for q in benchmark}
        if unknown:
            raise SystemExit(f"eval_explanations: no benchmark prompt {sorted(unknown)}")
        benchmark = [q for q in benchmark if q.id in ids]

    rows = []
    for q in benchmark:
        print(q.id, file=sys.stderr)
        parsed = parse_query(q.prompt, index)
        vector = (await embedder.embed_documents([q.prompt]))[0].vector
        scored = sorted(
            (c.model_copy(update={"similarity": _cosine(vector, d.vector)})
             for c, d in zip(catalogue, docs)),
            key=lambda c: -(c.similarity or 0.0))
        legs = [scored[:50]]
        filters = metadata_filters(parsed)
        if filters is not None and filters.genres:
            wanted = {g.lower() for g in filters.genres}
            legs.append([c for c in scored if wanted & {g.lower() for g in c.genres}][:50])
        candidates = [s.candidate for s in merge_and_score(legs, parsed)][:CANDIDATES_K]

        picks: dict[str, Any] = {}
        for version in ("before", "after"):
            if version == "before":
                with mock.patch.object(llm_module, "_build_messages", build_messages_before):
                    recs = await _rank(llm, llm_module, q.prompt, candidates)
            else:
                recs = await _rank(llm, llm_module, q.prompt, candidates)
            picks[version] = None if recs is None else [
                {"title": r.title, "reason": r.reason,
                 "genres": by_id[r.game_id].genres, "tags": by_id[r.game_id].tags}
                for r in recs
            ]
        rows.append({"id": q.id, "category": q.category, "prompt": q.prompt, **picks})

    meta = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "llm_model": llm._gemini_model,
        "embedding_model": embedder.model_name,
        "catalogue_games": len(catalogue),
        "benchmark_queries": len(benchmark),
        "candidates_k": CANDIDATES_K,
        "picks": PICKS,
    }
    return rows, meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("artifacts/sprint10"))
    parser.add_argument("--ids", default="",
                        help="comma-separated benchmark ids to run (default: all 20)")
    args = parser.parse_args()
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    rows, meta = asyncio.run(collect(ids))
    report = build_report(rows, meta)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{ARTIFACT_NAME}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / f"{ARTIFACT_NAME}.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
