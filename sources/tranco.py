"""
Source A: Tranco top-sites list, filtered to .in / .co.in TLDs.

Downloads the latest Tranco top-1M CSV and yields Indian-TLD candidates.

Bias caveat: Tranco ranks by link-based popularity, so it skews toward news,
gov, and banking sites — low Shopify hit rate is expected (~10%).
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import httpx

from utils import normalize_domain, get_suffix

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
_CACHE_FILE = Path("data/tranco_top1m.csv")

_INDIAN_SUFFIXES: frozenset[str] = frozenset({"in", "co.in"})


def _is_indian_tld(domain: str) -> bool:
    suffix = get_suffix(domain)
    return suffix in _INDIAN_SUFFIXES


def _download_tranco() -> list[str]:
    """Download (or load from cache) the Tranco list. Returns raw domain strings."""
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _CACHE_FILE.exists():
        print(f"[tranco] Using cached list: {_CACHE_FILE}")
        with open(_CACHE_FILE, newline="", encoding="utf-8") as f:
            return [row[1] for row in csv.reader(f) if len(row) >= 2]

    print("[tranco] Downloading Tranco top-1M list …")
    resp = httpx.get(TRANCO_URL, follow_redirects=True, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_bytes = zf.read(zf.namelist()[0])

    _CACHE_FILE.write_bytes(csv_bytes)
    lines = csv_bytes.decode("utf-8").strip().splitlines()
    return [row.split(",")[1] for row in lines if "," in row]


def get_candidates() -> list[dict]:
    """
    Return Indian-TLD domains from Tranco as candidate dicts:
        {"domain": <canonical>, "source": "tranco", "raw": <original>}

    Deduped by canonical registrable domain.
    """
    seen: set[str] = set()
    results: list[dict] = []

    for raw in _download_tranco():
        if not _is_indian_tld(raw):
            continue
        canonical = normalize_domain(raw)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        results.append({"domain": canonical, "source": "tranco", "raw": raw})

    print(f"[tranco] {len(results)} unique .in/.co.in candidates")
    return results


if __name__ == "__main__":
    candidates = get_candidates()
    print(f"Total: {len(candidates)}")
    for c in candidates[:20]:
        print(f"  {c['domain']}")
