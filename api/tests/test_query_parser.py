"""QueryParser (TM11-62, REQ011).

One group per acceptance criterion. The catalogue is a fixed list of real
seed titles, so these run offline with no database.
"""

from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

import pytest

from api.services.query_parser import (
    PARSER_VERSION,
    QueryParser,
    TitleIndex,
    parse_query,
)
from api.services.title_matching import CatalogueGame

TITLES = [
    "Hades", "Hades II", "Dead Cells", "Celeste", "Hollow Knight", "Stardew Valley",
    "Rust", "Control", "The Forest", "Sons of the Forest", "Dark Souls III",
    "The Witcher 3: Wild Hunt", "The Elder Scrolls V: Skyrim", "Cities: Skylines",
    "Ori and the Blind Forest", "No Man's Sky", "Ratchet & Clank", "Portal 2",
]
GAMES = [CatalogueGame(uuid4(), title) for title in TITLES]
ID = {g.title: g.game_id for g in GAMES}


@pytest.fixture(scope="module")
def index() -> TitleIndex:
    return TitleIndex(GAMES)


def titles(parsed) -> list[str]:
    return [r.title for r in parsed.reference_titles]


# ───────────── AC: genre, mood, platform and reference-title signals ─────────────


def test_all_four_signals_come_out_of_one_query(index):
    parsed = parse_query(
        "A cozy farming sim like Stardew Valley that I can play on Xbox", index
    )
    assert parsed.genres == ("Simulation",)
    assert parsed.moods == ("cozy",)
    assert parsed.platforms == ("xbox",)
    assert parsed.reference_titles[0].game_id == ID["Stardew Valley"]


@pytest.mark.parametrize("query, genre", [
    ("jrpgs", "RPG"),
    ("a role-playing game", "RPG"),
    ("roguelites", "Roguelike"),
    ("an fps", "Shooter"),
    ("co-op games", "Co-op"),
    ("something soulslike", "Action RPG"),
    ("a deck-building game", "Deckbuilder"),
])
def test_genre_synonyms_map_to_catalogue_genre_names(index, query, genre):
    assert parse_query(query, index).genres == (genre,)


@pytest.mark.parametrize("query, mood", [
    ("something chill", "relaxing"),
    ("a spooky one", "tense"),
    ("wholesome", "cozy"),
    ("hilarious", "comedy"),
    ("story-driven", "story-rich"),
    ("fast-paced", "fast-paced"),
])
def test_mood_words_map_to_catalogue_tags(index, query, mood):
    assert parse_query(query, index).moods == (mood,)


def test_pc_means_both_pc_stores(index):
    assert parse_query("good on PC", index).platforms == ("steam", "epic")


def test_epic_as_an_adjective_is_not_a_platform(index):
    parsed = parse_query("an epic adventure", index)
    assert parsed.platforms == ()
    assert parsed.genres == ("Adventure",)


def test_epic_games_store_is_a_platform(index):
    assert parse_query("free on the Epic Games Store", index).platforms == ("epic",)


def test_a_list_of_references_is_read_in_order(index):
    parsed = parse_query("like Hades, Dead Cells and Celeste", index)
    assert titles(parsed) == ["Hades", "Dead Cells", "Celeste"]


def test_the_longest_title_wins_over_a_list_split(index):
    # "and"/"&" inside a title is part of it, not a list joiner.
    parsed = parse_query("something like Ori and the Blind Forest", index)
    assert titles(parsed) == ["Ori and the Blind Forest"]
    assert titles(parse_query("like Ratchet and Clank", index)) == ["Ratchet & Clank"]


@pytest.mark.parametrize("query, title", [
    ("like dark souls 3", "Dark Souls III"),
    ("like hades 2", "Hades II"),
    ("a game like the witcher 3", "The Witcher 3: Wild Hunt"),
    ("like skyrim", "The Elder Scrolls V: Skyrim"),
    ("similar to no mans sky", "No Man's Sky"),
    ("I loved Hollow Knight's art", "Hollow Knight"),
])
def test_common_spellings_of_a_title_match(index, query, title):
    assert titles(parse_query(query, index)) == [title]


def test_a_multi_word_title_counts_without_a_cue(index):
    assert titles(parse_query("Stardew Valley but in space", index)) == ["Stardew Valley"]


