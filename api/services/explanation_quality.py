"""Explanation quality checks for recommendation reasons (TM11-70, REQ015).

REQ015 asks for a plain-language reason a player can act on, not the game's
genre tags read back to them. These are the mechanical half of reviewing an
explanation; the judgement half is the written review in
docs/explanation-quality.md. Each reason is checked for:

  request words    words of the player's request it uses ("unwind", "Hades"):
                   a reason that shares none isn't answering the request
  labels restated  the game's own genre and tag labels it repeats ("Roguelike",
                   "story-rich"); two or more reads as a tag list
  stock phrases    filler that fits any game ("perfect match", "fits your query")

A reason passes when it uses a request word, restates fewer than two labels and
has no stock phrase. Word matching is deliberately crude (lower case, a plural
"s" dropped), so the counts compare two prompts on the same candidates rather
than grade one reason in isolation.

Pure Python, no model or database, so it is unit-tested offline. The live run
is scripts/eval_explanations.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# Restating this many of the game's own labels makes a reason a tag list.
LABELS_FOR_A_TAG_LIST = 2

STOCK_PHRASES = (
    "perfect match", "perfectly match", "perfect fit", "perfectly fit", "great choice",
    "great pick", "excellent choice", "your query", "what you're looking for", "what you are looking for",
    "fits the bill", "ticks all the boxes", "checks all the boxes", "look no further",
    "strong match", "quintessential",
)

_WORD = re.compile(r"[a-z0-9]+")
# Words that carry no request: function words and the ones every request has.
_STOPWORDS = frozenset("""
a an the and or but nor so if then than that this these those it its it's of to in on at
by for from with without about into over under after before while when where who whom
which what why how i im ive id me my we our you your youre they them their he she his her
is are was were be been being am do does did doing have has had having can could would
should will shall may might must just really very quite bit lot more most less some any
all each every other another such one ones something anything thing things want wanna
looking look like game games play playing played try get got make makes made also still
even much many way new good great
""".split())


def words(text: str) -> list[str]:
    """Lower-case content words, a plural "s" dropped: "Roguelikes" -> "roguelike"."""
    out = []
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS or len(word) < 3:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _contains_label(reason: str, label: str) -> bool:
    """Whether `label` appears in `reason` as whole words, ignoring case and hyphens."""
    flat = re.sub(r"[-_]", " ", label.lower()).strip()
    if not flat:
        return False
    pattern = r"\b" + r"[\s-]+".join(map(re.escape, flat.split())) + r"s?\b"
    return re.search(pattern, reason.lower()) is not None


@dataclass(frozen=True)
class ExplanationCheck:
    request_words: tuple[str, ...]
    labels_restated: tuple[str, ...]
    stock_phrases: tuple[str, ...]
    word_count: int

    @property
    def uses_request(self) -> bool:
        return bool(self.request_words)

    @property
    def is_tag_list(self) -> bool:
        return len(self.labels_restated) >= LABELS_FOR_A_TAG_LIST

    @property
    def passes(self) -> bool:
        return self.uses_request and not self.is_tag_list and not self.stock_phrases


def check_explanation(
    request: str, reason: str, genres: Iterable[str] = (), tags: Iterable[str] = (),
) -> ExplanationCheck:
    """The checks above for one reason given for one game."""
    wanted = set(words(request))
    used = tuple(dict.fromkeys(w for w in words(reason) if w in wanted))
    labels = tuple(dict.fromkeys(
        label for label in (*genres, *tags) if _contains_label(reason, label)))
    lowered = reason.lower().replace("’", "'")
    stock = tuple(p for p in STOCK_PHRASES if p in lowered)
    return ExplanationCheck(
        request_words=used,
        labels_restated=labels,
        stock_phrases=stock,
        word_count=len(_WORD.findall(reason.lower())),
    )


@dataclass(frozen=True)
class ExplanationSummary:
    explanations: int
    passing: int
    using_request: int
    tag_lists: int
    with_stock_phrases: int
    mean_words: float


def summarise(checks: Sequence[ExplanationCheck]) -> ExplanationSummary:
    n = len(checks)
    return ExplanationSummary(
        explanations=n,
        passing=sum(c.passes for c in checks),
        using_request=sum(c.uses_request for c in checks),
        tag_lists=sum(c.is_tag_list for c in checks),
        with_stock_phrases=sum(bool(c.stock_phrases) for c in checks),
        mean_words=round(sum(c.word_count for c in checks) / n, 1) if n else 0.0,
    )
