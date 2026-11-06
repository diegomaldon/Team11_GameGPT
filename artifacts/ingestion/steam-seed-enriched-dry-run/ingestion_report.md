# Ingestion run report — steam-seed-enriched-dry-run

- **Source:** steam-seed
- **Generated:** 2026-11-05T15:11:55+00:00
- **Rows fetched:** 167
- **Passed validation:** 167
- **Rejected:** 0

## Field coverage

Percentages are of rows that passed validation (the corpus that is actually ingested).
The all-rows column shows the same measure before rejects were removed.

| Field | Present | Coverage (valid rows) | Coverage (all rows) |
|---|---|---|---|
| description | 167 / 167 | 100.0% | 100.0% |
| genres | 167 / 167 | 100.0% | 100.0% |
| scores | 167 / 167 | 100.0% | 100.0% |
| platforms | 167 / 167 | 100.0% | 100.0% |
| purchase_links | 167 / 167 | 100.0% | 100.0% |

## Purchase link coverage

Rows (passed validation) holding a validated storefront link. Absent means the
source gave no usable URL; nothing is filled in or guessed.

| Storefront | Present | Coverage |
|---|---|---|
| any | 167 / 167 | 100.0% |
| STEAM | 167 / 167 | 100.0% |
| XBOX | 0 / 167 | 0.0% |
| EPIC | 0 / 167 | 0.0% |

## Rejections

None.

## Warnings (rows still ingested)

None.
