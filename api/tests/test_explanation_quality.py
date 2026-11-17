"""Explanation quality (TM11-70, REQ015).

The checks behind the before/after review, and the prompt change itself. No
model or database: the live run is scripts/eval_explanations.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.models import GameCandidate
from api.services.explanation_quality import (
    check_explanation,
    summarise,
    words,
)
from api.services.llm import _build_messages

def make_candidate(title: str) -> GameCandidate:
    return GameCandidate(game_id=uuid4(), title=title)


REQUEST = "something calm and low stress to unwind with after a long day"


def test_words_drop_function_words_and_plurals():
    assert words("I want some Roguelikes, with friends!") == ["roguelike", "friend"]


def test_a_reason_that_answers_the_request_passes():
    c = check_explanation(
        REQUEST,
        "You glide around a small island at your own pace, so it's an easy way to unwind "
        "after a long day.",
        genres=["Adventure"], tags=["relaxing", "exploration"],
    )
    assert c.uses_request and set(c.request_words) >= {"unwind", "long", "day"}
    assert c.passes


def test_a_genre_list_is_flagged_as_restated_labels():
    c = check_explanation(
        "roguelike deckbuilder where each run I build a new deck",
        "A roguelike deckbuilder with strategy and card game elements.",
        genres=["Roguelike", "Deckbuilder", "Strategy"], tags=["card game"],
    )
    assert c.labels_restated == ("Roguelike", "Deckbuilder", "Strategy", "card game")
    assert c.is_tag_list and not c.passes


def test_one_label_in_a_real_reason_is_not_a_tag_list():
    c = check_explanation(
        "turn-based tactics where I command a squad against an alien invasion",
        "You lead a squad against an alien invasion and lose soldiers for good, so every "
        "tactics decision matters.",
        genres=["Tactics", "Strategy"], tags=["turn-based"],
    )
    assert c.labels_restated == ("Tactics",)
    assert c.passes


@pytest.mark.parametrize("filler", [
    "Stardew Valley is the quintessential farming game, perfectly matching your query.",
    "A great choice that fits what you're looking for.",
    "This one ticks all the boxes.",
])
def test_stock_phrases_fail_even_when_the_request_is_named(filler):
    c = check_explanation("a cozy farming game", filler, genres=["Simulation"])
    assert c.stock_phrases
    assert not c.passes


def test_a_reason_sharing_no_request_word_fails():
    c = check_explanation("an emotional story that will probably make me cry",
                          "Beautiful hand-drawn art and a strong soundtrack.")
    assert not c.uses_request and not c.passes


def test_labels_match_across_hyphens_and_plurals():
    c = check_explanation("x", "Fast paced and story rich, with roguelikes.",
                          tags=["fast-paced", "story-rich"], genres=["Roguelike"])
    assert set(c.labels_restated) == {"fast-paced", "story-rich", "Roguelike"}


def test_summary_counts_each_check():
    checks = [
        check_explanation(REQUEST, "An easy game to unwind with after work."),
        check_explanation(REQUEST, "A perfect match."),
        check_explanation(REQUEST, "Roguelike Shooter", genres=["Roguelike", "Shooter"]),
    ]
    s = summarise(checks)
    assert (s.explanations, s.passing, s.using_request) == (3, 1, 1)
    assert (s.tag_lists, s.with_stock_phrases) == (1, 1)
    assert summarise([]).mean_words == 0.0


# ───── the prompt (AC: explanations reference the query, not just the game) ─────


def test_the_prompt_asks_for_the_request_in_the_players_terms_and_no_label_lists():
    system, user = _build_messages(REQUEST, [make_candidate("A Short Hike")], 1)
    assert f"Request: {REQUEST}" in user
    assert "tell the player in plain language why" in system
    assert "in their own terms" in user
    assert "Do not list genre or tag labels" in user
    assert "something concrete from the description" in user
    assert "perfect match" in user  # named as a phrase to avoid


def test_the_prompt_keeps_the_response_contract():
    _, user = _build_messages("x", [make_candidate("A"), make_candidate("B")], 2)
    # TM11-69's schema is unchanged: only the explanation rule grew.
    assert ('{"recommendations": [{"rank": 1, "index": <int>, "title": <string>, '
            '"explanation": <string>}]}') in user
    assert "Return exactly 2 games" in user
