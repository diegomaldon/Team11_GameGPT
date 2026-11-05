#!/usr/bin/env python3
"""Steam store details for the seed catalogue, cached in the repo (TM11-159).

The RAWG-era hosted rows carry critic_score, publishers, cover art and
Steam-style tags that the seed fixture lacks. Steam's public store endpoint
(no key) has all four:

    https://store.steampowered.com/api/appdetails?appids=<id>&cc=us&l=english

Responses are trimmed and kept in `scripts/fixtures/steam_appdetails.json`, so
the ingest reads only that file: it runs offline, and two runs read the same
data, which keeps the load idempotent. Refreshing the cache is a separate step:

    python3 scripts/steam_store.py              # fetch app ids missing from the cache
    python3 scripts/steam_store.py --refresh    # re-fetch every app id

Steam allows about 200 requests per 5 minutes, so calls are paced (default
1.6s) and a 429 backs off and retries. An app Steam doesn't know is cached as
{"success": false} so it isn't asked for again. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import catalogue_source

log = logging.getLogger("steam_store")

CACHE_PATH = Path(__file__).resolve().parent / "fixtures" / "steam_appdetails.json"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=english"
USER_AGENT = "GameGPT-catalogue/1.0 (CIS453 Team 11)"
PACE_SECONDS = 1.6
RETRIES = 4


def trim(appid: int, payload: dict) -> dict:
    """Keep only what the catalogue uses from one appdetails response."""
    entry = (payload or {}).get(str(appid)) or {}
    if not entry.get("success") or not isinstance(entry.get("data"), dict):
        return {"success": False}
    d = entry["data"]
    meta = d.get("metacritic") or {}
    score = meta.get("score")
    categories: list[str] = []
    for c in d.get("categories") or []:
        name = (c.get("description") or "").strip()
        if name and name not in categories:
            categories.append(name)
    return {
        "success": True,
        "name": d.get("name"),
        "developers": [x for x in d.get("developers") or [] if isinstance(x, str) and x.strip()],
        "publishers": [x for x in d.get("publishers") or [] if isinstance(x, str) and x.strip()],
        "metacritic": score if isinstance(score, int) and 0 <= score <= 100 else None,
        "header_image": d.get("header_image") or None,
        "categories": categories,
    }


def fetch_appdetails(appid: int, opener: Callable = urllib.request.urlopen,
                     sleep: Callable = time.sleep) -> dict:
    req = urllib.request.Request(APPDETAILS_URL.format(appid=appid), headers={"User-Agent": USER_AGENT})
    for attempt in range(1, RETRIES + 1):
        try:
            with opener(req, timeout=20) as resp:
                return trim(appid, json.load(resp))
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == RETRIES:
                raise
            wait = 30 * attempt if exc.code == 429 else 5 * attempt
            log.warning("appdetails %s: HTTP %s, retry %d in %ss", appid, exc.code, attempt, wait)
            sleep(wait)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == RETRIES:
                raise
            log.warning("appdetails %s: %s, retry %d", appid, exc, attempt)
            sleep(5 * attempt)
    raise RuntimeError("unreachable")


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save_cache(cache: dict[str, dict], path: Path = CACHE_PATH) -> None:
    ordered = {k: cache[k] for k in sorted(cache, key=int)}
    Path(path).write_text(json.dumps(ordered, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def update_cache(appids: list[int], cache: dict[str, dict], refresh: bool = False,
                 fetch: Callable[[int], dict] = fetch_appdetails, sleep: Callable = time.sleep,
                 pace: float = PACE_SECONDS, save: Callable[[dict], None] | None = None) -> dict[str, int]:
    """Fetch the app ids the cache lacks (or all, with refresh). Saves as it goes."""
    todo = [a for a in appids if refresh or str(a) not in cache]
    counts = {"fetched": 0, "unknown": 0, "failed": 0, "cached": len(appids) - len(todo)}
    for i, appid in enumerate(todo):
        if i:
            sleep(pace)
        try:
            cache[str(appid)] = entry = fetch(appid)
        except Exception as exc:  # noqa: BLE001 - logged, counted, rerun picks it up
            counts["failed"] += 1
            log.error("appdetails %s failed: %s", appid, exc)
            continue
        counts["fetched"] += 1
        counts["unknown"] += not entry["success"]
        if save and (counts["fetched"] % 20 == 0):
            save(cache)
    if save:
        save(cache)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-fetch app ids already in the cache")
    ap.add_argument("--pace", type=float, default=PACE_SECONDS)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    appids = sorted({e["steam_appid"] for e in catalogue_source.load_fixture() if e.get("steam_appid")})
    cache = load_cache()
    counts = update_cache(appids, cache, a.refresh, pace=a.pace, save=save_cache)
    print(f"steam_store: {len(appids)} app ids; {counts['cached']} already cached, "
          f"{counts['fetched']} fetched ({counts['unknown']} unknown to Steam), {counts['failed']} failed. "
          f"Cache: {CACHE_PATH}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
