"""Unit tests for imported-title -> games matching.

Pure functions, no DB, no network. Covers the AC cases: punctuation, edition
suffixes and trademark symbols, plus unmatched recording and match rate.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.services.title_matching import (
    CatalogueGame,
    ImportedTitle,
    TitleMatch,
    TitleMatcher,
    UnmatchedTitle,
    catalogue_from_rows,
    normalise_title,
    strip_edition,
)

# ─────────────────────────── normalise_title ───────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # trademark symbols
        ("Portal 2™", "portal 2"),
        ("Assassin's Creed® Unity", "assassins creed unity"),
        ("Tom Clancy's Rainbow Six® Siege", "tom clancys rainbow six siege"),
        ("Minecraft©", "minecraft"),
        ("FINAL FANTASY XIV(TM)", "final fantasy xiv"),
        ("Halo (R) Infinite", "halo infinite"),
        # punctuation
        ("The Witcher 3: Wild Hunt", "the witcher 3 wild hunt"),
        ("Half-Life 2", "half life 2"),
        ("S.T.A.L.K.E.R.: Shadow of Chernobyl", "s t a l k e r shadow of chernobyl"),
        ("Baldur’s Gate 3", "baldurs gate 3"),  # curly apostrophe
        ("Ratchet & Clank", "ratchet and clank"),
        ("Hellblade: Senua's Sacrifice", "hellblade senuas sacrifice"),
        ("  DOOM   Eternal  ", "doom eternal"),
        ("NieR:Automata™", "nier automata"),
        # unicode
        ("Pokémon Legends: Arceus", "pokemon legends arceus"),
        ("ＡＢＺÛ", "abzu"),  # full-width + accent
    ],
)
def test_normalise_title(raw, expected):
    assert normalise_title(raw) == expected


def test_normalise_title_handles_none_and_blank():
    assert normalise_title(None) == ""
    assert normalise_title("   ") == ""
    assert normalise_title("™®") == ""


def test_normalise_title_keeps_bare_tm_and_r_letters():
    # Only bracketed ASCII marks are trademarks; real words survive.
    assert normalise_title("TR Racer") == "tr racer"
    assert normalise_title("Resident Evil 4") == "resident evil 4"


def test_normalised_forms_of_storefront_and_catalogue_spellings_agree():
    assert normalise_title("Assassin’s Creed® Odyssey") == normalise_title(
        "Assassin's Creed Odyssey"
    )


# ─────────────────────────── strip_edition ───────────────────────────


@pytest.mark.parametrize(
    ("raw", "base"),
    [
        ("The Witcher 3: Wild Hunt - Game of the Year Edition", "the witcher 3 wild hunt"),
        ("Fallout 4: GOTY", "fallout 4"),
        ("Fallout: New Vegas Ultimate Edition", "fallout new vegas"),
        ("DOOM Eternal - Deluxe Edition", "doom eternal"),
        ("Red Dead Redemption 2: Ultimate Edition", "red dead redemption 2"),
        ("The Elder Scrolls V: Skyrim Special Edition", "the elder scrolls v skyrim"),
        ("Borderlands 2 Game of the Year Edition", "borderlands 2"),
        ("Cyberpunk 2077 (Digital Deluxe Edition)", "cyberpunk 2077"),
        ("Death Stranding Director's Cut", "death stranding"),
        ("BioShock Infinite: The Complete Edition", "bioshock infinite"),
        ("Batman™: Arkham Knight Premium Edition", "batman arkham knight"),
        ("Divinity: Original Sin 2 - Definitive Edition", "divinity original sin 2"),
        ("Sid Meier's Civilization® VI Gold Edition", "sid meiers civilization vi"),
    ],
)
def test_strip_edition_removes_suffix(raw, base):
    assert strip_edition(normalise_title(raw)) == base


@pytest.mark.parametrize(
    "raw",
    [
        "Persona 5 Royal",              # no "edition" -> not a suffix
        "Final Fantasy VII",            # edition word not at the end
        "Dark Souls Remastered",        # remasters are separate catalogue rows
        "Resident Evil 2",
        "Gold Edition",                 # nothing would be left
    ],
)
def test_strip_edition_leaves_non_suffixes_alone(raw):
    norm = normalise_title(raw)
    assert strip_edition(norm) == norm


# ─────────────────────────── TitleMatcher ───────────────────────────


def _game(title: str, steam_appid: int | None = None) -> CatalogueGame:
    return CatalogueGame(game_id=uuid4(), title=title, steam_appid=steam_appid)


@pytest.fixture
def catalogue() -> dict[str, CatalogueGame]:
    games = [
        _game("Portal 2", 620),
        _game("The Witcher 3: Wild Hunt", 292030),
        _game("Stardew Valley"),
        _game("Assassin's Creed Unity"),
        _game("DOOM Eternal"),
        _game("The Elder Scrolls V: Skyrim"),
        _game("The Elder Scrolls V: Skyrim Special Edition"),
        _game("Dark Souls"),
        _game("Dark Souls Remastered"),
        _game("Half-Life 2"),
    ]
    return {g.title: g for g in games}


@pytest.fixture
def matcher(catalogue) -> TitleMatcher:
    return TitleMatcher(catalogue.values())


def _ok(result, expected: CatalogueGame, method: str) -> None:
    assert isinstance(result, TitleMatch), result
    assert result.game_id == expected.game_id
    assert result.method == method


def test_appid_wins_over_a_different_title(matcher, catalogue):
    result = matcher.match(ImportedTitle("Portal 2 (Beta)", steam_appid=620))
    _ok(result, catalogue["Portal 2"], "appid")


def test_unknown_appid_falls_through_to_title(matcher, catalogue):
    result = matcher.match(ImportedTitle("Stardew Valley", steam_appid=413150))
    _ok(result, catalogue["Stardew Valley"], "exact")


def test_exact_match(matcher, catalogue):
    _ok(matcher.match(ImportedTitle("Half-Life 2")), catalogue["Half-Life 2"], "exact")


def test_exact_ignores_surrounding_whitespace(matcher, catalogue):
    _ok(matcher.match(ImportedTitle("  DOOM Eternal ")), catalogue["DOOM Eternal"], "exact")


@pytest.mark.parametrize(
    ("imported", "expected"),
    [
        ("Portal 2™", "Portal 2"),
        ("PORTAL 2", "Portal 2"),
        ("Assassin's Creed® Unity", "Assassin's Creed Unity"),
        ("Assassin’s Creed Unity", "Assassin's Creed Unity"),
        ("The Witcher® 3 - Wild Hunt", "The Witcher 3: Wild Hunt"),
        ("Half Life 2", "Half-Life 2"),
        ("stardew valley", "Stardew Valley"),
    ],
)
def test_normalised_match(matcher, catalogue, imported, expected):
    _ok(matcher.match(ImportedTitle(imported)), catalogue[expected], "normalised")


@pytest.mark.parametrize(
    ("imported", "expected"),
    [
        ("The Witcher 3: Wild Hunt - Game of the Year Edition", "The Witcher 3: Wild Hunt"),
        ("DOOM Eternal Deluxe Edition", "DOOM Eternal"),
        ("Portal 2: Complete Edition", "Portal 2"),
        # base game row exists alongside another edition: base game wins
        ("The Elder Scrolls V: Skyrim Legendary Edition", "The Elder Scrolls V: Skyrim"),
    ],
)
def test_edition_suffix_match(matcher, catalogue, imported, expected):
    _ok(matcher.match(ImportedTitle(imported)), catalogue[expected], "edition")


def test_specific_edition_row_beats_edition_fallback(matcher, catalogue):
    result = matcher.match(ImportedTitle("The Elder Scrolls V: Skyrim® Special Edition"))
    _ok(result, catalogue["The Elder Scrolls V: Skyrim Special Edition"], "normalised")


def test_remaster_is_not_folded_into_base(matcher, catalogue):
    result = matcher.match(ImportedTitle("DARK SOULS™: REMASTERED"))
    _ok(result, catalogue["Dark Souls Remastered"], "normalised")


def test_edition_only_catalogue_matches_via_stripped_index():
    # The catalogue only carries an edition row; the plain title and a different
    # edition both reach it through the stripped-base index.
    only = _game("Fallout 4: Game of the Year Edition")
    for imported in ("Fallout 4", "Fallout 4 - Deluxe Edition"):
        result = TitleMatcher([only]).match(ImportedTitle(imported))
        _ok(result, only, "edition")


def test_unmatched_is_recorded_with_reason(matcher):
    result = matcher.match(ImportedTitle("Some Indie Nobody Has Heard Of™"))
    assert isinstance(result, UnmatchedTitle)
    assert result.reason == "no_match"
    assert result.normalised_title == "some indie nobody has heard of"
    assert result.imported.title == "Some Indie Nobody Has Heard Of™"


def test_blank_title_is_unmatched_not_crashing(matcher):
    result = matcher.match(ImportedTitle("™ "))
    assert isinstance(result, UnmatchedTitle)
    assert result.reason == "blank_title"


def test_ambiguous_normalised_title_is_not_guessed():
    a, b = _game("Prey"), _game("PREY")
    result = TitleMatcher([a, b]).match(ImportedTitle("Prey™"))
    assert isinstance(result, UnmatchedTitle)
    assert result.reason == "ambiguous"
    assert set(result.candidate_game_ids) == {a.game_id, b.game_id}


def test_ambiguous_edition_base_is_not_guessed():
    a = _game("Fallout 4: Game of the Year Edition")
    b = _game("Fallout 4 - Ultimate Edition")
    result = TitleMatcher([a, b]).match(ImportedTitle("Fallout 4 Deluxe Edition"))
    assert isinstance(result, UnmatchedTitle)
    assert result.reason == "ambiguous"


def test_duplicate_appid_rows_fall_back_to_title():
    a, b = _game("Alpha", 10), _game("Beta", 10)
    result = TitleMatcher([a, b]).match(ImportedTitle("Beta", steam_appid=10))
    assert isinstance(result, TitleMatch)
    assert result.game_id == b.game_id and result.method == "exact"


# ─────────────────────────── MatchReport ───────────────────────────


def test_match_all_reports_rate_and_keeps_unmatched(matcher):
    report = matcher.match_all(
        [
            ImportedTitle("Portal 2", steam_appid=620),          # appid
            ImportedTitle("Stardew Valley"),                     # exact
            ImportedTitle("Half Life 2"),                        # normalised
            ImportedTitle("DOOM Eternal - Deluxe Edition"),      # edition
            ImportedTitle("Unknown Game"),                       # unmatched
        ]
    )
    assert report.total == 5
    assert len(report.matched) == 4
    assert [u.imported.title for u in report.unmatched] == ["Unknown Game"]
    assert report.match_rate == 0.8
    assert report.counts_by_method() == {
        "appid": 1, "exact": 1, "normalised": 1, "edition": 1,
    }
    assert report.summary()["unmatched"] == 1


def test_empty_import_reports_zero_rate(matcher):
    report = matcher.match_all([])
    assert report.total == 0
    assert report.match_rate == 0.0


def test_catalogue_from_rows_accepts_db_shapes():
    gid = uuid4()
    games = catalogue_from_rows(
        [{"game_id": str(gid), "title": "Portal 2", "steam_appid": 620},
         {"game_id": uuid4(), "title": None, "steam_appid": None}]
    )
    assert games[0] == CatalogueGame(gid, "Portal 2", 620)
    # a NULL title is indexed by appid only, never as an empty-string title
    matcher = TitleMatcher(games)
    assert isinstance(matcher.match(ImportedTitle("")), UnmatchedTitle)
