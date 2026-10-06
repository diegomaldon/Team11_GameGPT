import json, tempfile, unittest
from pathlib import Path
import purchase_links as pl
from ingestion_report import validate_rows, write_run_report
from ingest_games import InMemoryStore, run_job

STEAM = "https://store.steampowered.com/app/271590"
XBOX = "https://www.xbox.com/en-US/games/store/grand-theft-auto-v/BPJ686W6S0NH"
EPIC = "https://store.epicgames.com/en-US/p/grand-theft-auto-v"


def row(i, links):
    return {"source": "rawg", "source_id": i, "title": f"G{i}", "purchase_links": links}


class CheckLink(unittest.TestCase):
    def test_valid_links(self):
        for p, u in (("STEAM", STEAM), ("XBOX", XBOX), ("EPIC", EPIC),
                     ("XBOX", "https://microsoft.com/p/gtav"),
                     ("STEAM", "https://store.steampowered.com/app/440/Team_Fortress_2/")):
            self.assertIsNone(pl.check_link(p, u), u)

    def test_invalid_links(self):
        cases = [
            ("STEAM", "http://store.steampowered.com/app/1", "https"),
            ("STEAM", "https://store.epicgames.com/p/x", "host"),
            ("STEAM", "https://store.steampowered.com/search?q=gta", "/app/"),
            ("EPIC", "https://evil.example/store.epicgames.com", "host"),
            ("EPIC", "https://store.epicgames.com.evil.example/p/x", "host"),
            ("XBOX", "https://user:pw@www.xbox.com/x", "credentials"),
            ("XBOX", "javascript:alert(1)", "https"),
            ("GOG", "https://www.gog.com/game/x", "unknown platform"),
            ("STEAM", "", "empty"),
            ("STEAM", None, "empty"),
            ("STEAM", "https://store.steampowered.com/app/1 x", "whitespace"),
            ("STEAM", "https://store.steampowered.com/app/" + "1" * 3000, "too long"),
        ]
        for p, u, why in cases:
            reason = pl.check_link(p, u)
            self.assertIsNotNone(reason, u)
            self.assertIn(why, reason)


class FromSources(unittest.TestCase):
    def test_rawg_stores_endpoint_fills_blank_detail_urls(self):
        detail = [{"store": {"id": 1, "slug": "steam"}, "url": ""},
                  {"store": {"id": 11, "slug": "epic-games"}, "url": ""}]
        stores = [{"store_id": 1, "url": "http://store.steampowered.com/app/271590"},
                  {"store_id": 11, "url": EPIC}]
        r = pl.from_rawg(detail, stores)
        self.assertEqual(r.links, {"STEAM": STEAM, "EPIC": EPIC})  # http upgraded
        self.assertEqual(r.rejected, [])

    def test_missing_links_stay_absent(self):
        r = pl.from_rawg([{"store": {"slug": "steam"}, "url": ""}], [])
        self.assertEqual(r.links, {})
        self.assertEqual(r.rejected, [])  # absent is not an error
        self.assertEqual(pl.from_rawg(None, None).links, {})
        self.assertEqual(pl.from_igdb(None).links, {})

    def test_unmapped_stores_ignored(self):
        r = pl.from_rawg([{"store": {"slug": "gog"}, "url": "https://www.gog.com/game/x"}],
                         [{"store_id": 3, "url": "https://store.playstation.com/x"}])
        self.assertEqual((r.links, r.rejected), ({}, []))

    def test_bad_url_rejected_and_later_valid_one_used(self):
        r = pl.from_rawg(stores_results=[{"store_id": 1, "url": "https://example.com/x"},
                                         {"store_id": 1, "url": STEAM}])
        self.assertEqual(r.links, {"STEAM": STEAM})
        self.assertEqual([x[0] for x in r.rejected], ["STEAM"])

    def test_first_valid_url_wins(self):
        other = "https://store.steampowered.com/app/999"
        r = pl.from_rawg(stores_results=[{"store_id": 1, "url": STEAM},
                                         {"store_id": 1, "url": other}])
        self.assertEqual(r.links, {"STEAM": STEAM})

    def test_igdb(self):
        r = pl.from_igdb([{"category": 13, "url": STEAM}, {"category": 16, "url": EPIC},
                          {"category": 3, "url": "https://en.wikipedia.org/wiki/GTAV"}])
        self.assertEqual(r.links, {"STEAM": STEAM, "EPIC": EPIC})

    def test_clean(self):
        r = pl.clean({"STEAM": STEAM, "EPIC": "https://example.com", "GOG": "https://gog.com"})
        self.assertEqual(r.links, {"STEAM": STEAM})
        self.assertEqual(sorted(x[0] for x in r.rejected), ["EPIC", "GOG"])
        self.assertEqual(pl.clean(None).links, {})


class Coverage(unittest.TestCase):
    def test_link_coverage(self):
        rows = [row(1, {"STEAM": STEAM}), row(2, {"STEAM": STEAM, "EPIC": EPIC}),
                row(3, {}), row(4, None)]
        c = pl.link_coverage(rows)
        self.assertEqual(c["any"], {"present": 2, "total": 4, "pct": 50.0})
        self.assertEqual(c["STEAM"]["present"], 2)
        self.assertEqual(c["EPIC"]["present"], 1)
        self.assertEqual(c["XBOX"]["pct"], 0.0)
        self.assertEqual(pl.link_coverage([])["any"]["pct"], 0.0)

    def test_report_includes_link_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            md = write_run_report(validate_rows([row(1, {"STEAM": STEAM}), row(2, {})]),
                                  "r", "rawg", Path(d))
            s = json.loads((md.parent / "ingestion_report.json").read_text())
            self.assertEqual(s["purchase_link_coverage"]["any"]["pct"], 50.0)
            self.assertEqual(s["coverage_valid_rows"]["purchase_links"]["present"], 1)
            self.assertIn("## Purchase link coverage", md.read_text())


class Validation(unittest.TestCase):
    def test_invalid_link_warns_but_row_kept(self):
        r = validate_rows([row(1, {"STEAM": "https://example.com/x"})])
        self.assertTrue(r.results[0].ok)
        self.assertIn("invalid purchase link: STEAM", r.results[0].warnings)

    def test_non_object_rejected(self):
        self.assertFalse(validate_rows([row(1, ["x"])]).results[0].ok)


class IngestJob(unittest.TestCase):
    def test_job_drops_bad_links_keeps_game_and_reports(self):
        rows = [row(1, {"STEAM": STEAM, "EPIC": "https://example.com/x"}), row(2, {})]
        with tempfile.TemporaryDirectory() as d:
            st = InMemoryStore()
            s = run_job(rows, st, "t", "rawg", limit=10, target=2, artifact_root=Path(d))
            self.assertEqual((s.inserted, s.links_kept, s.links_dropped), (2, 1, 1))
            self.assertEqual(st.rows[("rawg", "1")]["purchase_links"], {"STEAM": STEAM})
            self.assertEqual(st.rows[("rawg", "2")]["purchase_links"], {})
            self.assertEqual(s.dropped_links[0]["platform"], "EPIC")
            self.assertIn("Purchase links dropped", (Path(d) / "t" / "ingestion_run.md")
                          .read_text())
        self.assertEqual(rows[0]["purchase_links"]["EPIC"], "https://example.com/x")  # input untouched


if __name__ == "__main__":
    unittest.main()
