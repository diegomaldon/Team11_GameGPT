import json, tempfile, unittest
from pathlib import Path
from ingest_games import InMemoryStore, run_job, build_upsert_sql, normalise, PostgresStore, DATA_COLUMNS

def make(n, start=1):
    return [{"source": "rawg", "source_id": i, "title": f"G{i}", "description": "d",
             "genres": ["RPG"], "tags": [], "available_platforms": ["STEAM"],
             "purchase_links": {}, "review_score": 80, "critic_score": 75,
             "release_date": "2020-01-01", "developers": ["x"], "publishers": ["y"],
             "header_image_url": "u"} for i in range(start, start + n)]

class FailingStore(InMemoryStore):
    def upsert(self, row):
        if row["source_id"] == 5:
            raise RuntimeError("check constraint violated")
        return super().upsert(row)

class T(unittest.TestCase):
    def run_it(self, rows, store=None, **kw):
        d = tempfile.mkdtemp()
        store = store or InMemoryStore()
        kw.setdefault("limit", 10_000)
        s = run_job(rows, store, "t", "rawg", artifact_root=Path(d), **kw)
        return s, store, Path(d) / "t"

    def test_loads_3000_and_meets_target(self):
        s, st, _ = self.run_it(make(3200), limit=3000, target=3000)
        self.assertEqual((s.fetched, s.inserted, s.target_met), (3000, 3000, True))
        self.assertEqual(len(st.rows), 3000)

    def test_idempotent_rerun(self):
        store = InMemoryStore()
        self.run_it(make(50), store)
        s2, _, _ = self.run_it(make(50), store)
        self.assertEqual((s2.inserted, s2.updated, s2.unchanged, len(store.rows)), (0, 0, 50, 50))
        changed = make(50); changed[0]["title"] = "Renamed"
        s3, _, _ = self.run_it(changed, store)
        self.assertEqual((s3.inserted, s3.updated, s3.unchanged), (0, 1, 49))

    def test_validation_rejects_logged_to_file(self):
        rows = make(5) + [{**make(1, 99)[0], "title": ""}, make(1, 1)[0]]  # blank title + dup id
        s, st, out = self.run_it(rows, target=1)
        self.assertEqual((s.valid, s.rejected_validation), (5, 2))
        lines = [json.loads(l) for l in (out / "rejects.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(l["stage"] == "validation" and l["errors"] for l in lines))

    def test_database_failure_is_recorded_not_swallowed(self):
        s, st, out = self.run_it(make(10), FailingStore(), target=1)
        self.assertEqual((s.inserted, s.rejected_database), (9, 1))
        rec = json.loads((out / "rejects.jsonl").read_text().splitlines()[0])
        self.assertEqual(rec["stage"], "database")
        self.assertIn("check constraint", rec["errors"][0])

    def test_unknown_source_rejected(self):
        rows = make(2) + [{**make(1, 7)[0], "source": "epic"}]
        s, _, _ = self.run_it(rows, target=1)
        self.assertEqual((s.valid, s.rejected_validation), (2, 1))

    def test_target_shortfall_flagged(self):
        s, _, _ = self.run_it(make(10), target=3000)
        self.assertFalse(s.target_met)
        self.assertTrue(any("shortfall" in n for n in s.notes))

    def test_run_summary_artifacts_written(self):
        s, _, out = self.run_it(make(10), target=1)
        j = json.loads((out / "ingestion_run.json").read_text())
        self.assertEqual((j["inserted"], j["loaded"]), (10, 10))
        self.assertIn("Duration", (out / "ingestion_run.md").read_text())
        self.assertTrue((out / "ingestion_report.md").exists())


class FakeConn:
    def __init__(self, result): self.calls, self.result = [], result
    def transaction(self):
        import contextlib; return contextlib.nullcontext()
    def execute(self, sql, vals):
        self.calls.append((sql, vals)); r = self.result
        class C:
            def fetchone(_): return r
        return C()

class SqlTests(unittest.TestCase):
    def test_sql_shape_matches_ddl(self):
        sql = build_upsert_sql("rawg_id")
        self.assertIn("ON CONFLICT (rawg_id) DO UPDATE", sql)
        self.assertIn("%s::public.platform_type[]", sql)
        self.assertIn("%s::jsonb", sql)
        self.assertIn("IS DISTINCT FROM", sql)
        self.assertNotIn("embedding", sql)                 # never clobber embeddings
        self.assertEqual(sql.count("%s"), 1 + len(DATA_COLUMNS))

    def test_null_not_null_columns_become_empty(self):
        n = normalise({**make(1)[0], "genres": None, "tags": None, "purchase_links": None,
                       "developers": None, "publishers": None, "available_platforms": None})
        self.assertEqual((n["genres"], n["purchase_links"], n["available_platforms"]), ([], {}, []))

    def _store(self, result):
        st = PostgresStore.__new__(PostgresStore)
        class Jsonb:
            def __init__(self, v): self.v = v
        st._Jsonb, st.conn = Jsonb, FakeConn(result); return st

    def test_upsert_states_and_param_count(self):
        for result, want in (((True,), "inserted"), ((False,), "updated"), (None, "unchanged")):
            st = self._store(result)
            self.assertEqual(st.upsert(make(1)[0]), want)
            sql, vals = st.conn.calls[0]
            self.assertEqual(len(vals), sql.count("%s"))

if __name__ == "__main__":
    unittest.main()
