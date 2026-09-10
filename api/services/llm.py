"""LLMService — ranks candidates into explained recommendations.

SysML block: LLM. Anthropic call with structured JSON out, validated against
the Recommendation model, one retry on parse failure. With no API key, Agent B's
implementation falls back to a deterministic ranking so the slice runs offline.
"""

from __future__ import annotations

import json

from api.config import get_settings
from api.models import GameCandidate, Recommendation

_UNSET = object()


def _synthesize_reason(query: str, candidate: GameCandidate) -> str:
    """A non-empty explanation that references the query and the game's traits."""
    traits = candidate.genres or candidate.tags
    if traits:
        trait_text = ", ".join(traits[:3])
        return (
            f"A strong match for \"{query}\": {candidate.title} is a "
            f"{trait_text} game that fits what you're looking for."
        )
    return (
        f"A strong match for \"{query}\": {candidate.title} lines up well "
        f"with what you're looking for."
    )


def _deterministic_rank(
    query: str, candidates: list[GameCandidate], n: int
) -> list[Recommendation]:
    """Take the first `n` (already similarity-ordered) candidates, rank 1..n."""
    recs: list[Recommendation] = []
    for i, c in enumerate(candidates[:n]):
        recs.append(
            Recommendation(
                rank=i + 1,
                game_id=c.game_id,
                title=c.title,
                reason=_synthesize_reason(query, c),
                steam_appid=c.steam_appid,
                review_score=c.review_score,
            )
        )
    return recs


def _extract_json(text: str) -> str:
    """Pull the outermost JSON object out of a model response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in model response")
    return text[start:end + 1]


class LLMService:
    def __init__(self, *, api_key=_UNSET, model=_UNSET) -> None:
        settings = get_settings()
        self._api_key = settings.anthropic_api_key if api_key is _UNSET else api_key
        self._model = settings.anthropic_model if model is _UNSET else model
        self._client = None  # lazily constructed AsyncAnthropic

    @property
    def offline(self) -> bool:
        return not self._api_key

    def _anthropic(self):
        if self._client is None:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def rank(
        self, query: str, candidates: list[GameCandidate], n: int = 3
    ) -> list[Recommendation]:
        """Pick and rank the best `n` candidates for `query`.

        Returns exactly-ranked Recommendations (rank 1..n) each with a
        non-empty `reason`.
        """
        if not candidates:
            return []
        if self.offline:
            return _deterministic_rank(query, candidates, n)

        # Real Anthropic path: one attempt + one retry on parse/validation
        # failure, then fall back to the deterministic ranker so the slice
        # always yields valid, non-empty output.
        for _ in range(2):
            try:
                return await self._rank_with_llm(query, candidates, n)
            except Exception:
                continue
        return _deterministic_rank(query, candidates, n)

    async def _rank_with_llm(
        self, query: str, candidates: list[GameCandidate], n: int
    ) -> list[Recommendation]:
        pool = candidates[: max(n * 4, n)]
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
        want = min(n, len(pool))
        system = (
            "You are a game recommendation engine. Rank the candidate games by "
            "how well they fit the user's query. Respond with ONLY a JSON object, "
            "no prose."
        )
        user = (
            f"Query: {query}\n\n"
            f"Candidates (JSON):\n{json.dumps(catalog)}\n\n"
            f"Return a JSON object of the form "
            f'{{"recommendations": [{{"index": <int>, "reason": <string>}}]}} '
            f"with exactly {want} entries, best match first. `index` must be one "
            f"of the candidate indices above; `reason` must be a short, non-empty "
            f"explanation that references the query."
        )

        response = await self._anthropic().messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        data = json.loads(_extract_json(text))
        picks = data["recommendations"]
        if not isinstance(picks, list) or not picks:
            raise ValueError("empty or malformed recommendations")

        recs: list[Recommendation] = []
        seen: set[int] = set()
        for pick in picks[:n]:
            idx = int(pick["index"])
            if idx < 0 or idx >= len(pool) or idx in seen:
                continue
            seen.add(idx)
            c = pool[idx]
            reason = str(pick.get("reason") or "").strip()
            if not reason:
                reason = _synthesize_reason(query, c)
            recs.append(
                Recommendation(
                    rank=len(recs) + 1,
                    game_id=c.game_id,
                    title=c.title,
                    reason=reason,
                    steam_appid=c.steam_appid,
                    review_score=c.review_score,
                )
            )
        if not recs:
            raise ValueError("no valid recommendations parsed")
        return recs
