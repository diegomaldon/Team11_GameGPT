import json, tempfile, unittest
from pathlib import Path
from ingestion_report import validate_rows, coverage, write_run_report

GOOD = {"source": "rawg", "source_id": 1, "title": "A", "description": "d", "genres": ["RPG"],
        "available_platforms": ["STEAM"], "review_score": 80}

class T(unittest.TestCase):
    def test_required_fields_per_row(self):
        rows = [GOOD, {**GOOD, "source_id": 2, "title": " "}, {**GOOD, "source_id": None}]
        r = validate_rows(rows)
        self.assertEqual([x.ok for x in r.results], [True, False, False])

    def test_duplicates_rejected(self):
        r = validate_rows([GOOD, dict(GOOD)])
        self.assertTrue(r.results[0].ok and not r.results[1].ok)

    def test_score_range_and_types(self):
        r = validate_rows([{**GOOD, "review_score": 101}, {**GOOD, "source_id": 3, "genres": "RPG"}])
        self.assertFalse(any(x.ok for x in r.results))

    def test_unscaled_rawg_warns(self):
        r = validate_rows([{**GOOD, "review_score": 4.5}])
        self.assertTrue(r.results[0].ok and r.results[0].warnings)

    def test_coverage(self):
        rows = [GOOD, {"source_id": 2, "title": "B", "description": "", "genres": [],
                       "available_platforms": ["EPIC"], "review_score": None, "critic_score": None}]
        c = coverage(rows)
        self.assertEqual(c["description"]["pct"], 50.0)
        self.assertEqual(c["genres"]["pct"], 50.0)
        self.assertEqual(c["scores"]["pct"], 50.0)
        self.assertEqual(c["platforms"]["pct"], 100.0)

    def test_empty_input_no_zero_division(self):
        self.assertEqual(coverage([])["genres"]["pct"], 0.0)

    def test_artifact_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_run_report(validate_rows([GOOD]), "run1", "rawg", Path(d))
            self.assertTrue(p.exists())
            self.assertEqual(json.loads((p.parent / "ingestion_report.json").read_text())["rows_valid"], 1)

if __name__ == "__main__":
    unittest.main()
