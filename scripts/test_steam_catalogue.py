"""TM11-159: growing the catalogue to 1000 games from Steam's most-owned ranking.

Run from scripts/:  python -m unittest -v test_steam_catalogue
"""
import io
import json
import unittest

import steam_catalogue as sc
from ingest_games import InMemoryStore, run_job


def details(**over):
    base = {"success": True, "name": "Game", "type": "game", "short_description": "A <b>fun</b> game &amp; more.",
            "genres": ["Action", "Free To Play"], "release_date": "Apr 18, 2011", "content_descriptors": [],
            "developers": ["Dev"], "publishers": ["Pub"], "metacritic": 88,
            "header_image": "https://cdn/x.jpg", "categories": ["Single-player", "Co-op"]}
    return {**base, **over}


def ranked(appid, name="Game", pos=900, neg=100):
    return {"appid": appid, "name": name, "positive": pos, "negative": neg}


SEED = [{"source": "steam", "source_id": 620, "title": "Portal 2"}]


class Mapping(unittest.TestCase):
    def test_row_shape(self):
        row = sc.to_row(ranked(10), details(), {"Roguelike": 50, "Co-op": 40, "Indie": 60})
        self.assertEqual(row["description"], "A fun game & more.")
        self.assertEqual(row["genres"], ["Action"])                       # pricing label dropped
        self.assertEqual(row["tags"], ["Indie", "Roguelike", "Co-op", "Single-player"])  # votes, then categories
        self.assertEqual((row["review_score"], row["critic_score"]), (90, 88))
        self.assertEqual(row["release_date"], "2011-04-18")
        self.assertEqual(row["purchase_links"], {"STEAM": "https://store.steampowered.com/app/10"})
        self.assertEqual((row["source"], row["source_id"], row["available_platforms"]), ("steam", 10, ["STEAM"]))

    def test_release_date_formats(self):
        self.assertEqual(sc.parse_release_date("16 Nov, 2004"), "2004-11-16")
        self.assertEqual(sc.parse_release_date("November 16, 2004"), "2004-11-16")
        self.assertIsNone(sc.parse_release_date("Coming soon"))
        self.assertIsNone(sc.parse_release_date(None))

    def test_review_score_needs_enough_reviews(self):
        self.assertIsNone(sc.review_score(ranked(1, pos=10, neg=5)))
        self.assertEqual(sc.review_score(ranked(1, pos=75, neg=25)), 75)

    def test_long_description_truncated(self):
        self.assertEqual(len(sc.clean_text("x" * 5000)), sc.MAX_DESCRIPTION)


class Skips(unittest.TestCase):
    def test_reasons(self):
        cases = [(None, "no cached Steam details"), ({"success": False}, "unknown to Steam"),
                 (details(type="dlc"), "not a game (type 'dlc')"),
                 (details(content_descriptors=[3]), "adult-only content"),
                 (details(genres=["Utilities", "Design & Illustration"]), "software, not a game"),
                 (details(short_description=""), "no description")]
        for d, want in cases:
            self.assertEqual(sc.skip_reason(d), want)
        self.assertIsNone(sc.skip_reason(details(content_descriptors=[2, 5])))  # violence/mature is fine
        self.assertIsNone(sc.skip_reason(details(genres=["Free To Play"])))     # The Lab: a game, not software
        self.assertEqual(sc.skip_reason(details(genres=["Free To Play", "Utilities"])), "software, not a game")

    def test_genres_from_tags_when_store_has_only_a_pricing_label(self):
        row = sc.to_row(ranked(1), details(genres=["Free To Play"]), {"VR": 90, "Action": 50, "Casual": 40})
        self.assertEqual(row["genres"], ["Action", "Casual"])

    def test_select_order_target_and_dedupe(self):
        ranking = [ranked(620, "Portal 2"), ranked(1, "A"), ranked(2, "Tool"), ranked(3, "a"),
                   ranked(4, "B"), ranked(5, "C")]
        det = {"1": details(name="A"), "2": details(type="application"), "3": details(name="a"),
               "4": details(name="B"), "5": details(name="C")}
        rows, skips = sc.select(ranking, det, {}, SEED, target=3)
        self.assertEqual([r["title"] for r in rows], ["Portal 2", "A", "B"])   # seed first, rank order, stops at 3
        self.assertEqual([(s["appid"], s["reason"]) for s in skips],
                         [(2, "not a game (type 'application')"), (3, "title 'a' already in the catalogue")])

    def test_seed_title_blocks_a_ranked_duplicate(self):
        rows, skips = sc.select([ranked(99, "Portal 2")], {"99": details(name="Portal 2")}, {}, SEED, 5)
        self.assertEqual(len(rows), 1)
        self.assertIn("already in the catalogue", skips[0]["reason"])


class Fetching(unittest.TestCase):
    def test_ranking_page_parsed(self):
        page = {"730": {"appid": 730, "name": "CS", "positive": 5, "negative": 1}, "x": {"name": "no id"}}
        self.assertEqual(sc.fetch_ranking_page(0, get=lambda url: page),
                         [{"appid": 730, "name": "CS", "positive": 5, "negative": 1}])

    def test_tags_parsed(self):
        self.assertEqual(sc.fetch_tags(1, get=lambda url: {"tags": {"Indie": 3, "bad": "x"}}), {"Indie": 3})
        self.assertEqual(sc.fetch_tags(1, get=lambda url: {"tags": []}), {})


class CachedCatalogue(unittest.TestCase):
    """Against the committed caches: the actual 1000-game load."""

    @classmethod
    def setUpClass(cls):
        cls.rows = list(sc.fetch_top_steam_catalogue(limit=1000))

    def test_reaches_1000_unique_games(self):
        self.assertEqual(len(self.rows), 1000)
        self.assertEqual(len({r["source_id"] for r in self.rows}), 1000)
        self.assertEqual(len({r["title"].casefold() for r in self.rows}), 1000)

    def test_seed_catalogue_comes_first_and_whole(self):
        self.assertTrue(all(r["purchase_links"] for r in self.rows[:167]))
        seed_ids = {r["source_id"] for r in sc.cs.fetch_seed_catalogue()}
        self.assertEqual({r["source_id"] for r in self.rows[:167]}, seed_ids)

    def test_every_game_has_description_and_genres(self):
        self.assertTrue(all(r["description"] and r["genres"] for r in self.rows))

    def test_loads_and_reruns_idempotently(self):
        store = InMemoryStore()
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        first = run_job(iter(self.rows), store, "a", "steam-top", limit=1000, target=1000, artifact_root=d)
        again = run_job(sc.fetch_top_steam_catalogue(limit=1000), store, "b", "steam-top",
                        limit=1000, target=1000, artifact_root=d)
        self.assertEqual((first.inserted, first.rejected, first.links_dropped), (1000, 0, 0))
        self.assertEqual((again.inserted, again.updated, again.unchanged), (0, 0, 1000))


if __name__ == "__main__":
    unittest.main()
