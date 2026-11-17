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
    ParsedQuery,
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
    return titles_of(parsed.reference_titles)


def titles_of(references) -> list[str]:
    return [r.title for r in references]


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


@pytest.mark.parametrize("query, platforms", [
    ("action roguelikes on Epic", ("epic",)),
    ("something cozy on epic, please", ("epic",)),
    ("I want to go on epic adventures", ()),  # PR #50 review: the adjective after "on"
])
def test_on_epic_counts_only_at_the_end_of_a_clause(index, query, platforms):
    assert parse_query(query, index).platforms == platforms


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


@pytest.mark.parametrize("query, title", [
    ("nothing like Dark Souls 3", "Dark Souls III"),   # PR #50 review
    ("not like Hades", "Hades"),
    ("I don't like Hades", "Hades"),                   # the negated verb still counts
    ("I don't like Stardew Valley", "Stardew Valley"),
    ("no Stardew Valley clones", "Stardew Valley"),    # uncued title
])
def test_a_negated_title_is_excluded_not_a_reference(index, query, title):
    parsed = parse_query(query, index)
    assert parsed.reference_titles == ()
    assert [r.title for r in parsed.excluded_reference_titles] == [title]


def test_wanted_and_ruled_out_titles_in_one_query(index):
    parsed = parse_query("a game like Celeste, nothing like Hades", index)
    assert titles(parsed) == ["Celeste"]
    assert [r.title for r in parsed.excluded_reference_titles] == ["Hades"]


def test_a_negated_list_of_titles_is_all_excluded(index):
    parsed = parse_query("nothing like Hades or Dead Cells", index)
    assert parsed.reference_titles == ()
    assert [r.title for r in parsed.excluded_reference_titles] == ["Hades", "Dead Cells"]


def test_i_like_names_no_title_either_way(index):
    parsed = parse_query("I like Hades", index)
    assert parsed.reference_titles == () and parsed.excluded_reference_titles == ()


def test_a_label_wanted_and_excluded_takes_its_last_mention(index):
    # PR #50 review: "horror" is also the tense mood.
    parsed = parse_query("no horror, but i want something tense", index)
    assert parsed.moods == ("tense",)
    assert parsed.excluded_moods == ()
    assert parsed.excluded_genres == ("Horror",)

    parsed = parse_query("something tense. Actually no, nothing scary", index)
    assert parsed.moods == ()
    assert parsed.excluded_moods == ("tense",)


def test_a_title_wanted_and_excluded_takes_its_last_mention(index):
    parsed = parse_query("like Hades. Actually, nothing like Hades", index)
    assert parsed.reference_titles == ()
    assert titles_of(parsed.excluded_reference_titles) == ["Hades"]


def test_no_label_is_ever_both_wanted_and_excluded(index):
    for query in ("no horror, but i want something tense", "chill, not chill, chill",
                  "on pc but not on epic games", "like Hades, nothing like Hades"):
        parsed = parse_query(query, index)
        for wanted, excluded in (
            (parsed.genres, parsed.excluded_genres),
            (parsed.moods, parsed.excluded_moods),
            (parsed.platforms, parsed.excluded_platforms),
            (parsed.reference_titles, parsed.excluded_reference_titles),
        ):
            assert not set(wanted) & set(excluded), query


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


@pytest.mark.asyncio
async def test_a_parser_bug_degrades_instead_of_failing_the_recommend(index, caplog, monkeypatch):
    # PR #50 review: only the catalogue load was guarded.
    import api.services.query_parser as query_parser

    def broken(query, index):
        raise ValueError("bug in a rule")

    async def load():
        return index

    monkeypatch.setattr(query_parser, "parse_query", broken)
    caplog.set_level(logging.INFO, logger="gamegpt.query_parser")
    parsed = await QueryParser(load_titles=load).parse("chill games like Hades")

    assert parsed == query_parser.ParsedQuery(titles_checked=False)
    assert [r.getMessage() for r in caplog.records] == ["query.parse_failed", "query.parsed"]


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
    assert last["excluded_reference_titles"] == []
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
            return ParsedQuery()

    class Stub:
        async def embed_query(self, text):
            return [0.0]

        async def top_k(self, embedding, k=20, filters=None):
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


# ───────────── TM11-160: gaps the retrieval benchmark found ─────────────
# Every phrasing here is new: none is one of the 20 TM11-63 benchmark prompts,
# so the parser isn't tuned to the benchmark it is measured on.

