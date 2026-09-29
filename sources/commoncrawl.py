"""
Source C: Common Crawl discovery.

Two CDX queries (no DuckDB / Athena required):

  Q1 — *.myshopify.com subdomains via prefix fan-out  → near-certain Shopify,
       India filtering deferred to verifier.
  Q2 — .in domains with /products/, /collections/, /cdn/shop/ URL paths
       → e-commerce-shaped .in candidates, NOT confirmed Shopify.

Results are cached in data/cc_candidates.json to avoid re-fetching.
The spike's cached file (spike/data/cc_candidates.json) is used as a
fast-path bootstrap so we don't hammer CC CDX in normal runs.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from utils import normalize_domain

_DATA_DIR = Path("data")
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CACHE_FILE = _DATA_DIR / "cc_candidates.json"

# Spike's pre-built cache — use as fast-path bootstrap
_SPIKE_CACHE = Path("spike/data/cc_candidates.json")

# Prefer recent crawls, fall back down the list on 5xx / empty
_CC_CRAWLS = [
    "CC-MAIN-2026-39",
    "CC-MAIN-2026-34",
    "CC-MAIN-2026-30",
    "CC-MAIN-2024-51",
]

_MYSHOPIFY_HOST_RE = re.compile(
    r"^https?://([a-z0-9][a-z0-9\-]*\.myshopify\.com)(?:/|$)",
    re.IGNORECASE,
)

_CDX_HEADERS = {"User-Agent": "RivyouBot/0.2 (academic research; contact: rivyou.research@example.com)"}


# ── CDX helpers ───────────────────────────────────────────────────────────────

def _cdx_get(client: httpx.Client, crawl: str, params: dict, retries: int = 3) -> str | None:
    url = f"https://index.commoncrawl.org/{crawl}-index"
    for attempt in range(retries):
        try:
            resp = client.get(url, params=params, timeout=90.0)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (429, 503, 504):
                wait = 2 ** attempt * 2
                print(f"[cc-cdx] HTTP {resp.status_code} on {crawl}; retry in {wait}s …")
                time.sleep(wait)
                continue
            print(f"[cc-cdx] HTTP {resp.status_code}: {resp.text[:120]}")
            return None
        except Exception as e:
            wait = 2 ** attempt
            print(f"[cc-cdx] error: {e}; retry in {wait}s …")
            time.sleep(wait)
    return None


def _pick_crawl(client: httpx.Client) -> str:
    for crawl in _CC_CRAWLS:
        text = _cdx_get(
            client, crawl,
            {"url": "example.com", "output": "json", "fl": "url", "limit": 1},
            retries=1,
        )
        if text is not None:
            print(f"[cc-cdx] Using crawl {crawl}")
            return crawl
    print(f"[cc-cdx] No crawl responded; defaulting to {_CC_CRAWLS[0]}")
    return _CC_CRAWLS[0]


# ── Q1: *.myshopify.com subdomains ───────────────────────────────────────────

def _get_myshopify_cdx(
    client: httpx.Client,
    crawl: str,
    max_hosts: int = 50_000,
) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    prefixes = [chr(c) for c in range(ord("a"), ord("z") + 1)] + [str(d) for d in range(10)]

    print(f"[cc-q1] Collecting *.myshopify.com hosts (crawl={crawl}, max={max_hosts})")
    for prefix in prefixes:
        if len(seen) >= max_hosts:
            break
        for page in range(3):
            if len(seen) >= max_hosts:
                break
            text = _cdx_get(
                client, crawl,
                {
                    "url": f"{prefix}*.myshopify.com/*",
                    "output": "json",
                    "fl": "url",
                    "limit": 2000,
                    "page": page,
                    "filter": "status:200",
                },
                retries=2,
            )
            if not text:
                break
            page_new = 0
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    raw_url = row.get("url") or row.get("original") or ""
                except json.JSONDecodeError:
                    continue
                m = _MYSHOPIFY_HOST_RE.match(raw_url)
                host = m.group(1).lower() if m else urlparse(raw_url).netloc.lower()
                if not host.endswith(".myshopify.com"):
                    continue
                slug = host.split(".myshopify.com")[0]
                if slug in {"www", "admin", "accounts", "cdn", "app"} or host in seen:
                    continue
                seen.add(host)
                page_new += 1
                results.append({
                    "domain": host,
                    "source": "commoncrawl",
                    "raw": host,
                    "cc_query": "myshopify_subdomains",
                    "slug": slug,
                })
                if len(seen) >= max_hosts:
                    break
            print(f"[cc-q1] {prefix}* page {page}: +{page_new} (total {len(seen)})")
            if page_new == 0:
                break
            time.sleep(0.3)

    print(f"[cc-q1] {len(results)} unique myshopify hosts")
    return results


# ── Q2: .in e-commerce path candidates ───────────────────────────────────────

def _get_in_ecom_cdx(
    client: httpx.Client,
    crawl: str,
    max_hosts: int = 20_000,
) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    prefixes = [chr(c) for c in range(ord("a"), ord("z") + 1)] + [str(d) for d in range(10)]
    path_suffixes = ("products", "collections", "cdn/shop")

    print(f"[cc-q2] Collecting .in e-com path candidates (crawl={crawl})")
    for prefix in prefixes:
        if len(seen) >= max_hosts:
            break
        for path in path_suffixes:
            if len(seen) >= max_hosts:
                break
            text = _cdx_get(
                client, crawl,
                {
                    "url": f"{prefix}*.in/{path}/*",
                    "output": "json",
                    "fl": "url",
                    "collapse": "host",
                    "limit": 500,
                    "filter": "status:200",
                },
                retries=2,
            )
            if not text:
                continue
            before = len(seen)
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    raw_url = row.get("url") or ""
                except json.JSONDecodeError:
                    continue
                host = urlparse(raw_url).netloc.lower().lstrip("www.")
                if not host.endswith(".in"):
                    continue
                domain = normalize_domain(host) or host
                if not domain or domain in seen:
                    continue
                seen.add(domain)
                results.append({
                    "domain": domain,
                    "source": "commoncrawl",
                    "raw": domain,
                    "cc_query": "in_ecom_paths",
                })
                if len(seen) >= max_hosts:
                    break
            gained = len(seen) - before
            if gained:
                print(f"[cc-q2] {prefix}*.in/{path}/*: +{gained} (total {len(seen)})")
            time.sleep(0.25)

    print(f"[cc-q2] {len(results)} unique .in e-commerce candidates")
    return results


# ── Public entry point ────────────────────────────────────────────────────────

def get_candidates(force_refresh: bool = False) -> list[dict]:
    """
    Return CC candidates, using the following priority:
      1. Production cache (data/cc_candidates.json) — skip live fetch
      2. Spike bootstrap cache (spike/data/cc_candidates.json) — copy over
      3. Live CDX queries (slow; may take several minutes)

    Set force_refresh=True to bypass cached files and re-run live queries.
    """
    if not force_refresh:
        for cache in (_CACHE_FILE, _SPIKE_CACHE):
            if cache.exists():
                try:
                    with open(cache, encoding="utf-8") as f:
                        data = json.load(f)
                    if data:
                        print(f"[cc] Loaded {len(data)} candidates from {cache}")
                        # If we loaded from spike cache, promote to production cache
                        if cache == _SPIKE_CACHE and not _CACHE_FILE.exists():
                            _CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                            print(f"[cc] Promoted spike cache → {_CACHE_FILE}")
                        return data
                except Exception as e:
                    print(f"[cc] Failed to load {cache}: {e}")

    with httpx.Client(follow_redirects=True, headers=_CDX_HEADERS) as client:
        crawl = _pick_crawl(client)
        q1 = _get_myshopify_cdx(client, crawl)
        q2 = _get_in_ecom_cdx(client, crawl)

    seen: set[str] = set()
    combined: list[dict] = []
    for entry in q1 + q2:
        d = entry["domain"]
        if d not in seen:
            seen.add(d)
            combined.append(entry)

    print(f"[cc] {len(combined)} unique CC candidates total")
    _CACHE_FILE.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"[cc] Saved to {_CACHE_FILE}")
    return combined


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true", help="Force live CDX queries")
    args = p.parse_args()
    candidates = get_candidates(force_refresh=args.refresh)
    print(f"Total candidates: {len(candidates)}")
