"""The per-game embedding document, template v1 (TM11-38, REQ011)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import game_document
from api.services.game_document import MAX_TAGS, TEMPLATE_VERSION, build_game_document

FIXTURE = Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "games.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "embedding-documents.md"


def hades() -> dict:
    return {
        "title": "Hades",
        "description": "Battle out of the Underworld in a rogue-like dungeon crawler.",
        "genres": ["Action", "Indie"],
        "tags": ["Roguelike", "Mythology", "Fast-Paced"],
    }


# ── AC: composed from title, description, genres and tags ───────────────────


def test_document_follows_the_v1_template():
    assert build_game_document(hades()) == (
        "Title: Hades\n"
        "Genres: Action, Indie\n"
        "Tags: Roguelike, Mythology, Fast-Paced\n"
        "Description: Battle out of the Underworld in a rogue-like dungeon crawler."
    )


def test_short_fields_come_before_the_description():
    """The model reads only the start, so a long description is what gets cut."""
    game = {**hades(), "description": "word " * 500}
    document = build_game_document(game)

    assert document.index("Tags:") < document.index("Description:")


def test_missing_parts_are_left_out():
    game = {"title": "Celeste", "description": None, "genres": [], "tags": None}

    assert build_game_document(game) == "Title: Celeste"


def test_a_game_without_tags_key_still_builds():
    game = {"title": "Celeste", "genres": ["Platformer"]}

    assert build_game_document(game) == "Title: Celeste\nGenres: Platformer"


def test_tags_that_repeat_a_genre_are_dropped():
    game = {**hades(), "tags": ["action", "Roguelike", "INDIE"]}

    assert "Tags: Roguelike\n" in build_game_document(game)


def test_duplicate_and_blank_values_are_dropped():
    game = {**hades(), "genres": ["Action", " action ", ""], "tags": ["Roguelike", "roguelike", "  "]}
    document = build_game_document(game)

    assert "Genres: Action\n" in document
    assert "Tags: Roguelike\n" in document


def test_tags_are_capped():
    game = {**hades(), "tags": [f"tag{n}" for n in range(MAX_TAGS + 10)]}
    tag_line = next(line for line in build_game_document(game).splitlines() if line.startswith("Tags:"))

    assert len(tag_line.removeprefix("Tags: ").split(", ")) == MAX_TAGS


def test_html_and_extra_whitespace_are_removed_from_the_description():
    game = {**hades(), "description": "<p>Fight&nbsp;your way <b>out</b>\n\n of hell.</p><br/>"}

    assert build_game_document(game).endswith("Description: Fight your way out of hell.")


def test_whitespace_in_the_title_is_tidied():
    game = {**hades(), "title": "  Hades \n II "}

    assert build_game_document(game).startswith("Title: Hades II\n")


def test_the_same_game_always_builds_the_same_text():
    """The pipeline's change check hashes this text, so it must be stable."""
    assert build_game_document(hades()) == build_game_document(hades())


@pytest.mark.parametrize("game", json.loads(FIXTURE.read_text(encoding="utf-8")), ids=lambda g: g["title"])
def test_every_fixture_game_builds_a_document_with_its_tags(game):
    document = build_game_document(game)

    assert document.startswith(f"Title: {game['title']}")
    assert "Description:" in document
    if game.get("tags"):
        assert "Tags:" in document


# ── AC: documented template, versioned ──────────────────────────────────────


def test_template_version_is_a_v_number():
    assert TEMPLATE_VERSION.startswith("v") and TEMPLATE_VERSION[1:].isdigit()


def test_the_current_version_is_documented():
    assert f"## {TEMPLATE_VERSION}" in DOC.read_text(encoding="utf-8")


def test_the_module_docstring_shows_the_current_template():
    assert f"Template {TEMPLATE_VERSION}" in game_document.__doc__
