# Purchase link enrichment (TM11-37, REQ012)

`games.purchase_links` is jsonb keyed by `platform_type`:

```json
{"STEAM": "https://store.steampowered.com/app/271590", "XBOX": "https://www.xbox.com/..."}
```

A key exists only when the metadata source supplied a URL for that storefront and the URL
passed validation. No link is ever built, guessed, or filled from another source. A
missing storefront means no key, and a game with no usable links stores `{}`.

## Where links come from

| Source | Field | Notes |
|---|---|---|
| RAWG `/games/{id}/stores` | `results[].store_id`, `url` | Holds the real URLs. Store ids 1 = Steam, 2 / 7 = Xbox, 11 = Epic |
| RAWG `/games/{id}` | `stores[].store.slug`, `url` | `url` is usually `""`. `fetch_metadata.py` calls `/stores` only when it is blank |
| IGDB `websites` | `category`, `url` | 13 = Steam, 16 = Epic. IGDB has no Xbox store category |

Stores with no `platform_type` value (GOG, PlayStation, Nintendo, itch, mobile) are ignored.

## Validation (`scripts/purchase_links.py: check_link`)

- `https` only. `http://` is upgraded to `https://` because all three stores serve TLS.
- The host must be on the storefront's allowlist:
  - STEAM: `store.steampowered.com`
  - XBOX: `www.xbox.com`, `xbox.com`, `www.microsoft.com`, `microsoft.com`
  - EPIC: `store.epicgames.com`, `www.epicgames.com`, `epicgames.com`
- Steam links must be `/app/<id>` pages.
- The URL may not contain credentials, a port, or whitespace, and may be at most 2048 characters.
- The key must be a `platform_type` value.

If more than one URL is valid for a storefront, the first one is kept.

`ingest_games.py` re-checks every row before loading it. A bad link is dropped and logged,
and the game itself is still loaded. The run summary (`ingestion_run.md`) counts kept and
dropped links and lists every dropped link with its reason. When `ingestion_report.py` is
run on its own, it flags a bad link as an `invalid purchase link` warning.

## Coverage

`ingestion_report.md` has a `purchase_links` row in the field-coverage table and a
**Purchase link coverage** section that breaks coverage down per storefront.
`artifacts/ingestion/purchase-links-fixture-01/` is an example dry run on fixture data.

## Tests

```
python -m pytest scripts -q                 # includes scripts/test_purchase_links.py
python scripts/fetch_metadata.py --self-test
```
