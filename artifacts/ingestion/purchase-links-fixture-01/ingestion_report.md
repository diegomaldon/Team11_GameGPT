# Ingestion run report — purchase-links-fixture-01

- **Source:** rawg
- **Generated:** 2026-10-06T14:08:35+00:00
- **Rows fetched:** 3
- **Passed validation:** 3
- **Rejected:** 0

## Field coverage

Percentages are of rows that passed validation (the corpus that is actually ingested).
The all-rows column shows the same measure before rejects were removed.

| Field | Present | Coverage (valid rows) | Coverage (all rows) |
|---|---|---|---|
| description | 3 / 3 | 100.0% | 100.0% |
| genres | 3 / 3 | 100.0% | 100.0% |
| scores | 3 / 3 | 100.0% | 100.0% |
| platforms | 3 / 3 | 100.0% | 100.0% |
| purchase_links | 2 / 3 | 66.7% | 66.7% |

## Purchase link coverage

Rows (passed validation) holding a validated storefront link. Absent means the
source gave no usable URL; nothing is filled in or guessed.

| Storefront | Present | Coverage |
|---|---|---|
| any | 2 / 3 | 66.7% |
| STEAM | 2 / 3 | 66.7% |
| XBOX | 1 / 3 | 33.3% |
| EPIC | 0 / 3 | 0.0% |

## Rejections

None.

## Warnings (rows still ingested)

None.
