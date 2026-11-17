"""LLMService — ranks candidates into explained recommendations.

SysML block: LLM. Prefers Google Gemini (structured JSON out), then Anthropic,
then a deterministic offline ranking. Each real provider gets one retry on a
parse/validation failure; if every provider fails the deterministic ranker
guarantees valid, non-empty output so the slice never dead-ends.

TM11-69 (REQ015): a ranking is always 3 to 5 games, the same range the
recommendations table's rank check allows. Every pick is checked against the
candidates the model was shown: a title that isn't among them is dropped and
logged, and the list is topped up from the unpicked candidates, so the output
never names a game retrieval didn't return. Each result carries the
generated_at of the call that produced it, alongside its rank and explanation,
which are the columns of a recommendations row.

Token usage is logged for every provider attempt (`llm.usage`), including one
whose answer then fails to parse, since those tokens were still spent. One
`llm.ranked` line per call says which provider answered and the call's total.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from api.config import get_settings
from api.models import GameCandidate, Recommendation
from api.observability.upstream import raise_for_status_safe

log = logging.getLogger("gamegpt.llm")

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

# Rejected titles are model output; cap what one log line can carry.
MAX_LOGGED_TITLE_CHARS = 100

# A sentence ends at . ! or ? (optionally followed by a closing quote or bracket)
# and then whitespace. Good enough for short English explanations.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"')\]])\s+")

# A full stop after one of these doesn't end the sentence ("Inspired by Mr. Robot."),
# so the split is undone there. "etc." and "no." are left out: in an explanation
# they end a sentence as often as not. Initials ("J. R. R.", "U.S.") count too.
_ABBREVIATIONS = frozenset(
    "mr mrs ms dr prof st jr sr vs vol ft mt e.g i.e approx".split()
)
_INITIALS = re.compile(r"^(?:[A-Za-z]\.)+$")


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


def _ends_with_abbreviation(part: str) -> bool:
    last_word = part.rsplit(" ", 1)[-1]
    return last_word.lower().rstrip(".") in _ABBREVIATIONS or bool(_INITIALS.match(last_word))


def _split_sentences(text: str) -> list[str]:
    """Split on sentence ends, rejoining a split made after an abbreviation."""
    sentences: list[str] = []
    for part in _SENTENCE_END.split(text):
        if not part:
            continue
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {part}"
        else:
            sentences.append(part)
    return sentences


def normalise_explanation(text: str) -> str:
    """Collapse whitespace and keep at most two sentences (TM11-69 AC-01).

    A full stop after a common abbreviation or an initial doesn't count as a
    sentence end. Returns "" for blank input so the caller can substitute a
    synthesized reason.
    """
    flat = " ".join(str(text).split())
    if not flat:
        return ""
    sentences = _split_sentences(flat)
    kept = " ".join(sentences[:MAX_EXPLANATION_SENTENCES])
    if len(kept) > MAX_EXPLANATION_CHARS:
        cut = kept[:MAX_EXPLANATION_CHARS].rsplit(" ", 1)[0].rstrip(",;:-")
        kept = cut + "…"
    return kept


def _to_recommendation(rank: int, c: GameCandidate, reason: str) -> Recommendation:
    return Recommendation(
        rank=rank,
        game_id=c.game_id,
        title=c.title,
        reason=reason,
        steam_appid=c.steam_appid,
        review_score=c.review_score,
    )


def _deterministic_rank(
    query: str, candidates: list[GameCandidate], n: int
) -> list[Recommendation]:
    """Take the first `n` (already similarity-ordered) candidates, rank 1..n."""
    return [
        _to_recommendation(i + 1, c, _synthesize_reason(query, c))
        for i, c in enumerate(candidates[:n])
    ]


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


def _title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def _as_index(value: object) -> int | None:
    """An int index, or None. Rejects bools and non-numeric strings."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _resolve_pick(pick: object, pool: list[GameCandidate]) -> int | None:
    """Which candidate a pick means, or None if it isn't one of them (AC-03).

    The title is the stronger signal: a model that copies the wrong index next
    to a real title still meant that title. A title that matches no candidate
    is a game the model made up or remembered, and is rejected even if its
    index is valid, since its explanation is about a different game.
    """
    if not isinstance(pick, dict):
        return None
    idx = _as_index(pick.get("index"))
    in_range = idx is not None and 0 <= idx < len(pool)
    title = pick.get("title")
    if isinstance(title, str) and title.strip():
        key = _title_key(title)
        if in_range and _title_key(pool[idx].title) == key:
            return idx
        for i, c in enumerate(pool):
            if _title_key(c.title) == key:
                return i
        return None
    return idx if in_range else None


