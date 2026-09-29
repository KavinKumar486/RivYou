"""
Socials extractor.

Finds official social media profile links from anchor hrefs.
Platforms: Instagram, Facebook, X/Twitter, LinkedIn, YouTube, Pinterest.

Rules:
  - Only href anchors (not src, not JS strings) — avoids tracking pixels
  - Share / intent URLs dropped (share?, intent/tweet, sharer.php etc.)
  - UTM / tracking params stripped from URLs
  - One canonical URL per platform (first non-share hit wins)

Returns:
    {"instagram": url, "facebook": url, ...}  — only platforms found
    Each value is {"url": str, "source_url": str, "method": "anchor_href"}
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlencode, parse_qs
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

# Platform patterns: (name, domain_fragment, share_path_fragments)
_PLATFORMS: list[tuple[str, str, list[str]]] = [
    ("instagram", "instagram.com",  ["share", "sharer"]),
    ("facebook",  "facebook.com",   ["share", "sharer", "dialog/share"]),
    ("twitter",   "twitter.com",    ["intent", "share"]),
    ("twitter",   "x.com",          ["intent", "share"]),
    ("linkedin",  "linkedin.com",   ["share", "shareArticle"]),
    ("youtube",   "youtube.com",    ["share"]),
    ("pinterest", "pinterest.com",  ["pin/create", "share"]),
]

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_UTM_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
               "fbclid", "gclid", "ref", "igshid"}

_PAGES = ["", "/pages/about", "/pages/contact"]


def _strip_tracking(url: str) -> str:
    try:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=False)
        clean = {k: v for k, v in qs.items() if k not in _UTM_PARAMS}
        new_query = urlencode(clean, doseq=True)
        return p._replace(query=new_query, fragment="").geturl()
    except Exception:
        return url


def _is_share_url(url: str, share_fragments: list[str]) -> bool:
    lower = url.lower()
    return any(frag.lower() in lower for frag in share_fragments)


def _match_platform(url: str) -> tuple[str, str] | None:
    """Return (platform_name, cleaned_url) or None."""
    for name, domain, share_frags in _PLATFORMS:
        if domain in url.lower():
            if _is_share_url(url, share_frags):
                return None
            return name, _strip_tracking(url)
    return None


async def extract(fetcher: "Fetcher", domain: str) -> dict:
    """Return social profile dict for *domain*."""
    base = f"https://{domain}"
    found: dict[str, dict] = {}   # platform → {url, source_url, method}

    for path in _PAGES:
        url = f"{base}{path}"
        resp = await fetcher.fetch(url)
        if not (resp and resp.get("status") == 200):
            continue
        html = resp.get("body", "")
        src  = resp.get("url", url)

        for m in _HREF_RE.finditer(html):
            href = m.group(1)
            if not href.startswith("http"):
                continue
            match = _match_platform(href)
            if match:
                name, clean_url = match
                if name not in found:
                    found[name] = {"url": clean_url, "source_url": src,
                                   "method": "anchor_href"}

        # Stop early once all major platforms found
        if len(found) >= 5:
            break

    return found
