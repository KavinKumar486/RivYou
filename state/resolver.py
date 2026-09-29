"""
State resolver.

Determines the Indian state of operation for a verified store.

Resolution order (first strong hit wins):
  1. GSTIN state code  — 2-digit prefix maps directly to state
  2. Full PIN code lookup — India Post 6-digit code prefix map
  3. City / address text — city→state map against contact/about pages
  4. State name in address context — regex against contact/about pages

Two strong signals disagreeing → status="needs_review", state=None.

Returns:
    {
        "state":        str | None,
        "method":       str,
        "status":       "resolved" | "needs_review" | "unresolved",
        "source_url":   str,
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

_HERE = Path(__file__).parent

with open(_HERE / "states.json", encoding="utf-8") as _f:
    _STATE_CODES: dict[str, str] = json.load(_f)   # "27" → "Maharashtra"

with open(_HERE / "city_state_map.json", encoding="utf-8") as _f:
    _CITY_MAP: dict[str, str] = json.load(_f)      # "mumbai" → "Maharashtra"

# PIN code prefix → state (India Post series)
# First 2 digits of 6-digit PIN code
_PIN_PREFIX_MAP: dict[str, str] = {
    "11": "Delhi",
    "12": "Haryana", "13": "Haryana",
    "14": "Punjab",  "15": "Punjab", "16": "Punjab",
    "17": "Himachal Pradesh",
    "18": "Jammu & Kashmir", "19": "Jammu & Kashmir",
    "20": "Uttar Pradesh", "21": "Uttar Pradesh", "22": "Uttar Pradesh",
    "23": "Uttar Pradesh", "24": "Uttar Pradesh", "25": "Uttar Pradesh",
    "26": "Uttar Pradesh", "27": "Uttar Pradesh", "28": "Uttar Pradesh",
    "30": "Rajasthan", "31": "Rajasthan", "32": "Rajasthan",
    "33": "Rajasthan", "34": "Rajasthan",
    "36": "Gujarat",  "37": "Gujarat",  "38": "Gujarat",
    "39": "Gujarat",
    "40": "Maharashtra", "41": "Maharashtra", "42": "Maharashtra",
    "43": "Maharashtra", "44": "Maharashtra",
    "45": "Madhya Pradesh", "46": "Madhya Pradesh", "47": "Madhya Pradesh",
    "48": "Madhya Pradesh", "49": "Chhattisgarh",
    "50": "Telangana", "51": "Telangana", "52": "Andhra Pradesh",
    "53": "Andhra Pradesh",
    "56": "Karnataka", "57": "Karnataka", "58": "Karnataka",
    "59": "Karnataka",
    "60": "Tamil Nadu", "61": "Tamil Nadu", "62": "Tamil Nadu",
    "63": "Tamil Nadu", "64": "Tamil Nadu",
    "67": "Kerala", "68": "Kerala", "69": "Kerala",
    "70": "West Bengal", "71": "West Bengal", "72": "West Bengal",
    "73": "West Bengal", "74": "West Bengal",
    "75": "Odisha", "76": "Odisha", "77": "Odisha",
    "78": "Assam",
    "80": "Bihar", "81": "Bihar", "82": "Bihar",
    "83": "Bihar", "84": "Bihar", "85": "Bihar",
    "82": "Jharkhand", "83": "Jharkhand",
    "90": "Uttar Pradesh", "91": "Uttar Pradesh",
    "92": "Uttar Pradesh", "93": "Uttar Pradesh",
}

# GSTIN pattern (same as in verify/india.py)
_GSTIN_RE = re.compile(r'\b([0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b')
_PIN_RE   = re.compile(
    r'(?:pin\s*(?:code)?|postal\s*code)\s*[:\-]?\s*([1-9]\d{5})\b'
    r'|(?<=[,\s])([1-9]\d{5})\s*(?:,?\s*India\b)',
    re.IGNORECASE,
)
_ADDR_CONTEXT_RE = re.compile(
    r'\b(?:address|office|registered|located|headquarter|regd\.?\s*office)\b',
    re.IGNORECASE,
)

_PAGES = [
    "",
    "/pages/contact", "/pages/contact-us",
    "/pages/about", "/pages/about-us",
    "/policies/terms-of-service",
]


def _state_from_gstin(html: str) -> str | None:
    for m in _GSTIN_RE.finditer(html):
        code = m.group(1)[:2]
        state = _STATE_CODES.get(code)
        if state:
            return state
    return None


def _state_from_pin(html: str) -> str | None:
    for m in _PIN_RE.finditer(html):
        pin = m.group(1) or m.group(2)
        if pin:
            prefix = pin[:2]
            state = _PIN_PREFIX_MAP.get(prefix)
            if state:
                return state
    return None


def _state_from_city(html: str) -> str | None:
    lower = html.lower()
    if not _ADDR_CONTEXT_RE.search(html):
        return None
    for city, state in _CITY_MAP.items():
        if city in lower:
            return state
    return None


def _state_from_name(html: str) -> str | None:
    """Match full state names in address context."""
    if not _ADDR_CONTEXT_RE.search(html):
        return None
    lower = html.lower()
    for state in _STATE_CODES.values():
        if state.lower() in lower:
            return state
    return None


async def resolve(fetcher: "Fetcher", domain: str,
                  existing_evidence: list[dict] | None = None) -> dict:
    """
    Resolve the operating state for *domain*.

    existing_evidence: evidence list already collected by india verifier
    (avoids re-fetching pages that were already retrieved).
    """
    base = f"https://{domain}"

    # Collect page HTML
    page_html: dict[str, str] = {}
    for path in _PAGES:
        url = f"{base}{path}"
        resp = await fetcher.fetch(url)
        if resp and resp.get("status") == 200:
            page_html[url] = resp.get("body", "")

    combined = "\n".join(page_html.values())

    # Resolution attempts in priority order
    hits: list[tuple[str, str, str]] = []  # (state, method, source_url)

    for url, html in page_html.items():
        s = _state_from_gstin(html)
        if s:
            hits.append((s, "gstin_state_code", url))
            break

    for url, html in page_html.items():
        s = _state_from_pin(html)
        if s:
            hits.append((s, "pin_prefix", url))
            break

    for url, html in page_html.items():
        s = _state_from_city(html)
        if s:
            hits.append((s, "city_map", url))
            break

    for url, html in page_html.items():
        s = _state_from_name(html)
        if s:
            hits.append((s, "state_name", url))
            break

    if not hits:
        return {"state": None, "method": "none", "status": "unresolved",
                "source_url": base}

    # Check for contradiction among strong signals
    strong = [h for h in hits if h[1] in ("gstin_state_code", "pin_prefix")]
    if len(strong) >= 2 and len({h[0] for h in strong}) > 1:
        return {"state": None, "method": "contradiction",
                "status": "needs_review", "source_url": hits[0][2]}

    # Best hit = highest priority (first in list)
    state, method, source_url = hits[0]
    return {"state": state, "method": method,
            "status": "resolved", "source_url": source_url}