@pytest.mark.parametrize("query", [
    "I really like rust",           # "like" is the verb here, not a comparison
    "a game where you take control",
    "explore the forest at night",  # "The Forest" needs a cue
    "an epic wild hunt",            # a subtitle alone needs a cue
    "build cities",
])
def test_ordinary_words_are_not_read_as_titles(index, query):
    assert parse_query(query, index).reference_titles == ()


def test_title_words_are_not_also_read_as_signals(index):
    # "Dark" is part of the title, not a request for a dark game.
    parsed = parse_query("like Dark Souls 3", index)
    assert parsed.moods == ()


def test_negated_signals_are_excluded_not_wanted(index):
    parsed = parse_query("I don't want anything scary, and no shooters", index)
    assert parsed.excluded_moods == ("tense",)
    assert parsed.excluded_genres == ("Shooter",)
    assert parsed.moods == () and parsed.genres == ()


def test_negation_stops_at_but(index):
    parsed = parse_query("not a shooter but a strategy game", index)
    assert parsed.excluded_genres == ("Shooter",)
    assert parsed.genres == ("Strategy",)


def test_negation_does_not_cross_a_sentence(index):
    parsed = parse_query("Not on Xbox. Puzzle games", index)
    assert parsed.excluded_platforms == ("xbox",)
    assert parsed.genres == ("Puzzle",)


def test_a_signal_mentioned_twice_is_listed_once(index):
    assert parse_query("relaxing, chill, calm", index).moods == ("relaxing",)


def test_query_with_no_signals_parses_to_empty(index):
    parsed = parse_query("surprise me", index)
    assert parsed.genres == parsed.moods == parsed.platforms == ()
    assert parsed.reference_titles == () and parsed.unrecognised_references == ()


# ───────────── AC: unrecognised reference titles ignored gracefully ─────────────


def test_unknown_title_after_a_cue_is_recorded_and_ignored(index):
    parsed = parse_query("games like Moonfall Saga with good music", index)
    assert parsed.reference_titles == ()
    assert parsed.unrecognised_references == ("moonfall saga",)


def test_unknown_title_does_not_stop_the_other_signals(index):
    parsed = parse_query("like Moonfall Saga, but a relaxing puzzle game on Steam", index)
    assert parsed.unrecognised_references == ("moonfall saga",)
    assert parsed.moods == ("relaxing",)
    assert parsed.genres == ("Puzzle",)
    assert parsed.platforms == ("steam",)


def test_known_and_unknown_titles_mix(index):
    parsed = parse_query("like Hades. Also similar to Moonfall Saga", index)
    assert titles(parsed) == ["Hades"]
    assert parsed.unrecognised_references == ("moonfall saga",)


@pytest.mark.parametrize("query", [
    "something like a cozy farm game",
    "like roguelikes",
    "games like that",
])
def test_a_description_after_like_is_not_an_unrecognised_title(index, query):
    assert parse_query(query, index).unrecognised_references == ()


def test_an_ambiguous_spelling_is_unrecognised_not_guessed():
    twins = TitleIndex([CatalogueGame(uuid4(), "Prey"), CatalogueGame(uuid4(), "Prey")])
    parsed = parse_query("like Prey", twins)
    assert parsed.reference_titles == ()
    assert parsed.unrecognised_references == ("prey",)


def test_without_a_catalogue_titles_are_skipped_and_signals_still_parse():
    parsed = parse_query("a relaxing game like Hades", None)
    assert parsed.titles_checked is False
    assert parsed.reference_titles == () and parsed.unrecognised_references == ()
    assert parsed.moods == ("relaxing",)


@pytest.mark.asyncio
async def test_catalogue_failure_degrades_instead_of_raising(caplog):
    async def broken():
        raise RuntimeError("database is down")

    caplog.set_level(logging.INFO, logger="gamegpt.query_parser")
    parsed = await QueryParser(load_titles=broken).parse("chill games like Hades")
    assert parsed.moods == ("relaxing",)
    assert parsed.titles_checked is False
    assert [r.getMessage() for r in caplog.records] == [
        "query.titles_unavailable", "query.parsed",
    ]


def test_an_empty_catalogue_is_handled():
    parsed = parse_query("like Hades", TitleIndex([]))
    assert parsed.reference_titles == ()
    assert parsed.unrecognised_references == ("hades",)


# ───────────── AC: extraction output logged for every query ─────────────


