"""Title matching — joins imported library titles to `games` rows.

Ownership filtering (REQ007) only works if an imported title resolves to a
games.game_id. Storefronts and the catalogue spell the same game differently
("Portal 2™", "DOOM Eternal - Deluxe Edition", "Assassin's Creed® Unity"), so a
plain string join silently drops a large part of every library.

Match tiers, tried in order; the first tier with exactly one hit wins:

  appid       imported steam_appid == games.steam_appid
  exact       title == games.title (only surrounding whitespace trimmed)
  normalised  normalise_title(title) == normalise_title(games.title)
  edition     the title with its edition suffix removed matches the base game
              ("... Game of the Year Edition", "... - Deluxe Edition")

A tier that hits more than one row is ambiguous. That title is recorded as
unmatched with the candidate ids, never guessed. Unmatched titles are returned
for review, not dropped.

Pure Python, no DB access, so it is unit-tested offline. The DB read/write
around it lives in api/db/repositories.py and LibrarySyncService.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from uuid import UUID

# Marks that storefronts add and catalogues usually leave out. The ASCII forms
# are only stripped when bracketed, so "TR" or "R" inside a real title is kept.
_TRADEMARKS = re.compile(r"[™®©℠]|\((?:tm|r|c|sm)\)", re.IGNORECASE)
# Apostrophes are removed without a gap: "Assassin's" -> "assassins", not "assassin s".
_APOSTROPHES = re.compile(r"['‘’ʼ`´]")
_PUNCT = re.compile(r"[^\w\s]|_", flags=re.UNICODE)
_WS = re.compile(r"\s+")

# Edition words that change the SKU but not the game. Deliberately left out:
# "remastered", "remake", "hd", and so on: those are often
# separate catalogue rows, and folding them into the base game would be a false
# match. A trailing "edition", "cut" or "version" is required, so "Persona 5
# Royal" or "Final Fantasy" are never touched.
_EDITION_WORDS = (
    r"game of the year|goty|deluxe|digital|super|definitive|complete|ultimate|"
    r"gold|premium|special|standard|enhanced|anniversary|collectors|legendary|"
    r"platinum|limited|steam|directors|final|extended|expanded"
)
# Applied to the already-normalised title, so punctuation is gone and the suffix
# is just trailing words: "doom eternal deluxe edition" -> "doom eternal".
_EDITION_SUFFIX = re.compile(
    rf"\s+(?:the\s+)?(?:(?:{_EDITION_WORDS})\s+)+(?:edition|cut|version)$"
    r"|\s+(?:game of the year|goty)$"
)


def normalise_title(title: str | None) -> str:
    """Canonical comparison key for a game title.

    Unicode compatibility-folded, accents and trademark symbols removed,
    lowercase, "&" read as "and", punctuation replaced with spaces and
    whitespace collapsed. Edition suffixes are NOT removed here; see
    `strip_edition`.
    """
    if not title:
        return ""
    # Trademarks first: NFKC folds "™" into the letters "TM", which would then
    # survive as a word ("portal 2tm").
    text = _TRADEMARKS.sub("", title)
    text = _TRADEMARKS.sub("", unicodedata.normalize("NFKC", text))
    # NFKD + drop combining marks: "Pokémon" -> "Pokemon".
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    text = text.lower().replace("&", " and ")
    text = _APOSTROPHES.sub("", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def strip_edition(normalised: str) -> str:
    """Remove one trailing edition suffix from an already-normalised title.

    Returns the input unchanged when there is no suffix. Never returns an empty
    string: "Gold Edition" on its own is a title, not a suffix.
    """
    base = _EDITION_SUFFIX.sub("", normalised).strip()
    return base or normalised


@dataclass(frozen=True)
class CatalogueGame:
    game_id: UUID
    title: str
    steam_appid: int | None = None


@dataclass(frozen=True)
class ImportedTitle:
    title: str
    steam_appid: int | None = None


@dataclass(frozen=True)
class TitleMatch:
    imported: ImportedTitle
    game_id: UUID
    method: str  # 'appid' | 'exact' | 'normalised' | 'edition'


@dataclass(frozen=True)
class UnmatchedTitle:
    imported: ImportedTitle
    normalised_title: str
    reason: str  # 'no_match' | 'ambiguous' | 'blank_title'
    candidate_game_ids: tuple[UUID, ...] = ()


MATCH_METHODS = ("appid", "exact", "normalised", "edition")


@dataclass
class MatchReport:
    """Outcome of matching one import against the catalogue."""

    matched: list[TitleMatch] = field(default_factory=list)
    unmatched: list[UnmatchedTitle] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.matched) + len(self.unmatched)

    @property
    def match_rate(self) -> float:
        """Matched / total, 0..1. An empty import reports 0.0."""
        return round(len(self.matched) / self.total, 4) if self.total else 0.0

    def counts_by_method(self) -> dict[str, int]:
        counts = {m: 0 for m in MATCH_METHODS}
        for m in self.matched:
            counts[m.method] += 1
        return counts

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "matched": len(self.matched),
            "unmatched": len(self.unmatched),
            "match_rate": self.match_rate,
            "by_method": self.counts_by_method(),
        }


class TitleMatcher:
    """Index over the catalogue, built once per import."""

    def __init__(self, catalogue: Iterable[CatalogueGame]) -> None:
        self._by_appid: dict[int, list[UUID]] = {}
        self._by_exact: dict[str, list[UUID]] = {}
        self._by_norm: dict[str, list[UUID]] = {}
        self._by_base: dict[str, list[UUID]] = {}
        for game in catalogue:
            if game.steam_appid is not None:
                _add(self._by_appid, int(game.steam_appid), game.game_id)
            exact = game.title.strip()
            if not exact:
                continue
            norm = normalise_title(exact)
            _add(self._by_exact, exact, game.game_id)
            _add(self._by_norm, norm, game.game_id)
            _add(self._by_base, strip_edition(norm), game.game_id)

    def match(self, item: ImportedTitle) -> TitleMatch | UnmatchedTitle:
        if item.steam_appid is not None:
            hit = self._by_appid.get(int(item.steam_appid), [])
            if len(hit) == 1:
                return TitleMatch(item, hit[0], "appid")

        exact = (item.title or "").strip()
        norm = normalise_title(exact)
        if not norm:
            return UnmatchedTitle(item, "", "blank_title")

        for method, index, key in (
            ("exact", self._by_exact, exact),
            ("normalised", self._by_norm, norm),
        ):
            hit = index.get(key, [])
            if len(hit) == 1:
                return TitleMatch(item, hit[0], method)
            if len(hit) > 1:
                return UnmatchedTitle(item, norm, "ambiguous", tuple(hit))

        # Edition fallback. Owning any edition means owning the base game, so a
        # catalogue row whose full title IS the base wins over other editions
        # that only share it after stripping.
        base = strip_edition(norm)
        for index in (self._by_norm, self._by_base):
            hit = index.get(base, [])
            if len(hit) == 1:
                return TitleMatch(item, hit[0], "edition")
            if len(hit) > 1:
                return UnmatchedTitle(item, norm, "ambiguous", tuple(hit))

        return UnmatchedTitle(item, norm, "no_match")

    def match_all(self, items: Iterable[ImportedTitle]) -> MatchReport:
        report = MatchReport()
        for item in items:
            result = self.match(item)
            if isinstance(result, TitleMatch):
                report.matched.append(result)
            else:
                report.unmatched.append(result)
        return report


def catalogue_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[CatalogueGame]:
    """Adapt `select game_id, title, steam_appid from games` rows."""
    return [
        CatalogueGame(
            game_id=r["game_id"] if isinstance(r["game_id"], UUID) else UUID(str(r["game_id"])),
            title=r["title"] or "",
            steam_appid=r.get("steam_appid"),
        )
        for r in rows
    ]


def _add(index: dict, key: Any, game_id: UUID) -> None:
    ids = index.setdefault(key, [])
    if game_id not in ids:
        ids.append(game_id)
