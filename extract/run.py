"""
Extraction orchestrator.

Runs all extractors for a single domain and returns a consolidated fields dict
suitable for storage.save_extracted().

Progressive crawl strategy:
  - The fetcher's SQLite cache means pages already fetched for verification
    are served from disk — no extra network requests for cached pages.
  - Each extractor is responsible for its own page selection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from extract import contacts, socials, category, tagline, logo
from state import resolver

if TYPE_CHECKING:
    from fetcher import Fetcher

log = logging.getLogger(__name__)


async def extract_store(fetcher: "Fetcher", domain: str) -> dict:
    """
    Run all extractors for *domain*.

    Returns a fields dict ready for storage.save_extracted():
        contacts, socials, category, category_method,
        tagline, tagline_method,
        logo_url, logo_local_path, logo_source,
        state, state_method, state_status
    """
    fields: dict = {}

    try:
        fields["contacts"] = await contacts.extract(fetcher, domain)
    except Exception as e:
        log.warning("[%s] contacts error: %s", domain, e)
        fields["contacts"] = []

    try:
        fields["socials"] = await socials.extract(fetcher, domain)
    except Exception as e:
        log.warning("[%s] socials error: %s", domain, e)
        fields["socials"] = {}

    try:
        cat = await category.extract(fetcher, domain)
        if cat:
            fields["category"]        = cat["value"]
            fields["category_method"] = cat["method"]
    except Exception as e:
        log.warning("[%s] category error: %s", domain, e)

    try:
        tag = await tagline.extract(fetcher, domain)
        if tag:
            fields["tagline"]        = tag["value"]
            fields["tagline_method"] = tag["method"]
    except Exception as e:
        log.warning("[%s] tagline error: %s", domain, e)

    try:
        lg = await logo.extract(fetcher, domain)
        if lg:
            fields["logo_url"]        = lg["logo_url"]
            fields["logo_local_path"] = lg["logo_local_path"]
            fields["logo_source"]     = lg["logo_source"]
    except Exception as e:
        log.warning("[%s] logo error: %s", domain, e)

    try:
        state_result = await resolver.resolve(fetcher, domain)
        fields["state"]        = state_result["state"]
        fields["state_method"] = state_result["method"]
        fields["state_status"] = state_result["status"]
    except Exception as e:
        log.warning("[%s] state resolver error: %s", domain, e)

    return fields


def fill_rate_report(records: list[dict]) -> dict:
    """
    Compute per-field fill rates from a list of extracted records.

    Returns:
        {field: {"filled": int, "total": int, "rate": float, "miss_reason": str}}
    """
    if not records:
        return {}

    total = len(records)
    fields_to_check = [
        ("contacts",      lambda r: bool(r.get("contacts"))),
        ("socials",       lambda r: bool(r.get("socials"))),
        ("category",      lambda r: bool(r.get("category") and r["category"] != "Other")),
        ("tagline",       lambda r: bool(r.get("tagline"))),
        ("logo_url",      lambda r: bool(r.get("logo_url"))),
        ("state",         lambda r: r.get("state_status") == "resolved"),
    ]

    report = {}
    for field, check in fields_to_check:
        filled = sum(1 for r in records if check(r))
        rate   = filled / total if total else 0.0
        miss   = _miss_reason(field, total - filled, records)
        report[field] = {"filled": filled, "total": total,
                         "rate": round(rate, 3), "miss_reason": miss}
    return report


def _miss_reason(field: str, miss_count: int, records: list[dict]) -> str:
    if miss_count == 0:
        return "none"
    reasons = {
        "contacts":  "no mailto/tel anchor; junk-domain filter; page behind JS",
        "socials":   "no social links in homepage/about; share-button-only links",
        "category":  "all products in 'Other' bucket; no product_type/tags set",
        "tagline":   "no og:description/meta; dynamic hero (JS-rendered)",
        "logo_url":  "no JSON-LD org; no logo-hinted img; og:image is product photo",
        "state":     "no GSTIN/PIN/city in pages; foreign address; JS-rendered contact",
    }
    pct = f"{miss_count / len(records) * 100:.0f}% missing"
    return f"{pct} — {reasons.get(field, 'unknown')}"
