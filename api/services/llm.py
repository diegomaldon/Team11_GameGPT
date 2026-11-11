"""LLMService — ranks candidates into explained recommendations.

SysML block: LLM. Prefers Google Gemini (structured JSON out), then Anthropic,
then a deterministic offline ranking. Each real provider gets one retry on a
parse/validation failure; if every provider fails the deterministic ranker
guarantees valid, non-empty output so the slice never dead-ends.

TM11-69 (REQ015): a ranking is always 3 to 5 games, the same range the
recommendations table's rank check allows.
"""

from __future__ import annotations

import json
import re

import httpx

from api.config import get_settings
from api.models import GameCandidate, Recommendation
from api.observability.upstream import raise_for_status_safe

_UNSET = object()

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# REQ015: "a ranked list of 3 to 5". recommendations.rank is checked 1..5 in the
# hosted schema, so a sixth result would fail the history write.
MIN_RECOMMENDATIONS = 3
MAX_RECOMMENDATIONS = 5


# AC-01 asks for one or two sentences. Models sometimes write a paragraph, so the
# parser keeps the first two. The character cap stops one run-on sentence from
# swamping a result card.
MAX_EXPLANATION_SENTENCES = 2
MAX_EXPLANATION_CHARS = 320

# A sentence ends at . ! or ? (optionally followed by a closing quote or bracket)
# and then whitespace. Good enough for short English explanations.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"')\]])\s+")


def clamp_recommendation_count(n: int) -> int:
    """Pull a requested result count into REQ015's 3-5 range."""
    return max(MIN_RECOMMENDATIONS, min(MAX_RECOMMENDATIONS, n))


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


def normalise_explanation(text: str) -> str:
    """Collapse whitespace and keep at most two sentences (TM11-69 AC-01).

    Returns "" for blank input so the caller can substitute a synthesized reason.
    """
    flat = " ".join(str(text).split())
    if not flat:
        return ""
    sentences = [part for part in _SENTENCE_END.split(flat) if part]
    kept = " ".join(sentences[:MAX_EXPLANATION_SENTENCES])
    if len(kept) > MAX_EXPLANATION_CHARS:
        cut = kept[:MAX_EXPLANATION_CHARS].rsplit(" ", 1)[0].rstrip(",;:-")
        kept = cut + "…"
    return kept


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


# The model sees each candidate by index and title and must echo both back, so
# the parser can check every pick against the set it was given (AC-03).
_SYSTEM_PROMPT = (
    "You are GameGPT's recommendation ranker. You are given a player's request and a "
    "numbered list of candidate games retrieved from our catalogue. Choose the games "
    "that best fit the request and rank them, best first. Only choose games from the "
    "candidate list, and copy each one's index and title exactly. Never suggest a "
    "game that is not on the list. Respond with only a JSON object, no prose and no "
    "code fences."
)


def _build_messages(query: str, pool: list[GameCandidate], want: int) -> tuple[str, str]:
    """The system and user prompt every provider sends (TM11-69 AC-01)."""
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
    return _SYSTEM_PROMPT, user


def _picks_to_recs(
    data: dict, pool: list[GameCandidate], query: str, n: int
) -> list[Recommendation]:
    picks = data.get("recommendations")
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
        reason = (
            normalise_explanation(pick.get("explanation") or pick.get("reason") or "")
            or _synthesize_reason(query, c)
        )
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


class LLMService:
    def __init__(
        self,
        *,
        gemini_api_key=_UNSET,
        gemini_model=_UNSET,
        anthropic_api_key=_UNSET,
        anthropic_model=_UNSET,
    ) -> None:
        s = get_settings()
        self._gemini_key = s.gemini_api_key if gemini_api_key is _UNSET else gemini_api_key
        self._gemini_model = s.gemini_model if gemini_model is _UNSET else gemini_model
        self._anthropic_key = (
            s.anthropic_api_key if anthropic_api_key is _UNSET else anthropic_api_key
        )
        self._anthropic_model = (
            s.anthropic_model if anthropic_model is _UNSET else anthropic_model
        )
        self._anthropic_client = None

    @property
    def offline(self) -> bool:
        return not self._gemini_key and not self._anthropic_key

    async def rank(
        self, query: str, candidates: list[GameCandidate], n: int = 3
    ) -> list[Recommendation]:
        """Pick and rank the best `n` candidates for `query`.

        `n` is clamped to 3-5 (REQ015). Returns Recommendations ranked 1..n, each
        with a non-empty `reason`; fewer only when there are fewer candidates.
        Falls back to a deterministic ranking if no provider succeeds.
        """
        if not candidates:
            return []
        n = clamp_recommendation_count(n)

        providers = []
        if self._gemini_key:
            providers.append(self._rank_with_gemini)
        if self._anthropic_key:
            providers.append(self._rank_with_anthropic)

        for provider in providers:
            for _ in range(2):  # one attempt + one retry
                try:
                    return await provider(query, candidates, n)
                except Exception:
                    continue
        return _deterministic_rank(query, candidates, n)

    # ── Gemini (preferred) ──
    async def _rank_with_gemini(
        self, query: str, candidates: list[GameCandidate], n: int
    ) -> list[Recommendation]:
        pool = candidates[: max(n * 4, n)]
        want = min(n, len(pool))
        system, user = _build_messages(query, pool, want)
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        url = _GEMINI_URL.format(model=self._gemini_model)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url, params={"key": self._gemini_key}, json=payload
            )
            # The key rides in the query string; raise_for_status() would put it
            # in the exception message. See observability/upstream.py.
            raise_for_status_safe(resp, "gemini")
            body = resp.json()
        text = "".join(
            part.get("text", "")
            for part in body["candidates"][0]["content"]["parts"]
        )
        data = json.loads(_extract_json(text))
        return _picks_to_recs(data, pool, query, n)

    # ── Anthropic (fallback) ──
    def _anthropic(self):
        if self._anthropic_client is None:
            from anthropic import AsyncAnthropic

            self._anthropic_client = AsyncAnthropic(api_key=self._anthropic_key)
        return self._anthropic_client

    async def _rank_with_anthropic(
        self, query: str, candidates: list[GameCandidate], n: int
    ) -> list[Recommendation]:
        pool = candidates[: max(n * 4, n)]
        want = min(n, len(pool))
        system, user = _build_messages(query, pool, want)
        response = await self._anthropic().messages.create(
            model=self._anthropic_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        data = json.loads(_extract_json(text))
        return _picks_to_recs(data, pool, query, n)
