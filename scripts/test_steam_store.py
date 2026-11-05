"""TM11-159: Steam store enrichment of the seed catalogue.

Run from scripts/:  python -m unittest -v test_steam_store
"""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import catalogue_source as cs
import steam_store as ss
from ingest_games import InMemoryStore, run_job

CACHE = ss.load_cache()
FIXTURE = cs.load_fixture()

# Steam's store name differs from the fixture title only by edition or styling.
# Each was checked by hand; anything else means the fixture's appid is wrong
# (ten were, pointing at other games, before TM11-159 corrected them).
KNOWN_RENAMES = {
    "Warhammer 40,000: Dawn of War": "Warhammer 40,000: Dawn of War - Anniversary Edition (Classic)",
    "Civilization V": "Sid Meier's Civilization® V",
    "Kentucky Route Zero": "Kentucky Route Zero: PC Edition",
    "Deus Ex: Human Revolution": "Deus Ex: Human Revolution - Director's Cut",
    "Risk of Rain": "Risk of Rain (2013)",
    "Shovel Knight": "Shovel Knight: Treasure Trove",
    "Grand Theft Auto V": "Grand Theft Auto V Legacy",
    "Sid Meier's Civilization VI": "Sid Meier’s Civilization® VI",
    "The Witcher 3: Wild Hunt": "The Witcher 3: Wild Hunt — Remastered",
    "Divinity: Original Sin": "Divinity: Original Sin - Enhanced Edition",
    "DOOM (2016)": "DOOM",
    "Divinity: Original Sin 2": "Divinity: Original Sin 2 - Definitive Edition",
    "Human: Fall Flat": "Human Fall Flat",
    "Prey (2017)": "Prey",
    "Nioh": "Nioh: Complete Edition",
    "Disco Elysium": "Disco Elysium - The Final Cut",
    "Sekiro: Shadows Die Twice": "Sekiro™: Shadows Die Twice - GOTY Edition",
    "Spiritfarer": "Spiritfarer®: Farewell Edition",
    "Sea of Thieves": "Sea of Thieves: 2026 Edition",
    "Potion Craft": "Potion Craft: Alchemist Simulator",
    "Age of Empires IV": "Age of Empires IV: Anniversary Edition",
    "God of War (2018)": "God of War",
    "Hitman 3": "HITMAN World of Assassination",
    "Dead Space (2023)": "Dead Space",
    "Marvel's Spider-Man Remastered": "Marvel’s Spider-Man Remastered",
}

PORTAL2 = {"620": {"success": True, "data": {
    "name": "Portal 2", "developers": ["Valve"], "publishers": ["Valve", ""],
    "metacritic": {"score": 95}, "header_image": "https://cdn/620/header.jpg",
    "categories": [{"description": "Single-player"}, {"description": "Co-op"},
                   {"description": "Co-op"}, {"description": " "}]}}}


def _clean(name: str) -> str:
    return name.replace("™", "").replace("®", "").casefold()


class CacheMatchesFixture(unittest.TestCase):
    def test_cache_covers_every_fixture_appid(self):
        self.assertEqual(set(CACHE), {str(g["steam_appid"]) for g in FIXTURE})

    def test_every_appid_is_the_game_the_fixture_names(self):
        for g in FIXTURE:
            entry = CACHE[str(g["steam_appid"])]
            self.assertTrue(entry["success"], g["title"])
            if _clean(entry["name"]) != _clean(g["title"]):
                self.assertEqual(KNOWN_RENAMES.get(g["title"]), entry["name"],
                                 f"steam:{g['steam_appid']} is {entry['name']!r}, not {g['title']!r}")


class Trim(unittest.TestCase):
    def test_keeps_only_catalogue_fields(self):
        t = ss.trim(620, PORTAL2)
        self.assertEqual(t, {"success": True, "name": "Portal 2", "developers": ["Valve"],
                             "publishers": ["Valve"], "metacritic": 95,
                             "header_image": "https://cdn/620/header.jpg",
                             "categories": ["Single-player", "Co-op"]})

    def test_unknown_app(self):
        self.assertEqual(ss.trim(1, {"1": {"success": False}}), {"success": False})

    def test_out_of_range_metacritic_dropped(self):
        bad = json.loads(json.dumps(PORTAL2)); bad["620"]["data"]["metacritic"] = {"score": 140}
        self.assertIsNone(ss.trim(620, bad)["metacritic"])


