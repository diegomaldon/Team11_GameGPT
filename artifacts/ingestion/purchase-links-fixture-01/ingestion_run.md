# Ingestion job — purchase-links-fixture-01

- **Source:** rawg  (dry run, nothing written to the database)
- **Started:** 2026-10-06T14:08:35+00:00
- **Duration:** 0.001s total (0.0s fetch, 0.0s load, 0 rows/s)

| Metric | Count |
|---|---|
| Fetched (limit 3000) | 3 |
| Passed validation | 3 |
| Inserted (new) | 3 |
| Updated (present, values changed) | 0 |
| Unchanged (present, identical) | 0 |
| Rejected — validation | 0 |
| Rejected — database | 0 |
| Purchase links kept | 3 |
| Purchase links dropped (failed validation) | 1 |
| **Loaded total** | **3** |

**Target 3+:** MET


Dropped purchase links:

- `rawg:3499` EPIC: host 'example.com' is not allowed for EPIC

Field coverage: see `ingestion_report.md` in this folder.
