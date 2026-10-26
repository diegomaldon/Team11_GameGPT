"""The text embedded for each game: a documented, versioned template (TM11-38, REQ011).

Retrieval can only find what this text says, so it is built to read the way a
player would describe the game: what it is called, what kind of game it is,
what it feels like, then what it is about.

Template v1 (one labelled line per part, parts with nothing to say are left out):

    Title: <title>
    Genres: <genre>, <genre>, ...
    Tags: <tag>, <tag>, ...           up to MAX_TAGS, genres not repeated
    Description: <description>        HTML and extra whitespace removed

Why this order: the model (all-MiniLM-L6-v2) only reads the first 256 word
pieces. Title, genres and tags are short and say the most about how a game
feels, so they go first. A long description is what gets cut, never the tags.

Why labels: "Genres:" and "Tags:" tell the model what a list of words is, so
"Horror" in a tag list reads as a mood, not a stray word.

Changing the template: change build_game_document, bump TEMPLATE_VERSION, and
add the new version to docs/embedding-documents.md. Each game_embeddings row
records the version it was embedded with, and a row from an older version
counts as changed, so the next pipeline run re-embeds it (TM11-41).
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable, Mapping

# v0: TM11-39's "title description genres" joined by spaces, no tags.
# v1: labelled lines; title, genres, tags, then description.
TEMPLATE_VERSION = "v1"

MAX_TAGS = 15

_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def build_game_document(game: Mapping[str, Any]) -> str:
    """The text embedded for `game`, per template TEMPLATE_VERSION."""
    title = _clean(game.get("title"))
    genres = _unique(game.get("genres"))
    seen = {genre.casefold() for genre in genres}
    tags = [tag for tag in _unique(game.get("tags")) if tag.casefold() not in seen][:MAX_TAGS]
    description = _clean_description(game.get("description"))

    lines = [
        f"Title: {title}" if title else "",
        f"Genres: {', '.join(genres)}" if genres else "",
        f"Tags: {', '.join(tags)}" if tags else "",
        f"Description: {description}" if description else "",
    ]
    return "\n".join(line for line in lines if line)


def _clean(text: Any) -> str:
    return _WHITESPACE.sub(" ", str(text or "")).strip()


def _clean_description(text: Any) -> str:
    """Store descriptions can carry HTML (Steam's do). The model only needs the words."""
    without_tags = _HTML_TAG.sub(" ", str(text or ""))
    return _clean(html.unescape(without_tags))


def _unique(values: Iterable[Any] | None) -> list[str]:
    """Cleaned, non-blank values, first spelling kept, case-insensitive duplicates dropped."""
    seen: set[str] = set()
    result = []
    for value in values or []:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result