SERIES_TITLES = [
    "Portal", "Portal 2", "DARK SOULS™: REMASTERED", "DARK SOULS™ II: Scholar of the First Sin",
    "DARK SOULS™ III", "Hollow Knight", "Hollow Knight: Silksong", "Fallout 4",
    "Fallout: New Vegas", "Star Wars Jedi: Fallen Order", "Star Wars Jedi: Survivor",
    "The Witcher 2: Assassins of Kings", "The Witcher 3: Wild Hunt", "Subnautica",
    "Subnautica: Below Zero", "Terraria", "Celeste", "Rust",
]
SERIES_GAMES = [CatalogueGame(uuid4(), t) for t in SERIES_TITLES]


@pytest.fixture(scope="module")
def series() -> TitleIndex:
    return TitleIndex(SERIES_GAMES)


# AC1: "I finished X" and "X but ..." are comparisons, and X is the reference.


@pytest.mark.parametrize("query, title", [
    ("just finished Celeste, need another platformer", "Celeste"),
    ("I completed Terraria twice, what next", "Terraria"),
    ("we beat Rust last weekend", "Rust"),
    ("played through Celeste and want more", "Celeste"),
    ("finally beaten Terraria, any ideas", "Terraria"),
])
def test_finishing_a_game_names_it_as_the_reference(series, query, title):
    assert titles(parse_query(query, series)) == [title]


@pytest.mark.parametrize("query, title", [
    ("Terraria but set in space", "Terraria"),
    ("Celeste, but with a bigger world", "Celeste"),
    ("Rust but less toxic. On PC", "Rust"),
])
def test_a_leading_title_followed_by_but_is_a_comparison(series, query, title):
    assert titles(parse_query(query, series)) == [title]


def test_a_leading_word_followed_by_but_that_is_no_title_is_not_a_reference(series):
    parsed = parse_query("relaxing but not boring", series)
    assert parsed.reference_titles == ()
    assert parsed.unrecognised_references == ()


def test_a_single_word_title_mid_sentence_before_but_still_needs_a_cue(series):
    # Only the start of a clause counts: "rust" here is the ordinary word.
    assert titles(parse_query("a game about rust but in space", series)) == []


def test_beat_em_up_is_a_genre_not_a_finished_game(series):
    parsed = parse_query("a beat em up for two players", series)
    assert parsed.genres == ("Fighting",)
    assert parsed.unrecognised_references == ()


def test_a_title_starting_with_a_cue_word_is_the_title_not_a_cue():
    # PR #64 review: "beat" also starts "Beat Saber", which must not leave "saber" behind.
    index = TitleIndex([CatalogueGame(uuid4(), "Beat Saber"), CatalogueGame(uuid4(), "Celeste")])
    parsed = parse_query("I love Beat Saber, want more rhythm games", index)
    assert titles(parsed) == ["Beat Saber"]
    assert parsed.unrecognised_references == ()
    # "beat" is still a cue in front of another title.
    assert titles(parse_query("just beat Celeste", index)) == ["Celeste"]


def test_beat_it_after_a_signal_is_not_an_unrecognised_title(series):
    parsed = parse_query("tough, but satisfying once you beat it", series)
    assert parsed.unrecognised_references == ()


# AC2: the named game resolves to the right entry, and its series is ruled out.


def test_dark_souls_resolves_to_the_first_game_not_a_sequel(series):
    parsed = parse_query("anything similar to Dark Souls with a fantasy setting", series)
    assert titles(parsed) == ["DARK SOULS™: REMASTERED"]
    assert titles_of(parsed.related_titles) == [
        "DARK SOULS™ II: Scholar of the First Sin", "DARK SOULS™ III"]


def test_a_numbered_entry_resolves_to_itself_and_rules_out_the_rest(series):
    parsed = parse_query("loved Dark Souls 3, want a harder one", series)
    assert titles(parsed) == ["DARK SOULS™ III"]
    assert titles_of(parsed.related_titles) == [
        "DARK SOULS™ II: Scholar of the First Sin", "DARK SOULS™: REMASTERED"]


@pytest.mark.parametrize("query, reference, related", [
    ("I completed Portal", "Portal", ["Portal 2"]),
    ("similar to Portal 2", "Portal 2", ["Portal"]),
    ("like The Witcher 3 with better combat", "The Witcher 3: Wild Hunt",
     ["The Witcher 2: Assassins of Kings"]),
    ("I finished Hollow Knight", "Hollow Knight", ["Hollow Knight: Silksong"]),
    ("enjoyed Subnautica: Below Zero", "Subnautica: Below Zero", ["Subnautica"]),
    ("like Fallout: New Vegas", "Fallout: New Vegas", ["Fallout 4"]),
])
def test_sequels_prequels_and_subtitled_follow_ups_are_related(series, query, reference, related):
    parsed = parse_query(query, series)
    assert titles(parsed) == [reference]
    assert titles_of(parsed.related_titles) == related


