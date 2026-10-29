"""QueryParser — reads structured signals out of a free-text request (TM11-62, REQ011).

REQ011 lets a player describe what they want instead of picking filters. This
reads that description for four kinds of signal:

  genres            catalogue genre names ("RPG", "Roguelike"), from words like
                    "jrpg" or "roguelites"
  moods             catalogue tag names ("relaxing", "tense"), from words like
                    "chill" or "spooky"
  platforms         "steam", "xbox", "epic"; "pc" means both PC stores
  reference titles  catalogue games named as a comparison ("like Hades")

Rule-based and deterministic: no model call, so parsing adds no cost or
provider dependency to a recommend, and every signal traces back to a word in
the vocabularies below. A negated word ("nothing scary", "no shooters") is
recorded as excluded, not wanted.

Reference titles are matched with normalise_title, the key library import
matches on. A single-word title needs a comparison cue ("like Celeste") or
must be the whole query, because single words like "rust" or "control" are
also ordinary words. Longer titles ("Stardew Valley") count anywhere. A name
after a cue that matches no game goes in `unrecognised_references` and
nothing else happens: an unknown title never fails a query. If the catalogue
can't be read, title matching is skipped and the other signals still come back.

Every parse is logged as `query.parsed`. Using the signals to filter or boost
retrieval is TM11-65.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Sequence
from uuid import UUID

from api.db import has_db
from api.services.title_matching import (
    CatalogueGame,
    catalogue_from_rows,
    normalise_title,
    strip_edition,
)

log = logging.getLogger("gamegpt.query_parser")

# Bumped whenever a vocabulary or rule changes, so logged parses from before
# and after a change can be told apart.
PARSER_VERSION = "rules-v1"

# How long the title index is reused before the catalogue is read again.
CATALOGUE_CACHE_SECONDS = 600.0


# ───────────────────────────── vocabularies ─────────────────────────────
# Keys are the labels the catalogue uses (games.genres for genres, games.tags
# for moods), so TM11-65 can match them against rows directly. Phrases are
# written as normalise_title leaves them: lower case, punctuation as spaces.

_GENRE_PHRASES: dict[str, tuple[str, ...]] = {
    "Action": ("action",),
    "Adventure": ("adventure",),
    "RPG": ("rpg", "role playing", "roleplaying", "jrpg", "crpg"),
    "Action RPG": ("action rpg", "arpg", "soulslike", "souls like"),
    "Shooter": ("shooter", "fps", "first person shooter", "third person shooter"),
    "Strategy": ("strategy", "rts", "4x", "grand strategy"),
    "Simulation": ("simulation", "sim", "simulator"),
    "Platformer": ("platformer", "platforming"),
    "Puzzle": ("puzzle", "puzzler"),
    "Roguelike": ("roguelike", "roguelite", "rogue like", "rogue lite"),
    "Metroidvania": ("metroidvania",),
    "Survival": ("survival",),
    "Horror": ("horror", "survival horror"),
    "Open World": ("open world", "openworld"),
    "Co-op": ("co op", "coop", "cooperative", "co operative"),
    "Multiplayer": ("multiplayer",),
    "Sports": ("sports", "sport"),
    "Racing": ("racing", "racer"),
    "Fighting": ("fighting game", "fighter", "beat em up"),
    "Tactics": ("tactics", "tactical"),
    "Battle Royale": ("battle royale",),
    "Sandbox": ("sandbox",),
    "Deckbuilder": ("deckbuilder", "deck builder", "deckbuilding", "deck building", "card game"),
    "City Builder": ("city builder", "city building"),
    "Stealth": ("stealth",),
    "MOBA": ("moba",),
    "MMO": ("mmo", "mmorpg"),
    "Visual Novel": ("visual novel",),
    "Party": ("party game",),
    "Mystery": ("mystery", "detective"),
    "Management": ("management", "tycoon"),
    "Indie": ("indie",),
    "VR": ("vr", "virtual reality"),
}

_MOOD_PHRASES: dict[str, tuple[str, ...]] = {
    "relaxing": ("relaxing", "relaxed", "relax", "chill", "chilled", "calm", "calming",
                 "peaceful", "laid back", "low stress", "stress free", "unwind", "zen",
                 "meditative"),
    "cozy": ("cozy", "cosy", "comfy", "wholesome", "heartwarming", "comforting", "cute"),
    "atmospheric": ("atmospheric", "immersive", "moody", "haunting"),
    "difficult": ("difficult", "challenging", "punishing", "brutal", "unforgiving", "tough"),
    "fast-paced": ("fast paced", "frantic", "hectic", "adrenaline", "action packed",
                   "high octane", "twitchy"),
    "tense": ("tense", "scary", "creepy", "spooky", "terrifying", "frightening", "horror",
              "suspenseful", "eerie", "unsettling", "nerve wracking", "jump scares"),
    "emotional": ("emotional", "sad", "moving", "touching", "tearjerker", "heartfelt",
                  "bittersweet", "melancholy"),
    "dark": ("dark", "grim", "bleak", "gritty", "grimdark", "dystopian", "depressing"),
    "comedy": ("funny", "hilarious", "comedy", "comedic", "silly", "goofy", "lighthearted",
               "light hearted", "humorous", "humor", "humour", "wacky"),
    "competitive": ("competitive", "ranked", "pvp", "esports"),
    "story-rich": ("story rich", "story driven", "story heavy", "narrative",
                   "narrative driven", "good story", "great story"),
}

# "epic" alone is an adjective far more often than a store, so only store
# phrasings count.
_PLATFORM_PHRASES: dict[tuple[str, ...], tuple[str, ...]] = {
    ("steam",): ("steam", "steam deck"),
    ("xbox",): ("xbox", "xbox one", "xbox series x", "xbox series s", "series x",
                "game pass", "gamepass"),
    ("epic",): ("epic games", "epic games store", "epic store", "epic launcher", "egs",
                "on epic"),
    ("steam", "epic"): ("pc",),
}

# A negator up to this many words before a signal marks it as excluded.
_NEGATION_WINDOW = 3
_NEGATORS = frozenset({"no", "not", "without", "nothing", "never", "dont", "doesnt",
                       "isnt", "arent", "avoid", "hate", "except", "non", "zero"})
# These end a negation's reach: "not scary but funny" only excludes scary.
_NEGATION_BREAKS = frozenset({",", "but", "though", "although", "however", "instead",
                              "rather", "yet"})

# Words that introduce a reference title, as token sequences.
_CUES: tuple[tuple[str, ...], ...] = tuple(sorted(
    (tuple(cue.split()) for cue in (
        "like", "similar to", "such as", "reminds me of", "reminiscent of",
        "in the vein of", "in the style of", "along the lines of", "inspired by",
        "fan of", "fans of", "comparable to", "alternative to", "alternatives to",
        "loved", "enjoyed",
    )),
    key=len, reverse=True,
))
# "like" after one of these is the verb ("I like", "I'd like"), not a comparison.
_LIKE_AS_VERB_AFTER = frozenset({"i", "id", "we", "wed", "you", "youd", "they", "theyd",
                                 "would", "really", "also", "do", "dont", "didnt",
                                 "still", "usually", "generally", "might", "will"})
# Joins a list of references: "like Hades, Celeste and Dead Cells".
_LIST_JOINERS = frozenset({",", "and", "or"})
# Ends an unrecognised name: "like Moonfall Saga with good music" keeps "moonfall saga".
_NAME_STOPS = frozenset({",", "and", "or", "but", "with", "that", "which", "where", "who",
                         "for", "on", "because", "except", "though", "if", "so", "than",
                         "when", "to", "in", "from", "is", "are", "was"})
# A phrase starting with one of these after a cue is a description ("like a
# cozy farm game"), not a title, so it isn't reported as unrecognised.
_DESCRIPTION_STARTS = frozenset({"a", "an", "some", "something", "anything", "this", "that",
                                 "these", "those", "it", "them", "one", "ones", "more",
                                 "other", "others", "game", "games", "what", "how", "when",
                                 "my", "your", "their", "its"})
_MAX_UNRECOGNISED_WORDS = 6

_CLAUSE_SPLIT = re.compile(r"[.;!?\n]+")


def _phrase_table(phrases: dict[Any, tuple[str, ...]], *, plurals: bool) -> dict:
    """{token tuple: label}. With `plurals`, "shooter" also matches "shooters"."""
    table: dict[tuple[str, ...], Any] = {}
    for label, words in phrases.items():
        for phrase in words:
            tokens = tuple(phrase.split())
            table[tokens] = label
            if plurals and not tokens[-1].endswith("s"):
                table.setdefault(tokens[:-1] + (tokens[-1] + "s",), label)
    return table


_GENRES = _phrase_table(_GENRE_PHRASES, plurals=True)
_MOODS = _phrase_table(_MOOD_PHRASES, plurals=False)
_PLATFORMS = _phrase_table(_PLATFORM_PHRASES, plurals=False)
_SIGNAL_FIRST_WORDS = frozenset(t[0] for table in (_GENRES, _MOODS) for t in table)


# ──────────────────────────────── output ────────────────────────────────


@dataclass(frozen=True)
class ReferenceTitle:
    """A catalogue game the query compares itself to."""

    game_id: UUID
    title: str
    as_written: str = field(compare=False)


@dataclass(frozen=True)
class ParsedQuery:
    """Signals read from one query. Every tuple is in first-mention order."""

    genres: tuple[str, ...] = ()
    moods: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    excluded_genres: tuple[str, ...] = ()
    excluded_moods: tuple[str, ...] = ()
    excluded_platforms: tuple[str, ...] = ()
    reference_titles: tuple[ReferenceTitle, ...] = ()
    unrecognised_references: tuple[str, ...] = ()
    word_count: int = 0
    # False when the catalogue couldn't be read, so no title was looked for.
    titles_checked: bool = True
    parser_version: str = PARSER_VERSION

    def log_fields(self) -> dict[str, Any]:
        """The parse as a log payload, without any of the player's own words.

        Labels come from the vocabularies and titles from the catalogue, so
        nothing here is query text. Unrecognised names are query text, so
        only their count is logged (as with library titles, test_csv_import).
        """
        return {
            "parser_version": self.parser_version,
            "word_count": self.word_count,
            "genres": list(self.genres),
            "moods": list(self.moods),
            "platforms": list(self.platforms),
            "excluded_genres": list(self.excluded_genres),
            "excluded_moods": list(self.excluded_moods),
            "excluded_platforms": list(self.excluded_platforms),
            "reference_titles": [
                {"game_id": str(r.game_id), "title": r.title} for r in self.reference_titles
            ],
            "unrecognised_reference_count": len(self.unrecognised_references),
            "titles_checked": self.titles_checked,
        }


# ────────────────────────────── title index ─────────────────────────────


def _content_words(normalised: str) -> int:
    words = normalised.split()
    return len(words) - (1 if words and words[0] == "the" else 0)


# "Dark Souls III" is usually typed "dark souls 3". "x" and "i" are left out:
# as words they are too often not numerals.
_ROMAN_NUMERALS = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7",
                   "viii": "8", "ix": "9"}
_SUBTITLE_SPLIT = re.compile(r"\s*:\s*|\s+[-–—]\s+")


def _with_digits(normalised: str) -> str:
    return " ".join(_ROMAN_NUMERALS.get(w, w) for w in normalised.split())


def _title_keys(title: str) -> dict[str, bool]:
    """Spellings a player might use for `title`, each normalised: {key: needs a cue}.

    The full title and its edition-stripped base, each with and without a
    leading "the" and with roman numerals as digits. The part before a
    subtitle ("Witcher 3" for "The Witcher 3: Wild Hunt") counts when it has
    two words of its own, so "Cities" alone never stands for "Cities:
    Skylines". The part after one ("Skyrim") counts only after a cue: "a wild
    hunt" is not a reference to The Witcher 3. Single-word keys always need one.
    """
    full = normalise_title(title)
    if not full:
        return {}
    forms = {full: False, strip_edition(full): False}
    parts = _SUBTITLE_SPLIT.split(title, maxsplit=1)
    if len(parts) == 2:
        head, tail = normalise_title(parts[0]), normalise_title(parts[1])
        if _content_words(head) >= 2:
            forms.setdefault(head, False)
        if tail:
            forms.setdefault(tail, True)
    keys: dict[str, bool] = {}
    for form, needs_cue in forms.items():
        variants = {form, _with_digits(form)}
        variants |= {v[len("the "):] for v in variants
                     if v.startswith("the ") and _content_words(v) >= 2}
        for key in variants:
            cue_only = needs_cue or _content_words(key) < 2
            keys[key] = keys.get(key, True) and cue_only
    return keys


class TitleIndex:
    """Catalogue titles by every key in _title_keys, for longest-match lookup."""

    def __init__(self, games: Iterable[CatalogueGame]) -> None:
        # Every key, for lookups after a cue; and the subset that counts without one.
        self._ids_by_key: dict[tuple[str, ...], list[UUID]] = {}
        self._uncued_ids_by_key: dict[tuple[str, ...], list[UUID]] = {}
        self._titles: dict[UUID, str] = {}
        for game in games:
            self._titles[game.game_id] = game.title
            for key, needs_cue in _title_keys(game.title).items():
                words = tuple(key.split())
                _add(self._ids_by_key, words, game.game_id)
                if not needs_cue:
                    _add(self._uncued_ids_by_key, words, game.game_id)
        self._max_words = max((len(k) for k in self._ids_by_key), default=0)

    def __len__(self) -> int:
        return len(self._titles)

    def title(self, game_id: UUID) -> str:
        return self._titles[game_id]

    def longest_match(
        self, tokens: Sequence[str | None], start: int, *, cued: bool,
    ) -> tuple[int, list[UUID]] | None:
        """The longest key starting at `start`, as (end, game ids), or None.

        Without a cue only keys that don't need one count (see _title_keys).
        None in `tokens` marks a word already used by another match.
        """
        keys = self._ids_by_key if cued else self._uncued_ids_by_key
        longest = min(self._max_words, len(tokens) - start)
        for length in range(longest, 0, -1):
            words = tuple(tokens[start:start + length])
            if None in words or "," in words:
                continue
            ids = keys.get(words)
            if not ids and words[-1].endswith("s"):
                # A possessive: "Hollow Knight's art" normalises to "hollow knights".
                ids = keys.get(words[:-1] + (words[-1][:-1],))
            if ids:
                return start + length, ids
        return None


def _add(index: dict[tuple[str, ...], list[UUID]], key: tuple[str, ...], game_id: UUID) -> None:
    ids = index.setdefault(key, [])
    if game_id not in ids:
        ids.append(game_id)


# ──────────────────────────────── parsing ───────────────────────────────


def _clauses(query: str) -> list[list[str]]:
    """Normalised words per sentence, with "," kept as a word of its own."""
    clauses = []
    for sentence in _CLAUSE_SPLIT.split(query):
        tokens: list[str] = []
        for piece in sentence.split(","):
            words = normalise_title(piece).split()
            if words:
                tokens.extend(words)
                tokens.append(",")
        if tokens:
            clauses.append(tokens[:-1])
    return clauses


def _cue_length(tokens: Sequence[str | None], i: int) -> int:
    for cue in _CUES:
        if tuple(tokens[i:i + len(cue)]) == cue:
            if cue == ("like",) and i > 0 and tokens[i - 1] in _LIKE_AS_VERB_AFTER:
                return 0
            return len(cue)
    return 0


def _unrecognised_name(tokens: Sequence[str | None], start: int) -> str:
    """The words after a cue that look like a title nobody recognised, or ""."""
    first = tokens[start]
    if first is None or first in _DESCRIPTION_STARTS or first in _SIGNAL_FIRST_WORDS:
        return ""
    words = []
    for token in tokens[start:start + _MAX_UNRECOGNISED_WORDS]:
        if token is None or token in _NAME_STOPS:
            break
        words.append(token)
    return " ".join(words)


@dataclass
class _ClauseTitles:
    references: list[tuple[str, list[UUID]]] = field(default_factory=list)
    unrecognised: list[str] = field(default_factory=list)


def _find_titles(tokens: list[str | None], index: TitleIndex) -> _ClauseTitles:
    """Match reference titles in one clause, setting their words to None."""
    found = _ClauseTitles()

    def take(start: int, end: int, ids: list[UUID]) -> None:
        found.references.append((" ".join(tokens[start:end]), ids))
        tokens[start:end] = [None] * (end - start)

    i = 0
    while i < len(tokens):
        cue = _cue_length(tokens, i)
        if not cue:
            i += 1
            continue
        j = i + cue
        is_first = True
        while j < len(tokens):
            hit = index.longest_match(tokens, j, cued=True)
            if hit is None:
                if is_first and (name := _unrecognised_name(tokens, j)):
                    found.unrecognised.append(name)
                break
            end, ids = hit
            take(j, end, ids)
            is_first = False
            j = end
            while j < len(tokens) and tokens[j] in _LIST_JOINERS:
                j += 1
            if j == end:
                break
        i = max(i + 1, j)

    # Uncued: only multi-word titles ("I loved Hollow Knight's art").
    i = 0
    while i < len(tokens):
        hit = index.longest_match(tokens, i, cued=False) if tokens[i] is not None else None
        if hit is None:
            i += 1
            continue
        end, ids = hit
        take(i, end, ids)
        i = end
    return found


def _is_negated(tokens: Sequence[str | None], i: int) -> bool:
    for token in reversed(tokens[max(0, i - _NEGATION_WINDOW):i]):
        if token in _NEGATION_BREAKS:
            return False
        if token in _NEGATORS:
            return True
    return False


def _scan(tokens: Sequence[str | None], table: dict) -> tuple[list, list]:
    """(wanted labels, excluded labels) for every phrase of `table` in `tokens`.

    A negation carries along an "or" list: in "nothing scary or fast paced"
    both are excluded, though "fast" is past the negation window.
    """
    wanted, excluded = [], []
    longest = max(len(k) for k in table)
    negated_until = -1  # end of the last excluded phrase
    i = 0
    while i < len(tokens):
        for length in range(min(longest, len(tokens) - i), 0, -1):
            words = tuple(tokens[i:i + length])
            label = table.get(words) if None not in words else None
            if label is not None:
                continues_list = (
                    negated_until >= 0
                    and i > negated_until
                    and all(t in ("or", "nor") for t in tokens[negated_until:i])
                )
                if continues_list or _is_negated(tokens, i):
                    excluded.append(label)
                    negated_until = i + length
                else:
                    wanted.append(label)
                i += length
                break
        else:
            i += 1
    return wanted, excluded


def _unique(items: Iterable[Any]) -> tuple:
    return tuple(dict.fromkeys(items))


def _flatten(platform_groups: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    return _unique(p for group in platform_groups for p in group)


def parse_query(query: str, index: TitleIndex | None) -> ParsedQuery:
    """Signals in `query`. With no `index`, reference titles aren't looked for."""
    clauses = _clauses(query)
    genres: list[str] = []
    moods: list[str] = []
    platforms: list[tuple[str, ...]] = []
    no_genres: list[str] = []
    no_moods: list[str] = []
    no_platforms: list[tuple[str, ...]] = []
    references: list[tuple[str, list[UUID]]] = []
    unrecognised: list[str] = []

    for words in clauses:
        tokens: list[str | None] = list(words)
        if index is not None:
            found = _find_titles(tokens, index)
            references += found.references
            unrecognised += found.unrecognised
        for table, wanted, excluded in (
            (_GENRES, genres, no_genres),
            (_MOODS, moods, no_moods),
            (_PLATFORMS, platforms, no_platforms),
        ):
            more, fewer = _scan(tokens, table)
            wanted += more
            excluded += fewer

    # A query that is nothing but a title ("hades") names that game, cue or not.
    if index is not None and not references and len(clauses) == 1:
        hit = index.longest_match(clauses[0], 0, cued=True)
        if hit is not None and hit[0] == len(clauses[0]):
            references.append((" ".join(clauses[0]), hit[1]))
            genres, moods, platforms = [], [], []  # its words were a title, not signals

    matched: dict[UUID, ReferenceTitle] = {}
    for as_written, ids in references:
        if len(ids) > 1:
            # Two games share the spelling; guessing would compare against the wrong one.
            unrecognised.append(as_written)
        elif ids[0] not in matched:
            matched[ids[0]] = ReferenceTitle(ids[0], index.title(ids[0]), as_written)

    return ParsedQuery(
        genres=_unique(genres),
        moods=_unique(moods),
        platforms=_flatten(platforms),
        excluded_genres=_unique(no_genres),
        excluded_moods=_unique(no_moods),
        excluded_platforms=_flatten(no_platforms),
        reference_titles=tuple(matched.values()),
        unrecognised_references=_unique(unrecognised),
        word_count=sum(1 for words in clauses for w in words if w != ","),
        titles_checked=index is not None,
    )


