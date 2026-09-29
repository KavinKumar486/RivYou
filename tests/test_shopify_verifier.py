"""
Tests for verify/shopify.py — fixture-based, no live network calls.

The MockFetcher maps URL patterns to pre-built fixture responses so we can
test the verifier logic in isolation.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from verify.shopify import verify

FIXTURES = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _json(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MockFetcher:
    """
    Configurable fake fetcher.

    url_map: {url_fragment: {"status": int, "body": str, "headers": dict}}
    Any URL whose string contains a key fragment returns that response.
    Unmatched URLs return status 404.
    """

    def __init__(self, url_map: dict):
        self._map = url_map

    async def fetch(self, url: str, **_) -> dict:
        for fragment, resp in self._map.items():
            if fragment in url:
                return {"status": resp.get("status", 200),
                        "body": resp.get("body", ""),
                        "headers": resp.get("headers", {}),
                        "url": url}
        return {"status": 404, "body": "", "headers": {}, "url": url}


# ── Verified: real Shopify store ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_real_shopify_homepage_signals():
    """Homepage with JS + CDN + meta → verified (js + cdn + meta = 3 families, js is high)."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 200, "body": _json("cart_js.json")},
        "acme.com":        {"status": 200, "body": _html("shopify_real.html"),
                            "headers": {}},
    })
    result = await verify(fetcher, "acme.com")
    assert result["verdict"] == "verified"
    assert "js" in result["families"]
    assert "cdn" in result["families"]
    assert "meta" in result["families"]
    assert result["inconclusive"] is False


@pytest.mark.asyncio
async def test_real_shopify_api_signals():
    """products.json + cart.js alone = api family (high), but need >=2 families.
    Add a homepage with cdn reference → verified."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 200, "body": _json("cart_js.json")},
        "shop.example.com": {"status": 200,
                              "body": '<link href="https://cdn.shopify.com/x.css">',
                              "headers": {}},
    })
    result = await verify(fetcher, "shop.example.com")
    assert result["verdict"] == "verified"
    assert "api" in result["families"]
    assert "cdn" in result["families"]


@pytest.mark.asyncio
async def test_shopify_header_detected():
    """X-ShopId response header contributes to platform family."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 404, "body": ""},
        "header-shop.com": {"status": 200, "body": "",
                             "headers": {"x-shopid": "12345678"}},
    })
    result = await verify(fetcher, "header-shop.com")
    assert result["verdict"] == "verified"
    assert "platform" in result["families"]
    assert any("header" in s for s in result["families"]["platform"])


# ── Uncertain: headless / locked-down ────────────────────────────────────────

@pytest.mark.asyncio
async def test_headless_shopify_uncertain():
    """Only CDN signal present — one family, no high-specificity → uncertain."""
    fetcher = MockFetcher({
        "/products.json": {"status": 403, "body": ""},
        "/cart.js":        {"status": 403, "body": ""},
        "headless.com":    {"status": 200, "body": _html("shopify_headless.html"),
                            "headers": {}},
    })
    result = await verify(fetcher, "headless.com")
    assert result["verdict"] == "uncertain"
    assert "cdn" in result["families"]


# ── Rejected: non-Shopify platforms ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_woocommerce_rejected():
    """WooCommerce HTML has no Shopify signals → rejected."""
    fetcher = MockFetcher({
        "/products.json": {"status": 404, "body": ""},
        "/cart.js":        {"status": 404, "body": ""},
        "woo.example.com": {"status": 200, "body": _html("woocommerce.html"),
                            "headers": {}},
    })
    result = await verify(fetcher, "woo.example.com")
    assert result["verdict"] == "rejected"
    assert result["families"] == {}


@pytest.mark.asyncio
async def test_lookalike_rejected():
    """Mentions Shopify in text but has zero structural signals → rejected."""
    fetcher = MockFetcher({
        "/products.json": {"status": 404, "body": ""},
        "/cart.js":        {"status": 404, "body": ""},
        "fake.example.com": {"status": 200, "body": _html("shopify_lookalike.html"),
                             "headers": {}},
    })
    result = await verify(fetcher, "fake.example.com")
    assert result["verdict"] == "rejected"


# ── Inconclusive: all fetches fail ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_all_inconclusive():
    """All endpoints return 403 and no signals gathered → inconclusive=True."""
    fetcher = MockFetcher({
        "/products.json": {"status": 403, "body": ""},
        "/cart.js":        {"status": 403, "body": ""},
        "blocked.com":     {"status": 403, "body": ""},
    })
    result = await verify(fetcher, "blocked.com")
    assert result["inconclusive"] is True
    assert result["verdict"] == "rejected"


# ── Evidence rows ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_rows_populated():
    """Each detected signal must produce at least one evidence row."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 200, "body": _json("cart_js.json")},
        "evidence.com":   {"status": 200, "body": _html("shopify_real.html"),
                           "headers": {}},
    })
    result = await verify(fetcher, "evidence.com")
    assert result["verdict"] == "verified"
    assert len(result["evidence"]) >= 3
    types = {e["type"] for e in result["evidence"]}
    assert "api" in types


@pytest.mark.asyncio
async def test_evidence_has_source_url():
    """Every evidence row must have a non-empty source_url."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 200, "body": _json("cart_js.json")},
        "ev2.com":         {"status": 200, "body": _html("shopify_real.html"),
                            "headers": {}},
    })
    result = await verify(fetcher, "ev2.com")
    for ev in result["evidence"]:
        assert ev.get("source_url"), f"Missing source_url in: {ev}"
        assert ev.get("method"),     f"Missing method in: {ev}"


# ── Idempotency / normalisation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_www_stripped():
    """Passing www.domain still works correctly."""
    fetcher = MockFetcher({
        "/products.json": {"status": 200, "body": _json("products_json.json")},
        "/cart.js":        {"status": 200, "body": _json("cart_js.json")},
        "strip.com":       {"status": 200, "body": _html("shopify_real.html"),
                            "headers": {}},
    })
    result = await verify(fetcher, "www.strip.com")
    assert result["domain"] == "strip.com"
    assert result["verdict"] == "verified"