def test_a_subtitled_spin_off_keeps_its_own_series(series):
    # "Star Wars Jedi" is no game of its own, so Fallen Order and Survivor
    # aren't tied together, and naming one doesn't rule out every Star Wars game.
    parsed = parse_query("like Star Wars Jedi: Fallen Order", series)
    assert titles(parsed) == ["Star Wars Jedi: Fallen Order"]
    assert parsed.related_titles == ()


def test_an_excluded_games_series_is_related_too(series):
    parsed = parse_query("nothing like Portal, I'm sick of puzzles", series)
    assert titles_of(parsed.excluded_reference_titles) == ["Portal"]
    assert titles_of(parsed.related_titles) == ["Portal 2"]


def test_an_unlisted_base_game_still_rules_out_its_listed_sequels():
    # On a catalogue with only the sequel, "Dark Souls" names no game, but the
    # sequel is still the same series and still not an answer.
    only_sequel = TitleIndex([CatalogueGame(uuid4(), "Dark Souls III")])
    parsed = parse_query("something in the vein of Dark Souls but with guns", only_sequel)
    assert parsed.reference_titles == ()
    assert parsed.unrecognised_references == ("dark souls",)
    assert titles_of(parsed.related_titles) == ["Dark Souls III"]


def test_a_spelling_shared_within_one_series_picks_the_base_entry():
    base, edition = uuid4(), uuid4()
    index = TitleIndex([CatalogueGame(base, "Dark Souls"),
                        CatalogueGame(edition, "Dark Souls: Remastered")])
    parsed = parse_query("like Dark Souls", index)
    assert [r.game_id for r in parsed.reference_titles] == [base]
    assert [r.game_id for r in parsed.related_titles] == [edition]


def test_identical_titles_stay_ambiguous_but_both_are_ruled_out():
    twins = TitleIndex([CatalogueGame(uuid4(), "Prey"), CatalogueGame(uuid4(), "Prey")])
    parsed = parse_query("I finished Prey", twins)
    assert parsed.reference_titles == ()
    assert titles_of(parsed.related_titles) == ["Prey", "Prey"]


def test_related_titles_are_logged_by_catalogue_title(series):
    fields = parse_query("I completed Portal", series).log_fields()
    assert [r["title"] for r in fields["related_titles"]] == ["Portal 2"]


# AC3: vocabulary for difficulty, survival and playing with friends.


@pytest.mark.parametrize("query", [
    "something really hard",
    "hard platformers",
    "a brutally unfair boss rush",
    "hardcore colony management",
])
def test_hard_means_difficult(series, query):
    assert "difficult" in parse_query(query, series).moods


def test_not_too_hard_excludes_difficult(series):
    parsed = parse_query("a puzzle game that isn't too hard", series)
    assert parsed.excluded_moods == ("difficult",)


@pytest.mark.parametrize("query", [
    "help me survive a zombie outbreak",
    "surviving in the arctic",
    "try to survive the night in a haunted mall",
])
def test_survive_means_survival(series, query):
    assert "Survival" in parse_query(query, series).genres


@pytest.mark.parametrize("query", [
    "a racing game to play with friends",
    "something to play with my friends online",
    "tower defense with a buddy",
])
def test_with_friends_means_co_op_or_multiplayer(series, query):
    genres = parse_query(query, series).genres
    assert "Co-op" in genres and "Multiplayer" in genres


def test_not_with_friends_excludes_both(series):
    parsed = parse_query("a strategy game, not with friends, just me", series)
    assert set(parsed.excluded_genres) == {"Co-op", "Multiplayer"}


def test_a_series_names_words_are_not_read_as_signals():
    only_sequel = TitleIndex([CatalogueGame(uuid4(), "Dark Souls III")])
    assert parse_query("reminds me of Dark Souls", only_sequel).moods == ()


@pytest.mark.parametrize("query", [
    "a game that's hard to put down",
    "hard sci-fi with a slow-burn story",
    "something with hard choices",
])
def test_hard_not_about_difficulty_is_not_difficult(series, query):
    # PR #64 review: a bare "hard" only counts next to an intensifier or a game word.
    assert "difficult" not in parse_query(query, series).moods


@pytest.mark.parametrize("query", ["a hard game", "hard roguelikes", "so hard it hurts",
                                   "hard bosses and tight combat", "play it on hard mode"])
def test_hard_about_the_game_is_difficult(series, query):
    assert "difficult" in parse_query(query, series).moods
