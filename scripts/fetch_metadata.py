#!/usr/bin/env python3
"""
GameGPT :: metadata source prototype
Ticket: Prototype metadata pull from IGDB or RAWG

Pulls a sample of titles from RAWG and/or IGDB, normalizes them into the shape
of the `games` table, and writes:

    out/raw/<source>_<id>.json     raw API responses, cached
    out/prototype_games.json       normalized records
    out/prototype_games.csv        same, spreadsheet-friendly
    out/coverage_report.md         per-field fill rate -- the actual finding
    out/prototype_games_upsert.sql paste into the Supabase SQL Editor

Stdlib only. No pip install needed.

Usage
-----
    export RAWG_API_KEY=...
    python3 fetch_metadata.py --source rawg --limit 15

    export IGDB_CLIENT_ID=...
    export IGDB_CLIENT_SECRET=...
    python3 fetch_metadata.py --source igdb --limit 15

    python3 fetch_metadata.py --source both --limit 15

    python3 fetch_metadata.py --self-test     # no network; checks the mapping

Credentials
-----------
RAWG : https://rawg.io/apidocs -> "Get an API key". Single key, query string.
IGDB : https://dev.twitch.tv/console/apps -> register an app -> Client ID +
       Client Secret. The script exchanges them for an app access token itself.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

# -----------------------------------------------------------------------------
# Rate limits. Documented in docs/metadata_source_evaluation.md.
# -----------------------------------------------------------------------------
# IGDB: hard 4 requests/second, max 8 concurrent. 429 on breach.
IGDB_MIN_INTERVAL = 0.30          # ~3.3 rps, deliberately under the ceiling
# RAWG: no documented per-second limit, only a 20k/month quota. Self-throttle
# anyway -- hammering an undocumented endpoint is how undocumented endpoints
# acquire documented limits.
RAWG_MIN_INTERVAL = 0.25

USER_AGENT = "GameGPT-CIS453-prototype/0.1 (coursework)"

# Storefronts we care about, per REQ008. Must match the platform_type enum.
STOREFRONTS = {"STEAM", "XBOX", "EPIC"}

# RAWG store slugs -> our platform_type enum
RAWG_STORE_MAP = {
    "steam": "STEAM",
    "xbox-store": "XBOX",
    "xbox360": "XBOX",
    "epic-games": "EPIC",
}

# IGDB website category ids -> our platform_type enum
# 13 = Steam, 16 = Epic Games Store. IGDB has no Xbox storefront category,
# which is a real gap for REQ008 -- see the evaluation doc.
IGDB_WEBSITE_MAP = {
    13: "STEAM",
    16: "EPIC",
}


# =============================================================================
# HTTP
# =============================================================================
class Throttle:
    """Minimum-interval pacer. Cheaper than a token bucket and enough here."""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()


def http(url, data=None, headers=None, method=None, retries=4):
    """One request with backoff on 429 and 5xx. Returns parsed JSON."""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", USER_AGENT)
    if isinstance(data, str):
        data = data.encode()

    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                backoff = 2 ** attempt
                print(f"  HTTP {e.code}, retrying in {backoff}s", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise SystemExit(f"HTTP {e.code} on {url}\n{body}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"Network error on {url}: {e.reason}")
    raise SystemExit(f"Gave up on {url}")


# =============================================================================
# Normalized record
# =============================================================================
def blank_record():
    """Every key here maps to a column in public.games. See docs/field_mapping.md."""
    return {
        "source": None,
        "source_id": None,
        "title": None,
        "description": None,
        "genres": [],
        "tags": [],
        "platforms_raw": [],        # NOT a games column -- kept for the report
        "available_platforms": [],  # storefronts only, per REQ008
        "purchase_links": {},
        "critic_score": None,
        "review_score": None,
        "release_date": None,
        "developers": [],
        "publishers": [],
        "header_image_url": None,
    }


def clamp_score(value):
    """games.critic_score / review_score are smallint CHECK 0..100."""
    if value is None:
        return None
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, v))


def dedupe(seq):
    seen, out = set(), []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# =============================================================================
# RAWG
# =============================================================================
RAWG_BASE = "https://api.rawg.io/api"


def rawg_list(key, limit, throttle):
    """One call returns up to 40 games with genres, tags, platforms, scores."""
    qs = urllib.parse.urlencode({
        "key": key,
        "page_size": min(limit, 40),
        "ordering": "-added",       # most-tracked titles; dense metadata
        "metacritic": "1,100",      # bias toward rows that actually have a score
    })
    throttle.wait()
    return http(f"{RAWG_BASE}/games?{qs}").get("results", [])


def rawg_detail(key, game_id, throttle, raw_dir):
    """Detail call. This is the only place description_raw and stores appear."""
    cache = raw_dir / f"rawg_{game_id}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    qs = urllib.parse.urlencode({"key": key})
    throttle.wait()
    payload = http(f"{RAWG_BASE}/games/{game_id}?{qs}")
    cache.write_text(json.dumps(payload, indent=2))
    return payload


def rawg_normalize(summary, detail):
    r = blank_record()
    r["source"] = "rawg"
    r["source_id"] = detail.get("id") or summary.get("id")
    r["title"] = detail.get("name") or summary.get("name")

    # description_raw is plain text; `description` is HTML. Use the former.
    r["description"] = (detail.get("description_raw") or "").strip() or None

    r["genres"] = dedupe(g["name"] for g in detail.get("genres") or [])
    r["tags"] = dedupe(
        t["name"] for t in (detail.get("tags") or [])
        if t.get("language") in (None, "eng")
    )[:25]

    # RAWG "platforms" are hardware/OS, not storefronts. Recorded for the
    # report but NOT mapped to available_platforms.
    r["platforms_raw"] = dedupe(
        p["platform"]["name"] for p in detail.get("platforms") or []
    )

    # RAWG "stores" ARE storefronts, and carry a URL. This is what REQ008 and
    # REQ012 actually need.
    storefronts, links = [], {}
    for entry in detail.get("stores") or []:
        slug = (entry.get("store") or {}).get("slug")
        mapped = RAWG_STORE_MAP.get(slug)
        if not mapped:
            continue
        storefronts.append(mapped)
        url = entry.get("url") or ""
        if url and mapped not in links:
            links[mapped] = url
    r["available_platforms"] = dedupe(storefronts)
    r["purchase_links"] = links

    r["critic_score"] = clamp_score(detail.get("metacritic"))
    # RAWG's own user rating is 0-5. Rescale to 0-100 to match critic_score.
    rating = detail.get("rating")
    r["review_score"] = clamp_score(rating * 20) if rating else None

    r["release_date"] = detail.get("released") or None
    r["developers"] = dedupe(d["name"] for d in detail.get("developers") or [])
    r["publishers"] = dedupe(p["name"] for p in detail.get("publishers") or [])
    r["header_image_url"] = detail.get("background_image") or None
    return r


def pull_rawg(limit, raw_dir):
    key = os.environ.get("RAWG_API_KEY")
    if not key:
        raise SystemExit("RAWG_API_KEY is not set. Get one at https://rawg.io/apidocs")
    throttle = Throttle(RAWG_MIN_INTERVAL)
    print(f"RAWG: listing {limit} titles")
    summaries = rawg_list(key, limit, throttle)[:limit]
    out = []
    for i, s in enumerate(summaries, 1):
        print(f"  [{i}/{len(summaries)}] {s.get('name')}")
        detail = rawg_detail(key, s["id"], throttle, raw_dir)
        out.append(rawg_normalize(s, detail))
    print(f"RAWG: {len(out)} records, {1 + len(out)} requests")
    return out


# =============================================================================
# IGDB
# =============================================================================
IGDB_BASE = "https://api.igdb.com/v4"
IGDB_FIELDS = (
    "fields name,summary,storyline,"
    "genres.name,themes.name,keywords.name,"
    "platforms.name,"
    "aggregated_rating,aggregated_rating_count,rating,rating_count,"
    "first_release_date,"
    "involved_companies.company.name,involved_companies.developer,"
    "involved_companies.publisher,"
    "cover.url,websites.url,websites.category;"
)


def igdb_token():
    cid = os.environ.get("IGDB_CLIENT_ID")
    secret = os.environ.get("IGDB_CLIENT_SECRET")
    if not (cid and secret):
        raise SystemExit(
            "IGDB_CLIENT_ID and IGDB_CLIENT_SECRET must be set. Register an app "
            "at https://dev.twitch.tv/console/apps"
        )
    qs = urllib.parse.urlencode({
        "client_id": cid,
        "client_secret": secret,
        "grant_type": "client_credentials",
    })
    payload = http(f"https://id.twitch.tv/oauth2/token?{qs}", data=b"", method="POST")
    return cid, payload["access_token"]


def igdb_games(limit, raw_dir):
    """One POST returns every field the AC asks for. No per-title detail call."""
    cid, token = igdb_token()
    query = (
        IGDB_FIELDS
        + " where version_parent = null & summary != null"
        + " & aggregated_rating != null;"
        + " sort aggregated_rating desc;"
        + f" limit {limit};"
    )
    throttle = Throttle(IGDB_MIN_INTERVAL)
    throttle.wait()
    print(f"IGDB: querying {limit} titles in one request")
    payload = http(
        f"{IGDB_BASE}/games",
        data=query,
        headers={"Client-ID": cid, "Authorization": f"Bearer {token}"},
        method="POST",
    )
    for game in payload:
        (raw_dir / f"igdb_{game['id']}.json").write_text(json.dumps(game, indent=2))
    return payload


def igdb_normalize(g):
    r = blank_record()
    r["source"] = "igdb"
    r["source_id"] = g.get("id")
    r["title"] = g.get("name")
    r["description"] = (g.get("summary") or "").strip() or None

    r["genres"] = dedupe(x["name"] for x in g.get("genres") or [])
    # IGDB splits what RAWG calls "tags" across themes (curated) and keywords
    # (user-supplied, noisy). Merge, themes first.
    r["tags"] = dedupe(
        [x["name"] for x in g.get("themes") or []]
        + [x["name"] for x in g.get("keywords") or []]
    )[:25]

    r["platforms_raw"] = dedupe(x["name"] for x in g.get("platforms") or [])

    storefronts, links = [], {}
    for site in g.get("websites") or []:
        mapped = IGDB_WEBSITE_MAP.get(site.get("category"))
        if not mapped:
            continue
        storefronts.append(mapped)
        if site.get("url") and mapped not in links:
            links[mapped] = site["url"]
    r["available_platforms"] = dedupe(storefronts)
    r["purchase_links"] = links

    r["critic_score"] = clamp_score(g.get("aggregated_rating"))
    r["review_score"] = clamp_score(g.get("rating"))

    ts = g.get("first_release_date")
    if ts:
        r["release_date"] = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()

    for ic in g.get("involved_companies") or []:
        name = (ic.get("company") or {}).get("name")
        if not name:
            continue
        if ic.get("developer"):
            r["developers"].append(name)
        if ic.get("publisher"):
            r["publishers"].append(name)
    r["developers"] = dedupe(r["developers"])
    r["publishers"] = dedupe(r["publishers"])

    cover = (g.get("cover") or {}).get("url")
    if cover:
        # IGDB returns protocol-relative URLs with a thumbnail size token.
        r["header_image_url"] = "https:" + cover.replace("t_thumb", "t_cover_big")
    return r


def pull_igdb(limit, raw_dir):
    games = igdb_games(limit, raw_dir)
    out = [igdb_normalize(g) for g in games]
    print(f"IGDB: {len(out)} records, 2 requests (1 token + 1 query)")
    return out


# =============================================================================
# Outputs
# =============================================================================
REPORT_FIELDS = [
    "title", "description", "genres", "tags",
    "platforms_raw", "available_platforms", "purchase_links",
    "critic_score", "review_score",
    "release_date", "developers", "publishers", "header_image_url",
]

# Which AC field each column satisfies, so the report maps back to the ticket.
AC_FIELD = {
    "title": "title",
    "description": "description",
    "genres": "genres",
    "tags": "tags",
    "available_platforms": "platforms",
    "critic_score": "scores",
    "review_score": "scores",
}


def filled(value):
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


def coverage(records):
    by_source = {}
    for r in records:
        by_source.setdefault(r["source"], []).append(r)

    lines = [
        "# Metadata source coverage report",
        "",
        f"Generated {date.today().isoformat()} by `scripts/fetch_metadata.py`.",
        "",
        "Fill rate is the share of sampled titles where the field is present and",
        "non-empty. This is the finding the ticket is actually after: which fields",
        "a source populates *reliably*, not whether the field exists in the schema.",
        "",
    ]
    for source, rows in sorted(by_source.items()):
        lines += [
            f"## {source.upper()} -- n={len(rows)}",
            "",
            "| games column | AC field | filled | fill rate |",
            "|---|---|---|---|",
        ]
        for f in REPORT_FIELDS:
            n = sum(1 for r in rows if filled(r[f]))
            pct = 100.0 * n / len(rows) if rows else 0.0
            ac = AC_FIELD.get(f, "--")
            flag = ""
            if ac != "--" and pct < 100.0:
                flag = "  **AC GAP**" if pct < 80.0 else "  *partial*"
            lines.append(f"| `{f}` | {ac} | {n}/{len(rows)} | {pct:.0f}%{flag} |")
        lines.append("")

        avg_tags = sum(len(r["tags"]) for r in rows) / len(rows) if rows else 0
        avg_genres = sum(len(r["genres"]) for r in rows) / len(rows) if rows else 0
        avg_desc = (
            sum(len(r["description"] or "") for r in rows) / len(rows) if rows else 0
        )
        lines += [
            f"- mean tags per title: **{avg_tags:.1f}**",
            f"- mean genres per title: **{avg_genres:.1f}**",
            f"- mean description length: **{avg_desc:.0f}** chars",
            "",
        ]
    return "\n".join(lines)


def sql_literal(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def text_array(items):
    if not items:
        return "'{}'"
    return "array[" + ", ".join(sql_literal(i) for i in items) + "]"


def enum_array(items):
    if not items:
        return "'{}'::public.platform_type[]"
    return (
        "array[" + ", ".join(sql_literal(i) for i in items)
        + "]::public.platform_type[]"
    )


def upsert_sql(records):
    """Emit INSERT ... ON CONFLICT against public.games, keyed on the source id."""
    out = [
        "-- =============================================================================",
        "-- GameGPT :: prototype metadata import",
        f"-- Generated {date.today().isoformat()} by scripts/fetch_metadata.py",
        "-- =============================================================================",
        "-- Paste into the Supabase SQL Editor. Safe to re-run: conflicts on the",
        "-- source id column update in place rather than inserting a duplicate.",
        "--",
        "-- `embedding` is left null. Embeddings are a separate job.",
        "-- =============================================================================",
        "",
    ]
    for r in records:
        id_col = {"rawg": "rawg_id", "igdb": "igdb_id"}[r["source"]]
        out += [
            f"-- {r['source']}:{r['source_id']}  {r['title']}",
            "insert into public.games (",
            f"  {id_col}, title, description, genres, tags, available_platforms,",
            "  purchase_links, critic_score, review_score, release_date,",
            "  developers, publishers, header_image_url",
            ") values (",
            f"  {sql_literal(r['source_id'])},",
            f"  {sql_literal(r['title'])},",
            f"  {sql_literal(r['description'])},",
            f"  {text_array(r['genres'])},",
            f"  {text_array(r['tags'])},",
            f"  {enum_array(r['available_platforms'])},",
            f"  {sql_literal(json.dumps(r['purchase_links']))}::jsonb,",
            f"  {sql_literal(r['critic_score'])},",
            f"  {sql_literal(r['review_score'])},",
            f"  {sql_literal(r['release_date'])}::date,",
            f"  {text_array(r['developers'])},",
            f"  {text_array(r['publishers'])},",
            f"  {sql_literal(r['header_image_url'])}",
            ")",
            f"on conflict ({id_col}) do update set",
            "  title               = excluded.title,",
            "  description         = excluded.description,",
            "  genres              = excluded.genres,",
            "  tags                = excluded.tags,",
            "  available_platforms = excluded.available_platforms,",
            "  purchase_links      = excluded.purchase_links,",
            "  critic_score        = excluded.critic_score,",
            "  review_score        = excluded.review_score,",
            "  release_date        = excluded.release_date,",
            "  developers          = excluded.developers,",
            "  publishers          = excluded.publishers,",
            "  header_image_url    = excluded.header_image_url;",
            "",
        ]
    return "\n".join(out)


def write_csv(records, path):
    cols = ["source", "source_id"] + REPORT_FIELDS
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in records:
            row = []
            for c in cols:
                v = r[c]
                if isinstance(v, list):
                    v = "; ".join(str(x) for x in v)
                elif isinstance(v, dict):
                    v = json.dumps(v)
                row.append(v)
            w.writerow(row)


# =============================================================================
# Self-test (no network)
# =============================================================================
FIXTURE_RAWG = {
    "id": 3498,
    "name": "Grand Theft Auto V",
    "description_raw": "Rockstar Games went bigger, since their previous...",
    "metacritic": 92,
    "rating": 4.47,
    "released": "2013-09-17",
    "background_image": "https://media.rawg.io/media/games/456/456dea5e.jpg",
    "genres": [{"name": "Action"}, {"name": "Adventure"}],
    "tags": [
        {"name": "Singleplayer", "language": "eng"},
        {"name": "Atmospheric", "language": "eng"},
        {"name": "Einzelspieler", "language": "deu"},
    ],
    "platforms": [
        {"platform": {"name": "PC"}},
        {"platform": {"name": "Xbox Series S/X"}},
    ],
    "stores": [
        {"store": {"slug": "steam"}, "url": "https://store.steampowered.com/app/271590"},
        {"store": {"slug": "xbox-store"}, "url": "https://microsoft.com/p/gtav"},
        {"store": {"slug": "gog"}, "url": "https://gog.com/irrelevant"},
    ],
    "developers": [{"name": "Rockstar North"}],
    "publishers": [{"name": "Rockstar Games"}],
}

FIXTURE_IGDB = {
    "id": 1020,
    "name": "Grand Theft Auto V",
    "summary": "Grand Theft Auto V is a vast open world game...",
    "aggregated_rating": 93.4,
    "rating": 88.6,
    "first_release_date": 1379376000,
    "genres": [{"name": "Shooter"}, {"name": "Adventure"}],
    "themes": [{"name": "Action"}, {"name": "Comedy"}],
    "keywords": [{"name": "open world"}, {"name": "heist"}],
    "platforms": [{"name": "PC (Microsoft Windows)"}, {"name": "Xbox Series X|S"}],
    "websites": [
        {"category": 13, "url": "https://store.steampowered.com/app/271590"},
        {"category": 3, "url": "https://en.wikipedia.org/wiki/GTAV"},
    ],
    "involved_companies": [
        {"company": {"name": "Rockstar North"}, "developer": True, "publisher": False},
        {"company": {"name": "Rockstar Games"}, "developer": False, "publisher": True},
    ],
    "cover": {"url": "//images.igdb.com/igdb/image/upload/t_thumb/co2lbd.jpg"},
}


def self_test():
    failures = []

    def check(label, actual, expected):
        if actual != expected:
            failures.append(f"{label}: got {actual!r}, expected {expected!r}")

    r = rawg_normalize(FIXTURE_RAWG, FIXTURE_RAWG)
    check("rawg.title", r["title"], "Grand Theft Auto V")
    check("rawg.critic_score", r["critic_score"], 92)
    check("rawg.review_score", r["review_score"], 89)          # 4.47 * 20
    check("rawg.genres", r["genres"], ["Action", "Adventure"])
    check("rawg.tags", r["tags"], ["Singleplayer", "Atmospheric"])  # deu dropped
    check("rawg.storefronts", r["available_platforms"], ["STEAM", "XBOX"])  # gog dropped
    check("rawg.links", sorted(r["purchase_links"]), ["STEAM", "XBOX"])
    check("rawg.platforms_raw", r["platforms_raw"], ["PC", "Xbox Series S/X"])
    check("rawg.developers", r["developers"], ["Rockstar North"])
    check("rawg.release_date", r["release_date"], "2013-09-17")

    g = igdb_normalize(FIXTURE_IGDB)
    check("igdb.critic_score", g["critic_score"], 93)
    check("igdb.review_score", g["review_score"], 89)
    check("igdb.tags", g["tags"], ["Action", "Comedy", "open world", "heist"])
    check("igdb.storefronts", g["available_platforms"], ["STEAM"])  # no XBOX category
    check("igdb.release_date", g["release_date"], "2013-09-17")
    check("igdb.developers", g["developers"], ["Rockstar North"])
    check("igdb.publishers", g["publishers"], ["Rockstar Games"])
    check("igdb.cover", g["header_image_url"],
          "https://images.igdb.com/igdb/image/upload/t_cover_big/co2lbd.jpg")

    # score clamping against the smallint CHECK (0..100) constraints
    check("clamp.over", clamp_score(101.9), 100)
    check("clamp.under", clamp_score(-3), 0)
    check("clamp.none", clamp_score(None), None)

    # SQL generation must escape apostrophes, or one Tom Clancy title breaks it
    sql = upsert_sql([dict(r, title="Sid Meier's Civilization")])
    if "'Sid Meier''s Civilization'" not in sql:
        failures.append("SQL apostrophe escaping failed")
    if "on conflict (rawg_id)" not in sql:
        failures.append("SQL conflict target wrong for rawg")

    if failures:
        print("SELF-TEST FAILED")
        for f in failures:
            print("  -", f)
        return 1
    print("self-test passed: 21 assertions")
    return 0


# =============================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["rawg", "igdb", "both"], default="rawg")
    ap.add_argument("--limit", type=int, default=15,
                    help="titles per source (AC needs 10+; default 15 for headroom)")
    ap.add_argument("--out", default="out", help="output directory")
    ap.add_argument("--self-test", action="store_true",
                    help="verify the field mapping against fixtures, no network")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    records = []
    if args.source in ("rawg", "both"):
        records += pull_rawg(args.limit, raw_dir)
    if args.source in ("igdb", "both"):
        records += pull_igdb(args.limit, raw_dir)

    if not records:
        raise SystemExit("No records pulled.")

    (out / "prototype_games.json").write_text(json.dumps(records, indent=2))
    write_csv(records, out / "prototype_games.csv")
    (out / "coverage_report.md").write_text(coverage(records))
    (out / "prototype_games_upsert.sql").write_text(upsert_sql(records))

    print(f"\n{len(records)} records -> {out}/")
    for name in ("prototype_games.json", "prototype_games.csv",
                 "coverage_report.md", "prototype_games_upsert.sql"):
        print(f"  {name}")
    print(f"  raw/  ({len(list(raw_dir.glob('*.json')))} cached responses)")
    print("\nAttribution is required by both sources. See docs/metadata_source_evaluation.md.")


if __name__ == "__main__":
    main()
