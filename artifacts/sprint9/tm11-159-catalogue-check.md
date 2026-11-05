# Hosted catalogue check (TM11-159)

- **Checked:** 2026-11-05T16:33:01+00:00
- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`
- **Result:** PASS

| Check | Result | Detail |
|---|---|---|
| Size | PASS | 1005 games (need 1000+) |
| Duplicates | PASS | 0 shared steam_appid, 0 shared title |
| Embedded | PASS | 1005 of 1005 have a vector |
| Benchmark titles | PASS | 69 of 69 present |

Field coverage (reported, not failed: the AC says "where available"):

- missing description: 0
- missing genres: 1
- missing steam_appid: 5
