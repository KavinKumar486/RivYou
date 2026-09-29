"""
Tagline extractor.

Fallback chain (stops at first hit):
  1. og:description  meta tag
  2. meta description
  3. Hero heading — first <h1> or <h2> on homepage
  4. About paragraph — first <p> inside /pages/about[-us] with 20–200 chars

Returns:
    {"value": str, "source_url": str, "method": str}  or None

The method field records which step produced the value.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

_OG_DESC_RE   = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{10,300})["\']',
    re.IGNORECASE,
)
_OG_DESC_RE2  = re.compile(
    r'<meta[^>]+content=["\']([^"\']{10,300})["\'][^>]+property=["\']og:description["\']',
    re.IGNORECASE,
)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{10,300})["\']',
    re.IGNORECASE,
)
_META_DESC_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']{10,300})["\'][^>]+name=["\']description["\']',
    re.IGNORECASE,
)
_H1_RE = re.compile(r'<h1[^>]*>([^<]{10,200})</h1>', re.IGNORECASE)
_H2_RE = re.compile(r'<h2[^>]*>([^<]{10,200})</h2>', re.IGNORECASE)
_P_RE  = re.compile(r'<p[^>]*>([^<]{20,200})</p>',  re.IGNORECASE)

_HTML_TAG_RE = re.compile(r'<[^>]+>')


def _clean(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    return " ".join(text.split()).strip()


async def extract(fetcher: "Fetcher", domain: str) -> dict | None:
    """Return tagline evidence dict or None."""
    base = f"https://{domain}"

    # 1 + 2 + 3: homepage
    resp = await fetcher.fetch(base)
    if resp and resp.get("status") == 200:
        html = resp.get("body", "")
        src  = resp.get("url", base)

        for pattern, method in [
            (_OG_DESC_RE,    "og:description"),
            (_OG_DESC_RE2,   "og:description"),
            (_META_DESC_RE,  "meta_description"),
            (_META_DESC_RE2, "meta_description"),
        ]:
            m = pattern.search(html)
            if m:
                value = _clean(m.group(1))
                if value:
                    return {"value": value, "source_url": src, "method": method}

        for pattern, method in [
            (_H1_RE, "hero_h1"),
            (_H2_RE, "hero_h2"),
        ]:
            m = pattern.search(html)
            if m:
                value = _clean(m.group(1))
                if value:
                    return {"value": value, "source_url": src, "method": method}

    # 4: about page paragraph
    for path in ("/pages/about", "/pages/about-us", "/pages/our-story"):
        about_resp = await fetcher.fetch(f"{base}{path}")
        if about_resp and about_resp.get("status") == 200:
            html = about_resp.get("body", "")
            src  = about_resp.get("url", f"{base}{path}")
            for m in _P_RE.finditer(html):
                value = _clean(m.group(1))
                if len(value) >= 20:
                    return {"value": value, "source_url": src, "method": "about_paragraph"}

    return None
