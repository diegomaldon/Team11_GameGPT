#!/usr/bin/env python3
"""Purchase link enrichment for `games.purchase_links` (TM11-37, REQ012). Stdlib only.

  AC-01  purchase_links populated where the source provides them
  AC-02  missing links stored as absent (no key), never fabricated or guessed
  AC-03  link format validated: https, known storefront host, sane path
  AC-04  coverage reported (see link_coverage / ingestion_report.coverage)

`purchase_links` is jsonb keyed by platform_type, e.g.
    {"STEAM": "https://store.steampowered.com/app/271590"}
A key exists only when the source handed us a URL that passed check_link().

Sources:
  RAWG detail  /games/{id}         stores[] = {store: {id, slug}, url}   (url is often "")
  RAWG stores  /games/{id}/stores  results[] = {store_id, url}           (where the URLs live)
  IGDB         websites[]          {category, url}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlsplit

# Must match the platform_type enum (supabase/migrations/..._create_enums.sql).
PLATFORMS = ("STEAM", "XBOX", "EPIC")

# RAWG store slug / store id -> platform_type. Anything else (GOG, PlayStation,
# Nintendo, itch, mobile stores) has no enum value, so it is ignored.
RAWG_STORE_SLUGS = {"steam": "STEAM", "xbox-store": "XBOX", "xbox360": "XBOX", "epic-games": "EPIC"}
RAWG_STORE_IDS = {1: "STEAM", 2: "XBOX", 7: "XBOX", 11: "EPIC"}

# IGDB website category -> platform_type. 13 = Steam, 16 = Epic Games Store.
# IGDB has no Xbox storefront category.
IGDB_WEBSITE_CATEGORIES = {13: "STEAM", 16: "EPIC"}

# Hosts a link for each storefront may point at. A Steam key holding an Epic
# URL (or a wiki page) is a source data error and is rejected, not stored.
ALLOWED_HOSTS = {
    "STEAM": {"store.steampowered.com"},
    "XBOX": {"www.xbox.com", "xbox.com", "www.microsoft.com", "microsoft.com"},
    "EPIC": {"store.epicgames.com", "www.epicgames.com", "epicgames.com"},
}
STEAM_APP_PATH = re.compile(r"^/app/\d+(/|$)")
MAX_URL_LENGTH = 2048


@dataclass
class LinkResult:
    links: dict[str, str] = field(default_factory=dict)
    # (platform, url, reason) for every candidate that was not stored
    rejected: list[tuple[str, str, str]] = field(default_factory=list)


def normalise_url(url: str) -> str:
    """Trim and upgrade http to https. All three storefronts serve https."""
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    return url


def check_link(platform: str, url: object) -> str | None:
    """Return why `url` is not a valid purchase link for `platform`, or None if it is."""
    if platform not in PLATFORMS:
        return f"unknown platform {platform!r}"
    if not isinstance(url, str) or not url.strip():
        return "empty url"
    if len(url) > MAX_URL_LENGTH:
        return "url too long"
    if any(c.isspace() for c in url.strip()):
        return "url contains whitespace"
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "unparseable url"
    if parts.scheme != "https":
        return f"scheme {parts.scheme or 'missing'!r} is not https"
    if parts.username or parts.password or parts.port:
        return "url has credentials or a port"
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS[platform]:
        return f"host {host or 'missing'!r} is not allowed for {platform}"
    if platform == "STEAM" and not STEAM_APP_PATH.match(parts.path):
        return "steam url is not a /app/<id> page"
    return None


def collect(candidates: Iterable[tuple[str | None, object]]) -> LinkResult:
    """Keep the first valid URL per platform. Unmapped stores are skipped silently."""
    res = LinkResult()
    for platform, url in candidates:
        if platform is None or platform in res.links:
            continue
        if not isinstance(url, str) or not url.strip():
            continue  # source listed the store without a URL: absent, not an error
        url = normalise_url(url)
        reason = check_link(platform, url)
        if reason:
            res.rejected.append((platform, url, reason))
        else:
            res.links[platform] = url
    return res


def from_rawg(detail_stores: Iterable[dict] | None = None,
              stores_results: Iterable[dict] | None = None) -> LinkResult:
    """Links from RAWG. `/stores` results win over detail entries, which are often blank."""
    cands: list[tuple[str | None, object]] = []
    for e in stores_results or []:
        cands.append((RAWG_STORE_IDS.get(e.get("store_id")), e.get("url")))
    for e in detail_stores or []:
        store = e.get("store") or {}
        platform = RAWG_STORE_SLUGS.get(store.get("slug")) or RAWG_STORE_IDS.get(store.get("id"))
        cands.append((platform, e.get("url")))
    return collect(cands)


def from_igdb(websites: Iterable[dict] | None) -> LinkResult:
    return collect((IGDB_WEBSITE_CATEGORIES.get(w.get("category")), w.get("url"))
                   for w in websites or [])


def clean(links: object) -> LinkResult:
    """Re-validate an existing purchase_links object (e.g. rows loaded from a JSON file)."""
    if not isinstance(links, dict):
        return LinkResult()
    res = LinkResult()
    for platform, url in links.items():
        if not isinstance(url, str) or not url.strip():
            res.rejected.append((str(platform), str(url), "empty url"))
            continue
        url = normalise_url(url)
        reason = check_link(platform, url)
        if reason:
            res.rejected.append((str(platform), url, reason))
        else:
            res.links[platform] = url
    return res


def link_coverage(rows: list[dict]) -> dict[str, dict]:
    """Share of rows with at least one link, and per storefront."""
    n = len(rows)

    def pct(v: int) -> dict:
        return {"present": v, "total": n, "pct": round(100 * v / n, 1) if n else 0.0}

    def links(r: dict) -> dict:
        pl = r.get("purchase_links")
        return pl if isinstance(pl, dict) else {}

    out = {"any": pct(sum(bool(links(r)) for r in rows))}
    for p in PLATFORMS:
        out[p] = pct(sum(p in links(r) for r in rows))
    return out