# ─────────────────────────────── service ────────────────────────────────

TitleIndexLoader = Callable[[], Awaitable["TitleIndex | None"]]

_shared_index: tuple[float, TitleIndex] | None = None


async def load_shared_title_index() -> TitleIndex | None:
    """The catalogue's TitleIndex, rebuilt at most every CATALOGUE_CACHE_SECONDS.

    None when there is no database configured.
    """
    global _shared_index
    if not has_db():
        return None
    now = time.monotonic()
    if _shared_index is None or now - _shared_index[0] > CATALOGUE_CACHE_SECONDS:
        from api.db import repositories  # repositories imports api.models -> api.services

        rows = await repositories.list_catalogue_titles()
        _shared_index = (now, TitleIndex(catalogue_from_rows(rows)))
    return _shared_index[1]


def reset_shared_title_index() -> None:
    """Forget the cached index (tests, or after reseeding the catalogue)."""
    global _shared_index
    _shared_index = None


class QueryParser:
    def __init__(self, load_titles: TitleIndexLoader = load_shared_title_index) -> None:
        self._load_titles = load_titles

    async def parse(self, query: str) -> ParsedQuery:
        """Parse `query` and log the result. Never raises for a query's content."""
        try:
            index = await self._load_titles()
        except Exception:
            # Titles are one signal of four; the others don't need the catalogue.
            log.warning("query.titles_unavailable", exc_info=True)
            index = None
        parsed = parse_query(query, index)
        log.info("query.parsed", extra={"query_parse": parsed.log_fields()})
        return parsed