@pytest.mark.asyncio
async def test_every_parse_logs_its_signals(index, caplog):
    async def load():
        return index

    caplog.set_level(logging.INFO, logger="gamegpt.query_parser")
    parser = QueryParser(load_titles=load)
    for query in ("rpg", "surprise me", "chill like Hades on Steam"):
        await parser.parse(query)

    logged = [r.query_parse for r in caplog.records if r.getMessage() == "query.parsed"]
    assert len(logged) == 3
    last = logged[-1]
    assert last["parser_version"] == PARSER_VERSION
    assert last["moods"] == ["relaxing"]
    assert last["platforms"] == ["steam"]
    assert last["reference_titles"] == [{"game_id": str(ID["Hades"]), "title": "Hades"}]
    assert logged[1]["genres"] == [] and logged[1]["word_count"] == 2
    json.dumps(logged)  # the JSON log formatter has to be able to write it


@pytest.mark.asyncio
async def test_the_log_never_contains_the_players_own_words(index, caplog):
    async def load():
        return index

    caplog.set_level(logging.INFO, logger="gamegpt.query_parser")
    await QueryParser(load_titles=load).parse("like Secret Project Zeta, chill")

    record = caplog.records[-1]
    assert "secret" not in json.dumps(record.query_parse).lower()
    assert record.query_parse["unrecognised_reference_count"] == 1


@pytest.mark.asyncio
async def test_the_pipeline_parses_every_query():
    from api.services.rag_pipeline import RAGPipeline

    class RecordingParser:
        def __init__(self):
            self.queries: list[str] = []

        async def parse(self, query):
            self.queries.append(query)

    class Stub:
        async def embed_query(self, text):
            return [0.0]

        async def top_k(self, embedding, k=20):
            return []

        async def filter_owned(self, user_id, candidates):
            return candidates

        async def rank(self, query, candidates, n=3):
            return []

    parser = RecordingParser()
    stub = Stub()
    pipeline = RAGPipeline(stub, stub, stub, stub, parser=parser)
    await pipeline.recommend(UUID(int=1), "a chill game")
    await pipeline.recommend(UUID(int=1), "rpg")
    assert parser.queries == ["a chill game", "rpg"]


# ───────────── AC: a one-word query and a paragraph ─────────────


@pytest.mark.parametrize("query, field, expected", [
    ("rpg", "genres", ("RPG",)),
    ("cozy", "moods", ("cozy",)),
    ("xbox", "platforms", ("xbox",)),
    ("horror", "genres", ("Horror",)),
])
def test_one_word_signal_query(index, query, field, expected):
    parsed = parse_query(query, index)
    assert getattr(parsed, field) == expected
    assert parsed.word_count == 1


def test_one_word_title_query_names_that_game(index):
    parsed = parse_query("Hades", index)
    assert titles(parsed) == ["Hades"]
    assert parsed.genres == parsed.moods == ()


def test_one_word_query_with_nothing_to_extract(index):
    parsed = parse_query("hmm", index)
    assert parsed.word_count == 1
    assert parsed.reference_titles == () and parsed.unrecognised_references == ()


def test_paragraph_query(index):
    paragraph = (
        "I loved Hollow Knight's art and the way exploring slowly opened up the map. "
        "Looking for a metroidvania that is not too difficult and has a great story, "
        "something emotional like Ori and the Blind Forest or Celeste. I mostly play "
        "on my Steam Deck in bed, so nothing too scary or fast-paced, please! "
        "Bonus points if it has some puzzle elements; I don't really enjoy shooters."
    )
    parsed = parse_query(paragraph, index)
    assert titles(parsed) == ["Hollow Knight", "Ori and the Blind Forest", "Celeste"]
    assert parsed.genres == ("Metroidvania", "Puzzle")
    assert parsed.moods == ("story-rich", "emotional")
    assert set(parsed.excluded_moods) == {"difficult", "tense", "fast-paced"}
    assert parsed.excluded_genres == ("Shooter",)
    assert parsed.platforms == ("steam",)
    assert parsed.word_count > 60


def test_maximum_length_query_parses(index):
    query = ("relaxing puzzle games like Celeste " * 20)[:500]
    parsed = parse_query(query, index)
    assert titles(parsed) == ["Celeste"]
    assert parsed.genres == ("Puzzle",)


@pytest.mark.parametrize("query", ["", "   ", "...", ",,,", "!!!", "🎮", "like", "not"])
def test_degenerate_input_does_not_raise(index, query):
    parse_query(query, index)
