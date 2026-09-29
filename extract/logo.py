"""
Logo extractor.

Fallback chain (stops at first usable hit):
  1. JSON-LD Organization.logo (most reliable — structured data)
  2. Header <img> with logo-hint in src / alt / class / id
  3. og:image meta tag (fallback — often product images, not logos)

Negative filter: <link rel="icon"> / rel="shortcut icon" are favicons, not logos.

Returns:
    {
        "logo_url":        str,   # absolute URL
        "logo_local_path": str,   # "" until downloaded
        "logo_source":     str,   # source_url of the page it was found on
        "method":          str,
    }
    or None
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

_JSONLD_RE  = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)
_IMG_RE = re.compile(r'<img([^>]+)>', re.IGNORECASE)
_SRC_RE = re.compile(r'\bsrc=["\']([^"\']+)["\']', re.IGNORECASE)
_ALT_RE = re.compile(r'\balt=["\']([^"\']*)["\']', re.IGNORECASE)
_CLASS_RE = re.compile(r'\bclass=["\']([^"\']*)["\']', re.IGNORECASE)
_ID_RE  = re.compile(r'\bid=["\']([^"\']*)["\']',    re.IGNORECASE)

_LOGO_HINTS = re.compile(r'\blogo\b', re.IGNORECASE)

# Header / nav containers
_HEADER_RE = re.compile(
    r'<(?:header|nav)[^>]*>(.*?)</(?:header|nav)>',
    re.DOTALL | re.IGNORECASE,
)


def _abs(url: str, base: str) -> str:
    return urljoin(base, url)


def _extract_jsonld_logo(html: str, base: str) -> str | None:
    for m in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            # Handle @graph
            if "@graph" in item:
                items += item["@graph"]
                continue
            if item.get("@type") in ("Organization", "Store", "LocalBusiness"):
                logo = item.get("logo")
                if isinstance(logo, str) and logo:
                    return _abs(logo, base)
                if isinstance(logo, dict):
                    url = logo.get("url") or logo.get("contentUrl") or ""
                    if url:
                        return _abs(url, base)
    return None


def _extract_header_logo(html: str, base: str) -> str | None:
    # Look inside header/nav first, then fall back to full page
    search_html = " ".join(m.group(1) for m in _HEADER_RE.finditer(html)) or html
    for m in _IMG_RE.finditer(search_html):
        attrs = m.group(1)
        src_m = _SRC_RE.search(attrs)
        if not src_m:
            continue
        src = src_m.group(1)
        if not src or src.startswith("data:"):
            continue
        # Check for logo hints in src, alt, class, id
        alt   = (_ALT_RE.search(attrs)   or ["", ""])[1] if hasattr((_ALT_RE.search(attrs)), 'group') else ""
        cls   = (_CLASS_RE.search(attrs) or ["", ""])[1] if hasattr((_CLASS_RE.search(attrs)), 'group') else ""
        id_   = (_ID_RE.search(attrs)    or ["", ""])[1] if hasattr((_ID_RE.search(attrs)), 'group') else ""
        alt_m   = _ALT_RE.search(attrs)
        cls_m   = _CLASS_RE.search(attrs)
        id_m    = _ID_RE.search(attrs)
        alt   = alt_m.group(1)   if alt_m   else ""
        cls   = cls_m.group(1)   if cls_m   else ""
        id_   = id_m.group(1)    if id_m    else ""
        combined = f"{src} {alt} {cls} {id_}"
        if _LOGO_HINTS.search(combined):
            return _abs(src, base)
    return None


async def extract(fetcher: "Fetcher", domain: str) -> dict | None:
    """Return logo evidence dict or None."""
    base = f"https://{domain}"
    resp = await fetcher.fetch(base)
    if not (resp and resp.get("status") == 200):
        return None

    html = resp.get("body", "")
    src  = resp.get("url", base)

    # 1. JSON-LD
    logo_url = _extract_jsonld_logo(html, src)
    if logo_url:
        return {"logo_url": logo_url, "logo_local_path": "",
                "logo_source": src, "method": "jsonld_organization"}

    # 2. Header img with logo hint
    logo_url = _extract_header_logo(html, src)
    if logo_url:
        return {"logo_url": logo_url, "logo_local_path": "",
                "logo_source": src, "method": "header_img"}

    # 3. og:image fallback
    for pat in (_OG_IMAGE_RE, _OG_IMAGE_RE2):
        m = pat.search(html)
        if m:
            url = m.group(1).strip()
            if url:
                return {"logo_url": _abs(url, src), "logo_local_path": "",
                        "logo_source": src, "method": "og_image"}

    return None