class Fetch(unittest.TestCase):
    def test_429_backs_off_then_succeeds(self):
        calls, waits = [], []

        def opener(req, timeout):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
            return io.BytesIO(json.dumps(PORTAL2).encode())

        self.assertTrue(ss.fetch_appdetails(620, opener=opener, sleep=waits.append)["success"])
        self.assertEqual((len(calls), waits), (2, [30]))
        self.assertIn("appids=620", calls[0])

    def test_404_is_not_retried(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            ss.fetch_appdetails(620, opener=opener, sleep=lambda s: None)

    def test_update_cache_only_fetches_missing_and_counts(self):
        cache = {"1": {"success": True}}
        fetched = []

        def fetch(a):
            fetched.append(a)
            if a == 3:
                raise RuntimeError("boom")
            return {"success": a != 2}

        with self.assertLogs("steam_store", "ERROR"):
            counts = ss.update_cache([1, 2, 3, 4], cache, fetch=fetch, sleep=lambda s: None)
        self.assertEqual(fetched, [2, 3, 4])
        self.assertEqual(counts, {"fetched": 2, "unknown": 1, "failed": 1, "cached": 1})
        self.assertNotIn("3", cache)   # a failure isn't cached, so a rerun retries it


class Enrich(unittest.TestCase):
    def test_merges_store_fields_and_keeps_fixture_text(self):
        row = cs.to_ingest_row(next(g for g in FIXTURE if g["steam_appid"] == 620))
        out = cs.enrich(row, ss.trim(620, PORTAL2))
        self.assertEqual((out["critic_score"], out["publishers"], out["header_image_url"]),
                         (95, ["Valve"], "https://cdn/620/header.jpg"))
        self.assertEqual(out["tags"][:len(row["tags"])], row["tags"])
        # the fixture already tags Portal 2 "co-op", so Steam's "Co-op" isn't added twice
        self.assertIn("co-op", row["tags"])
        self.assertEqual(out["tags"][len(row["tags"]):], ["Single-player"])
        self.assertEqual((out["description"], out["genres"], out["review_score"]),
                         (row["description"], row["genres"], row["review_score"]))

    def test_unknown_app_loads_unenriched(self):
        row = cs.to_ingest_row(FIXTURE[0])
        self.assertEqual(cs.enrich(row, {"success": False}), row)
        self.assertEqual(cs.enrich(row, None), row)

    def test_missing_cache_entry_is_logged(self):
        d = Path(tempfile.mkdtemp()) / "cache.json"
        d.write_text("{}")
        with self.assertLogs("catalogue_source", "WARNING") as logs:
            rows = list(cs.fetch_steam_enriched_catalogue(limit=1, cache_path=d))
        self.assertIsNone(rows[0]["header_image_url"])
        self.assertIn("no cached Steam details", logs.output[0])


class EnrichedLoad(unittest.TestCase):
    def run_it(self, store):
        d = Path(tempfile.mkdtemp())
        return run_job(cs.fetch_steam_enriched_catalogue(), store, "t", "steam-seed",
                       limit=10_000, target=167, artifact_root=d)

    # AC1 + AC3: all 167 load, in the RAWG-era column shape where Steam has the data
    def test_all_167_load_with_store_fields(self):
        store = InMemoryStore()
        s = self.run_it(store)
        self.assertEqual((s.valid, s.inserted, s.rejected, s.links_dropped), (167, 167, 0, 0))
        rows = list(store.rows.values())
        self.assertEqual(sum(bool(r["header_image_url"]) for r in rows), 167)
        self.assertGreaterEqual(sum(bool(r["publishers"]) for r in rows), 160)
        self.assertGreaterEqual(sum(r["critic_score"] is not None for r in rows), 140)
        self.assertTrue(all(r["description"] and r["genres"] for r in rows))

    # AC2: the cached source is deterministic, so a re-run changes nothing
    def test_rerun_is_idempotent(self):
        store = InMemoryStore()
        self.run_it(store)
        again = self.run_it(store)
        self.assertEqual((again.inserted, again.updated, again.unchanged), (0, 0, 167))


if __name__ == "__main__":
    unittest.main()
