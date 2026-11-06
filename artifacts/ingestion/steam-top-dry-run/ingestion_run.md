# Ingestion job — steam-top-dry-run

- **Source:** steam-top  (dry run, nothing written to the database)
- **Started:** 2026-11-05T16:25:30+00:00
- **Duration:** 0.015s total (0.005s fetch, 0.001s load, 1000000.0 rows/s)

| Metric | Count |
|---|---|
| Fetched (limit 1000) | 1000 |
| Passed validation | 1000 |
| Inserted (new) | 1000 |
| Updated (present, values changed) | 0 |
| Unchanged (present, identical) | 0 |
| Adopted by title (row from another source given this id) | 0 |
| Rejected — validation | 0 |
| Rejected — database | 0 |
| Purchase links kept | 1000 |
| Purchase links dropped (failed validation) | 0 |
| **Loaded total** | **1000** |

**Target 1000+:** MET


Field coverage: see `ingestion_report.md` in this folder.
