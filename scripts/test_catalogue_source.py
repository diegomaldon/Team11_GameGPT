"""TM11-159: the seed-catalogue source and the hosted catalogue check.

Run from scripts/ like the other ingest tests:  cd scripts && python -m unittest -v
"""
import json
import tempfile
import unittest
from pathlib import Path

import catalogue_source as cs
from ingest_games import InMemoryStore, run_job
from verify_catalogue import benchmark_titles, evaluate, render

FIXTURE = cs.load_fixture()


def run(rows, store=None, target=167):
    d = Path(tempfile.mkdtemp())
    store = store or InMemoryStore()
    stats = run_job(rows, store, "t", "steam-seed", limit=10_000, target=target, artifact_root=d)
    return stats, store, d / "t"


class SeedSource(unittest.TestCase):
    # AC1: a source that doesn't depend on RAWG, with at least the 167 seed games
    def test_fixture_loads_all_167_without_rawg(self):
        stats, store, _ = run(cs.fetch_seed_catalogue())
        self.assertEqual(len(FIXTURE), 167)
        self.assertEqual((stats.fetched, stats.valid, stats.inserted, stats.rejected), (167, 167, 167, 0))
        self.assertTrue(stats.target_met)
        self.assertTrue(all(src == "steam" for src, _ in store.rows))

    def test_limit_is_honoured(self):
        self.assertEqual(len(list(cs.fetch_seed_catalogue(limit=5))), 5)

    # AC2: re-running is idempotent; unchanged rows are skipped
    def test_rerun_is_idempotent(self):
        store = InMemoryStore()
        run(cs.fetch_seed_catalogue(), store)
        again, _, _ = run(cs.fetch_seed_catalogue(), store)
        self.assertEqual((again.inserted, again.updated, again.unchanged), (0, 0, 167))
        self.assertEqual(len(store.rows), 167)

    # AC3: description, genres and steam_appid carried over
    def test_every_row_has_description_genres_and_appid(self):
        for entry, row in zip(FIXTURE, cs.fetch_seed_catalogue()):
            self.assertEqual(row["source_id"], entry["steam_appid"])
            self.assertEqual(row["description"], entry["description"])
            self.assertTrue(row["genres"])
            self.assertTrue(row["description"].strip())

    def test_mapping_to_hosted_columns(self):
        row = cs.to_ingest_row(FIXTURE[0])  # Half-Life 2, appid 220, score 0.97
        self.assertEqual(row["review_score"], 97)
        self.assertEqual(row["developers"], ["Valve"])
        self.assertEqual(row["available_platforms"], ["STEAM"])
        self.assertEqual(row["purchase_links"], {"STEAM": "https://store.steampowered.com/app/220"})
        self.assertIsNone(row["header_image_url"])   # not in the fixture, so not invented
        self.assertEqual(row["publishers"], [])

    def test_purchase_links_all_pass_validation(self):
        stats, _, _ = run(cs.fetch_seed_catalogue())
        self.assertEqual((stats.links_kept, stats.links_dropped), (167, 0))

    # AC3: rejected rows are logged with a reason
    def test_entry_without_appid_is_rejected_with_reason(self):
        bad = {**FIXTURE[0], "steam_appid": None, "title": "No App Id"}
        rows = list(cs.rows_from([bad, FIXTURE[1]]))
        self.assertEqual(rows[0]["purchase_links"], {})
        with self.assertLogs("ingest_games", "WARNING") as logs:
            stats, _, out = run(rows, target=1)
        self.assertEqual((stats.inserted, stats.rejected_validation), (1, 1))
        rec = json.loads((out / "rejects.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["stage"], "validation")
        self.assertIn("missing source or source_id", rec["errors"])
        self.assertTrue(any("rejected" in m for m in logs.output))

    def test_review_score_scaling(self):
        self.assertEqual(cs._review_score(0.5), 50)
        self.assertIsNone(cs._review_score(None))
        self.assertEqual(cs._review_score(88), 88)   # already 0..100, left alone


class BenchmarkCoverage(unittest.TestCase):
    # AC5: every TM11-63 benchmark title is in the seed catalogue
    def test_seed_catalogue_covers_every_benchmark_title(self):
        expected = benchmark_titles()
        self.assertGreater(len(expected), 0)
        self.assertEqual(expected - {r["title"] for r in cs.fetch_seed_catalogue()}, set())


def rows(n=3, **over):
    base = [{"title": f"G{i}", "description": "d", "genres": ["RPG"], "steam_appid": i,
             "embedded": True} for i in range(1, n + 1)]
    return [{**r, **over} for r in base]


class CatalogueCheck(unittest.TestCase):
    def test_all_pass(self):
        c = evaluate(rows(), {"G1"}, "m", min_games=3)
        self.assertTrue(c.ok, c.checks)
        self.assertIn("Result:** PASS", render(c))

    def test_too_few_games_fails(self):
        self.assertFalse(evaluate(rows(2), set(), "m", min_games=3).checks["size"])

    def test_duplicate_title_and_appid_fail(self):
        r = rows() + [{"title": " g1 ", "description": "d", "genres": [], "steam_appid": 2,
                       "embedded": True}]
        c = evaluate(r, set(), "m", min_games=1)
        self.assertEqual((c.duplicate_titles, c.duplicate_appids), (["g1"], [2]))
        self.assertFalse(c.ok)

    # AC4: every game embedded
    def test_unembedded_game_fails(self):
        r = rows(); r[1]["embedded"] = False
        c = evaluate(r, set(), "m", min_games=1)
        self.assertFalse(c.checks["embedded"])
        self.assertEqual(c.unembedded_titles, ["G2"])

    def test_missing_benchmark_title_fails(self):
        c = evaluate(rows(), {"G1", "Hades"}, "m", min_games=1)
        self.assertEqual(c.missing_benchmark_titles, ["Hades"])
        self.assertIn("- Hades", render(c))

    def test_field_gaps_reported_not_failed(self):
        r = rows(); r[0].update(description="", genres=[], steam_appid=None)
        c = evaluate(r, set(), "m", min_games=1)
        self.assertEqual((c.missing_description, c.missing_genres, c.missing_steam_appid), (1, 1, 1))
        self.assertTrue(c.ok)


if __name__ == "__main__":
    unittest.main()