def _in_model_order(picks: list) -> list:
    """The picks sorted by the model's `rank` when every pick has one, else as listed."""
    ranks = [_as_index(p.get("rank")) if isinstance(p, dict) else None for p in picks]
    if all(r is not None for r in ranks):
        return [p for _, p in sorted(zip(ranks, picks), key=lambda pair: pair[0])]
    return picks


def _picks_to_recs(
    data: dict, pool: list[GameCandidate], query: str, n: int
) -> list[Recommendation]:
    """Turn the model's JSON into ranked Recommendations drawn only from `pool`.

    Raises ValueError when nothing usable came back, so the caller retries.
    When some picks survive but fewer than asked, the rest are filled from the
    unpicked candidates in retrieval order (TM11-69 AC-03).
    """
    picks = data.get("recommendations") if isinstance(data, dict) else None
    if not isinstance(picks, list) or not picks:
        raise ValueError("empty or malformed recommendations")
    want = min(n, len(pool))

    chosen: list[tuple[int, str]] = []
    seen: set[int] = set()
    rejected: list[str] = []
    for pick in _in_model_order(picks):
        if len(chosen) == want:
            break
        idx = _resolve_pick(pick, pool)
        if idx is None:
            title = pick.get("title", "") if isinstance(pick, dict) else ""
            rejected.append(str(title)[:MAX_LOGGED_TITLE_CHARS])
            continue
        if idx in seen:
            continue
        seen.add(idx)
        explanation = pick.get("explanation") or pick.get("reason")
        if not isinstance(explanation, str):
            explanation = ""  # a list or number would render as junk; synthesize instead
        chosen.append((idx, normalise_explanation(explanation)))

    if rejected:
        log.warning(
            "llm.picks_rejected",
            extra={"rejected_count": len(rejected), "rejected_titles": rejected[:5]},
        )
    if not chosen:
        raise ValueError("no recommendation matched a retrieved candidate")

    filled = 0
    for i in range(len(pool)):
        if len(chosen) == want:
            break
        if i not in seen:
            seen.add(i)
            chosen.append((i, ""))
            filled += 1
    if filled:
        log.info("llm.picks_filled", extra={"filled_count": filled})

    return [
        _to_recommendation(rank, pool[idx], reason or _synthesize_reason(query, pool[idx]))
        for rank, (idx, reason) in enumerate(chosen, start=1)
    ]


@dataclass
class _UsageTally:
    """Token counts across every attempt of one rank() call (TM11-69 AC-04)."""

    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def record(
        self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None
    ) -> None:
        self.attempts += 1
        input_tokens = input_tokens or 0
        output_tokens = output_tokens or 0
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        fields = {
            "provider": provider,
            "model": model,
            "attempt": self.attempts,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        log.info("llm.usage", extra=fields)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def _stamp(recs: list[Recommendation]) -> list[Recommendation]:
    """Give one call's results the same generated_at (TM11-69 AC-02)."""
    generated_at = datetime.now(timezone.utc)
    return [r.model_copy(update={"generated_at": generated_at}) for r in recs]


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
            providers.append(("gemini", self._rank_with_gemini))
        if self._anthropic_key:
            providers.append(("anthropic", self._rank_with_anthropic))

        tally = _UsageTally()
        for name, provider in providers:
            for _ in range(2):  # one attempt + one retry
                try:
                    recs = await provider(query, candidates, n, tally=tally)
                except Exception as exc:
                    # Type only: an httpx or SDK message can carry the request URL.
                    log.warning(
                        "llm.attempt_failed",
                        extra={"provider": name, "error_type": type(exc).__name__},
                    )
                    continue
                self._log_ranked(name, tally, len(recs))
                return _stamp(recs)
        recs = _deterministic_rank(query, candidates, n)
        self._log_ranked("deterministic", tally, len(recs))
        return _stamp(recs)

    @staticmethod
    def _log_ranked(provider: str, tally: _UsageTally, result_count: int) -> None:
        log.info(
            "llm.ranked",
            extra={
                "provider": provider,
                "attempts": tally.attempts,
                "result_count": result_count,
                "input_tokens": tally.input_tokens,
                "output_tokens": tally.output_tokens,
                "total_tokens": tally.total_tokens,
            },
        )

    # ── Gemini (preferred) ──
    async def _rank_with_gemini(
        self, query: str, candidates: list[GameCandidate], n: int, *, tally: _UsageTally
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
        usage = body.get("usageMetadata") or {}
        tally.record(
            "gemini", self._gemini_model,
            usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
        )
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
        self, query: str, candidates: list[GameCandidate], n: int, *, tally: _UsageTally
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
        usage = getattr(response, "usage", None)
        tally.record(
            "anthropic", self._anthropic_model,
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
        )
        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        data = json.loads(_extract_json(text))
        return _picks_to_recs(data, pool, query, n)
