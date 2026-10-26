"""Deduplication suite: an owned game is never recommended (TM11-59, REQ007).

REQ007 is absolute, so these pin the behaviour, not the implementation:

  filter_owned  what DeduplicationService drops from a list of recommendations
  TitleMatcher  which catalogue game an imported title is counted as owning

One table of real title pairs drives both, grouped the way the ticket asks:
same game on two platforms, edition mismatch, sequels that must not collapse,
and near-miss titles that are different games.

Editions are the same game (Special, GOTY, Definitive...). A remaster is hidden
from recommendations when the original is owned, because REQ007 errs on the
side of hiding. The import matcher keeps a remaster apart from the original on
purpose (see title_matching._EDITION_WORDS), so it is not folded there.

Cases today's code gets wrong are strict xfails naming TM11-57 (title
normalisation). When that fix lands they pass, and strict mode fails CI until
the marker is removed, so they turn into real guards.

The database is an in-memory owned_games table. It answers a select by the
columns it lists rather than by matching query text, so these tests don't care
how filter_owned writes its SQL.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from api.models import GameCandidate
from api.services import deduplication
from api.services.deduplication import DeduplicationService
from api.services.title_matching import (
    CatalogueGame,
    ImportedTitle,
    TitleMatch,
    TitleMatcher,
)

USER = UUID("00000000-0000-0000-0000-000000000001")
SOMEONE_ELSE = UUID("00000000-0000-0000-0000-000000000002")


# ── the fixture set ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TitlePair:
    owned: str
    candidate: str
    is_duplicate: bool
    is_remaster: bool = False  # hidden from recommendations, not folded on import

    @property
    def is_same_catalogue_game(self) -> bool:
        return self.is_duplicate and not self.is_remaster


SAME_GAME = [
    TitlePair("Hades", "Hades", True),
    TitlePair("DOOM™", "Doom", True),
    TitlePair("Counter-Strike: Global Offensive", "Counter-Strike Global Offensive", True),
    TitlePair("Baldur's Gate 3", "Baldurs Gate 3", True),
    TitlePair("Assassin’s Creed® Valhalla", "Assassin's Creed Valhalla", True),
    TitlePair("Pokémon Legends: Arceus", "Pokemon Legends: Arceus", True),
]

EDITION_MISMATCH = [
    TitlePair("The Elder Scrolls V: Skyrim Special Edition", "The Elder Scrolls V: Skyrim", True),
    TitlePair(
        "The Witcher 3: Wild Hunt - Game of the Year Edition", "The Witcher 3: Wild Hunt", True
    ),
    TitlePair("Age of Empires II: Definitive Edition", "Age of Empires II", True),
    TitlePair("Divinity: Original Sin 2 - Definitive Edition", "Divinity: Original Sin 2", True),
    TitlePair("Control Ultimate Edition", "Control", True),
    TitlePair("Grand Theft Auto V: Premium Edition", "Grand Theft Auto V", True),
    TitlePair("The Elder Scrolls V: Skyrim", "The Elder Scrolls V: Skyrim Special Edition", True),
    TitlePair("Dark Souls Remastered", "Dark Souls", True, is_remaster=True),
]

SEQUELS = [
    TitlePair("Hades", "Hades II", False),
    TitlePair("Hades II", "Hades", False),
    TitlePair("Portal", "Portal 2", False),
    TitlePair("Half-Life 2", "Half-Life 2: Episode One", False),
    TitlePair("Dark Souls", "Dark Souls II", False),
    TitlePair("Left 4 Dead", "Left 4 Dead 2", False),
    TitlePair("Borderlands 2", "Borderlands", False),
    TitlePair("The Witcher 3: Wild Hunt", "The Witcher 3: Wild Hunt - Blood and Wine", False),
]

NEAR_MISSES = [
    TitlePair("Doom", "Doom Eternal", False),
    TitlePair("Celeste", "Celeste Classic", False),
    TitlePair("Hollow Knight", "Hollow Knight: Silksong", False),
    TitlePair("Final Fantasy VII", "Final Fantasy VII Remake", False),
    TitlePair("Portal", "Portal Stories: Mel", False),
    TitlePair("Rust", "Rusty Lake: Roots", False),
    TitlePair("Marvel's Spider-Man", "Marvel's Spider-Man: Miles Morales", False),
]

GROUPS = {
    "same game": SAME_GAME,
    "edition": EDITION_MISMATCH,
    "sequel": SEQUELS,
    "near miss": NEAR_MISSES,
}

# Cases today's code gets wrong, by layer. Each one is TM11-57's to fix.
FILTER_GAPS = {
    "Baldur's Gate 3 / Baldurs Gate 3": "apostrophe becomes a space",
    "Pokémon Legends: Arceus / Pokemon Legends: Arceus": "accents are kept",
    "The Elder Scrolls V: Skyrim Special Edition / The Elder Scrolls V: Skyrim": "no editions",
    "The Witcher 3: Wild Hunt - Game of the Year Edition / The Witcher 3: Wild Hunt": (
        "no editions"
    ),
    "Age of Empires II: Definitive Edition / Age of Empires II": "no editions",
    "Divinity: Original Sin 2 - Definitive Edition / Divinity: Original Sin 2": "no editions",
    "Control Ultimate Edition / Control": "no editions",
    "Grand Theft Auto V: Premium Edition / Grand Theft Auto V": "no editions",
    "The Elder Scrolls V: Skyrim / The Elder Scrolls V: Skyrim Special Edition": "no editions",
    "Dark Souls Remastered / Dark Souls": "no editions",
}
MATCHER_GAPS: dict[str, str] = {}


def case_id(pair: TitlePair) -> str:
    return f"{pair.owned} / {pair.candidate}"


def cases(gaps: dict[str, str]) -> list:
    """Every pair as a pytest param, with known gaps marked as strict xfails."""
    params = []
    for group, pairs in GROUPS.items():
        for pair in pairs:
            gap = gaps.get(case_id(pair))
            marks = [pytest.mark.xfail(strict=True, reason=f"TM11-57: {gap}")] if gap else []
            params.append(pytest.param(pair, id=f"{group}: {case_id(pair)}", marks=marks))
    return params


# ── an in-memory owned_games table ──────────────────────────────────────────


class OwnedGamesTable:
    """Answers a select with each of the user's rows, in the columns it lists.

    The user is the first query parameter, as in every owned_games query.
    `o.game_id` and `p.platform::text` read as game_id and platform.
    """

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self._result: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params=None):
        selected = re.search(r"select\s+(.*?)\s+from\s", str(query), re.I | re.S).group(1)
        columns = [c.strip().split(".")[-1].split("::")[0] for c in selected.split(",")]
        user = params[0]
        self._result = [
            tuple(row.get(column) for column in columns)
            for row in self.rows
            if row["user_id"] == user
        ]

    async def fetchall(self):
        return self._result


def owned_row(title=None, *, game_id=None, steam_appid=None, platform="steam", user_id=USER):
    return {
        "user_id": user_id,
        "game_id": game_id,
        "steam_appid": steam_appid,
        "title": title,
        "platform": platform,
    }


@pytest.fixture
def library(monkeypatch):
    """Point DeduplicationService at an in-memory table. Returns a setup function."""

    def use(rows: list[dict], *, shape: str = "legacy") -> None:
        table = OwnedGamesTable(rows)

        class Connection:
            def cursor(self):
                return table

        @asynccontextmanager
        async def connection():
            yield Connection()

        async def catalogue_shape():
            return shape

        monkeypatch.setattr(deduplication, "connection", connection)
        monkeypatch.setattr(deduplication, "catalogue_shape", catalogue_shape)

    return use


def candidate(title: str, *, game_id: UUID | None = None, steam_appid=None) -> GameCandidate:
    return GameCandidate(game_id=game_id or uuid4(), title=title, steam_appid=steam_appid)


async def recommendable(candidates: list[GameCandidate]) -> list[str]:
    kept = await DeduplicationService().filter_owned(USER, candidates)
    return [c.title for c in kept]


# ── filter_owned: titles (the local schema matches on appid, then title) ────


@pytest.mark.asyncio
@pytest.mark.parametrize("pair", cases(FILTER_GAPS))
async def test_an_owned_title_is_not_recommended_unless_it_is_another_game(library, pair):
    library([owned_row(pair.owned)])

    kept = await recommendable([candidate(pair.candidate)])

    assert kept == ([] if pair.is_duplicate else [pair.candidate])


@pytest.mark.asyncio
async def test_a_game_owned_on_two_platforms_is_dropped_once_and_order_is_kept(library):
    library([owned_row("Hades", platform="steam"), owned_row("Hades", platform="epic")])

    kept = await recommendable([candidate("Celeste"), candidate("Hades"), candidate("Inside")])

    assert kept == ["Celeste", "Inside"]


@pytest.mark.asyncio
async def test_the_same_appid_is_the_same_game_even_after_a_rename(library):
    library([owned_row("Counter-Strike: Global Offensive", steam_appid=730)])

    kept = await recommendable([candidate("Counter-Strike 2", steam_appid=730)])

    assert kept == []


@pytest.mark.asyncio
async def test_another_users_library_does_not_hide_anything(library):
    library([owned_row("Hades", user_id=SOMEONE_ELSE)])

    assert await recommendable([candidate("Hades")]) == ["Hades"]


@pytest.mark.asyncio
async def test_nothing_owned_keeps_every_candidate(library):
    library([])

    assert await recommendable([candidate("Hades"), candidate("Portal")]) == ["Hades", "Portal"]


@pytest.mark.asyncio
async def test_no_candidates_is_no_work(library):
    library([owned_row("Hades")])

    assert await recommendable([]) == []


# ── filter_owned: catalogue ids (the hosted schema matches on game_id) ──────


@pytest.mark.asyncio
async def test_hosted_a_game_owned_on_two_platforms_is_dropped(library):
    hades = uuid4()
    library(
        [owned_row(game_id=hades, platform="steam"), owned_row(game_id=hades, platform="xbox")],
        shape="hosted",
    )

    kept = await recommendable([candidate("Hades", game_id=hades), candidate("Celeste")])

    assert kept == ["Celeste"]


@pytest.mark.asyncio
async def test_hosted_a_sequel_is_still_recommended(library):
    hades, hades_ii = uuid4(), uuid4()
    library([owned_row(game_id=hades)], shape="hosted")

    kept = await recommendable([candidate("Hades II", game_id=hades_ii)])

    assert kept == ["Hades II"]


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="TM11-57: hosted dedup matches game_id only, so an owned edition row "
    "doesn't hide the base game's row",
)
async def test_hosted_an_owned_edition_hides_the_base_game(library):
    skyrim, skyrim_se = uuid4(), uuid4()
    library([owned_row("The Elder Scrolls V: Skyrim Special Edition", game_id=skyrim_se)],
            shape="hosted")

    kept = await recommendable([candidate("The Elder Scrolls V: Skyrim", game_id=skyrim)])

    assert kept == []


@pytest.mark.asyncio
async def test_hosted_another_users_library_does_not_hide_anything(library):
    hades = uuid4()
    library([owned_row(game_id=hades, user_id=SOMEONE_ELSE)], shape="hosted")

    assert await recommendable([candidate("Hades", game_id=hades)]) == ["Hades"]


# ── TitleMatcher: which catalogue game an import counts as owning ───────────


@pytest.mark.parametrize("pair", cases(MATCHER_GAPS))
def test_an_import_matches_a_catalogue_game_only_if_it_is_that_game(pair):
    game = CatalogueGame(game_id=uuid4(), title=pair.candidate)

    result = TitleMatcher([game]).match(ImportedTitle(pair.owned))

    is_match = isinstance(result, TitleMatch) and result.game_id == game.game_id
    assert is_match == pair.is_same_catalogue_game


def test_an_import_picks_the_original_over_its_sequel():
    hades, hades_ii = (CatalogueGame(uuid4(), t) for t in ("Hades", "Hades II"))
    matcher = TitleMatcher([hades, hades_ii])

    assert matcher.match(ImportedTitle("HADES™")).game_id == hades.game_id
    assert matcher.match(ImportedTitle("Hades II")).game_id == hades_ii.game_id
