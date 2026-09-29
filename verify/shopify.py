"""
Shopify verifier — production version.

Evidence families (only one signal per family counts):

  Family          | Signals                                          | Specificity
  ----------------+--------------------------------------------------+------------
  api             | /products.json valid, /cart.js valid             | High
  js              | Shopify.shop / Shopify.theme JS objects          | High
  cdn             | cdn.shopify.com or /cdn/shop/ in HTML            | Medium
  platform        | X-ShopId header, myshopify.com in HTML,          | Medium
                  | checkout redirect to myshopify                   |
  meta            | <meta name="shopify-…">, shopify-features attr   | Medium

Verdict rule:
  verified  — >= 2 families active, at least one is High (api or js)
  uncertain — some signals but rule not met  (headless / locked-down)
  rejected  — no signals at all

inconclusive — set when all fetches returned 403/429/503/timeout and no
               signals were gathered; excluded from yield calculations.

Every call returns a structured evidence dict that is written to the DB.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

# ── compiled regexes ──────────────────────────────────────────────────────────

_PRODUCTS_JSON_RE = re.compile(r'"products"\s*:', re.IGNORECASE)
_PRODUCTS_HANDLE_RE = re.compile(
    r'"handle"\s*:|"variants"\s*:|"product_type"\s*:', re.IGNORECASE
)
_CART_JS_RE = re.compile(
    r'"item_count"\s*:|"token"\s*:.*?"items"\s*:', re.IGNORECASE | re.DOTALL
)
_SHOPIFY_JS_RE = re.compile(
    r'Shopify\.shop\b|Shopify\.theme\b|ShopifyAnalytics\b'
    r'|window\.Shopify\s*=|"shopify_domain"',
    re.IGNORECASE,
)
_SHOPIFY_CDN_RE = re.compile(r'cdn\.shopify\.com|/cdn/shop/', re.IGNORECASE)
_MYSHOPIFY_HTML_RE = re.compile(r'[a-z0-9\-]+\.myshopify\.com', re.IGNORECASE)
_SHOPIFY_META_RE = re.compile(r'name=["\']shopify|shopify-features', re.IGNORECASE)
_SHOPIFY_HEADER_RE = re.compile(
    r'^x-shopid$|^x-shardid$|^x-sorting-hat', re.IGNORECASE
)
_MYSHOPIFY_CHECKOUT_RE = re.compile(
    r'https?://[a-z0-9\-]+\.myshopify\.com/\d+/checkouts', re.IGNORECASE
)

_INCONCLUSIVE_STATUSES = {403, 429, 503, 999}
_HIGH_FAMILIES = {"api", "js"}


# ── internal helpers ──────────────────────────────────────────────────────────

def _ok(resp: dict | None) -> bool:
    return resp is not None and resp.get("status") == 200


def _inconclusive(resp: dict | None) -> bool:
    if resp is None:
        return True
    return resp.get("status", -1) in _INCONCLUSIVE_STATUSES


async def _fetch(fetcher: "Fetcher", url: str,
                 bypass_cache: bool = False) -> dict | None:
    """Fetch url; on hard failure try the HTTP variant."""
    resp = await fetcher.fetch(url, refresh=bypass_cache)
    if resp is None or resp.get("status", -1) < 0:
        if url.startswith("https://"):
            resp = await fetcher.fetch("http://" + url[8:], refresh=bypass_cache)
    return resp


# ── public API ────────────────────────────────────────────────────────────────

async def verify(fetcher: "Fetcher", domain: str,
                 bypass_cache: bool = False) -> dict:
    """
    Verify whether *domain* is a Shopify store.

    Returns::

        {
            "domain":       str,
            "verdict":      "verified" | "uncertain" | "rejected",
            "inconclusive": bool,
            "families":     {family: [signal, ...]},
            "evidence":     [{"type", "value", "source_url", "method"}, ...],
        }

    The ``evidence`` list is suitable for direct insertion into the
    ``evidence`` table (check_type = "shopify").
    """
    domain = domain.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]

    base = f"https://{domain}"
    www  = f"https://www.{domain}"

    families: dict[str, list[str]] = {
        "api": [], "js": [], "cdn": [], "platform": [], "meta": []
    }
    evidence: list[dict] = []
    inconclusive_hits = 0
    total_fetches = 0

    def _ev(typ: str, value: str, source_url: str, method: str) -> None:
        evidence.append({"type": typ, "value": value,
                         "source_url": source_url, "method": method})

    # ── API family ────────────────────────────────────────────────────────
    prod_url = f"{base}/products.json?limit=1"
    prod_resp = await _fetch(fetcher, prod_url, bypass_cache)
    total_fetches += 1
    if _inconclusive(prod_resp):
        prod_resp = await _fetch(fetcher, f"{www}/products.json?limit=1", bypass_cache)
        total_fetches += 1
        if _inconclusive(prod_resp):
            inconclusive_hits += 1
    if _ok(prod_resp):
        body = prod_resp.get("body", "")
        if _PRODUCTS_JSON_RE.search(body) and _PRODUCTS_HANDLE_RE.search(body):
            families["api"].append("products_json")
            _ev("api", "products_json", prod_resp.get("url", prod_url), "http_get")

    cart_url = f"{base}/cart.js"
    cart_resp = await _fetch(fetcher, cart_url, bypass_cache)
    total_fetches += 1
    if _ok(cart_resp):
        body = cart_resp.get("body", "")
        if _CART_JS_RE.search(body) or ('"item_count"' in body and '"token"' in body):
            families["api"].append("cart_js")
            _ev("api", "cart_js", cart_resp.get("url", cart_url), "http_get")

    # ── Homepage families (js / cdn / platform / meta) ────────────────────
    home_resp = await _fetch(fetcher, base, bypass_cache)
    total_fetches += 1
    if _inconclusive(home_resp):
        home_resp = await _fetch(fetcher, www, bypass_cache)
        total_fetches += 1
        if _inconclusive(home_resp):
            inconclusive_hits += 1

    if _ok(home_resp):
        html    = home_resp.get("body", "")
        headers = home_resp.get("headers", {})
        src_url = home_resp.get("url", base)

        # js
        if _SHOPIFY_JS_RE.search(html):
            families["js"].append("shopify_js_object")
            _ev("js", "shopify_js_object", src_url, "html_parse")

        # cdn
        if _SHOPIFY_CDN_RE.search(html):
            families["cdn"].append("shopify_cdn")
            _ev("cdn", "shopify_cdn", src_url, "html_parse")

        # platform — myshopify in HTML
        if _MYSHOPIFY_HTML_RE.search(html):
            families["platform"].append("myshopify_in_html")
            _ev("platform", "myshopify_in_html", src_url, "html_parse")

        # platform — checkout redirect pattern
        if _MYSHOPIFY_CHECKOUT_RE.search(html):
            if "checkout_redirect" not in families["platform"]:
                families["platform"].append("checkout_redirect")
                _ev("platform", "checkout_redirect", src_url, "html_parse")

        # platform — Shopify response headers
        for h_name in headers:
            if _SHOPIFY_HEADER_RE.match(h_name):
                families["platform"].append("shopify_header")
                _ev("platform", f"header:{h_name.lower()}", src_url, "http_header")
                break

        # meta
        if _SHOPIFY_META_RE.search(html):
            families["meta"].append("shopify_meta")
            _ev("meta", "shopify_meta", src_url, "html_parse")

    # ── Verdict ───────────────────────────────────────────────────────────
    active = {f for f, sigs in families.items() if sigs}
    has_high = bool(active & _HIGH_FAMILIES)

    if has_high and len(active) >= 2:
        verdict = "verified"
    elif active:
        verdict = "uncertain"
    else:
        verdict = "rejected"

    all_inconclusive = (
        inconclusive_hits >= 2
        and total_fetches >= 3
        and not evidence
    )

    return {
        "domain":       domain,
        "verdict":      verdict,
        "inconclusive": all_inconclusive,
        "families":     {f: v for f, v in families.items() if v},
        "evidence":     evidence,
    }
