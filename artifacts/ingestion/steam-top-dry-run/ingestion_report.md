# Ingestion run report — steam-top-dry-run

- **Source:** steam-top
- **Generated:** 2026-11-05T16:25:30+00:00
- **Rows fetched:** 1000
- **Passed validation:** 1000
- **Rejected:** 0

## Field coverage

Percentages are of rows that passed validation (the corpus that is actually ingested).
The all-rows column shows the same measure before rejects were removed.

| Field | Present | Coverage (valid rows) | Coverage (all rows) |
|---|---|---|---|
| description | 1000 / 1000 | 100.0% | 100.0% |
| genres | 1000 / 1000 | 100.0% | 100.0% |
| scores | 997 / 1000 | 99.7% | 99.7% |
| platforms | 1000 / 1000 | 100.0% | 100.0% |
| purchase_links | 1000 / 1000 | 100.0% | 100.0% |

## Purchase link coverage

Rows (passed validation) holding a validated storefront link. Absent means the
source gave no usable URL; nothing is filled in or guessed.

| Storefront | Present | Coverage |
|---|---|---|
| any | 1000 / 1000 | 100.0% |
| STEAM | 1000 / 1000 | 100.0% |
| XBOX | 0 / 1000 | 0.0% |
| EPIC | 0 / 1000 | 0.0% |

## Rejections

None.

## Warnings (rows still ingested)

None.
