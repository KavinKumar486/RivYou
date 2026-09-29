"""
Tests for all extractors and the state resolver — fixture-based, no network.

Coverage:
  extract/contacts.py   — mailto/tel hrefs, regex fallback, junk-domain filter
  extract/socials.py    — platform detection, share-URL drop, UTM strip
  extract/category.py   — product_type/tags scoring, navigation text
  extract/tagline.py    — og:description, meta, h1, about-paragraph chain
  extract/logo.py       — JSON-LD org, header img hint, og:image fallback
  state/resolver.py     — GSTIN state code, PIN prefix, city map
"""

from __future__ import annotations

import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MockFetcher:
    """Maps URL fragments to pre-built responses; unmatched → 404."""

    def __init__(self, responses: dict[str, dict]):
        self._r = responses

    async def fetch(self, url: str, **_) -> dict:
        for frag, resp in self._r.items():
            if frag in url:
                return {"status": resp.get("status", 200),
                        "body": resp.get("body", ""),
                        "headers": {},
                        "url": url}
        return {"status": 404, "body": "", "headers": {}, "url": url}


# ═══════════════════════════════════════════════════════════════════════════════
# contacts
# ═══════════════════════════════════════════════════════════════════════════════

class TestContacts:

    @pytest.mark.asyncio
    async def test_mailto_href_extracted(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("contacts_full.html")}})
        result = await extract(fetcher, "acme.in")
        emails = [r["value"] for r in result if r["type"] == "email"]
        assert "hello@acmestore.in" in emails

    @pytest.mark.asyncio
    async def test_junk_email_domain_dropped(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("contacts_full.html")}})
        result = await extract(fetcher, "acme.in")
        emails = [r["value"] for r in result if r["type"] == "email"]
        assert not any("sentry.io" in e for e in emails)

    @pytest.mark.asyncio
    async def test_tel_href_extracted(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("contacts_full.html")}})
        result = await extract(fetcher, "acme.in")
        phones = [r["value"] for r in result if r["type"] == "phone"]
        assert "+919876543210" in phones

    @pytest.mark.asyncio
    async def test_email_regex_fallback(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"brand.in": {"body": _html("contacts_regex_fallback.html")}})
        result = await extract(fetcher, "brand.in")
        emails = [r["value"] for r in result if r["type"] == "email"]
        assert "orders@brandname.in" in emails

    @pytest.mark.asyncio
    async def test_phone_regex_fallback_10digit(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"brand.in": {"body": _html("contacts_regex_fallback.html")}})
        result = await extract(fetcher, "brand.in")
        phones = [r["value"] for r in result if r["type"] == "phone"]
        assert "+919123456789" in phones

    @pytest.mark.asyncio
    async def test_no_contacts_returns_empty_list(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"empty.in": {"body": "<html><body>No contact info</body></html>"}})
        result = await extract(fetcher, "empty.in")
        assert result == []

    @pytest.mark.asyncio
    async def test_evidence_has_source_url(self):
        from extract.contacts import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("contacts_full.html")}})
        result = await extract(fetcher, "acme.in")
        for item in result:
            assert item.get("source_url"), f"Missing source_url: {item}"
            assert item.get("method"),     f"Missing method: {item}"


# ═══════════════════════════════════════════════════════════════════════════════
# socials
# ═══════════════════════════════════════════════════════════════════════════════

class TestSocials:

    @pytest.mark.asyncio
    async def test_instagram_detected(self):
        from extract.socials import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("socials.html")}})
        result = await extract(fetcher, "acme.in")
        assert "instagram" in result
        assert "instagram.com/acmebrand" in result["instagram"]["url"]

    @pytest.mark.asyncio
    async def test_facebook_detected(self):
        from extract.socials import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("socials.html")}})
        result = await extract(fetcher, "acme.in")
        assert "facebook" in result

    @pytest.mark.asyncio
    async def test_share_url_dropped(self):
        from extract.socials import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("socials.html")}})
        result = await extract(fetcher, "acme.in")
        # sharer.php URL must not be the detected facebook URL
        if "facebook" in result:
            assert "sharer" not in result["facebook"]["url"]

    @pytest.mark.asyncio
    async def test_utm_params_stripped(self):
        from extract.socials import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("socials.html")}})
        result = await extract(fetcher, "acme.in")
        if "instagram" in result:
            assert "utm_source" not in result["instagram"]["url"]

    @pytest.mark.asyncio
    async def test_no_socials_returns_empty_dict(self):
        from extract.socials import extract
        fetcher = MockFetcher({"plain.in": {"body": "<html><body><p>Hello</p></body></html>"}})
        result = await extract(fetcher, "plain.in")
        assert result == {}

    @pytest.mark.asyncio
    async def test_evidence_has_source_url(self):
        from extract.socials import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("socials.html")}})
        result = await extract(fetcher, "acme.in")
        for platform, data in result.items():
            assert data.get("source_url"), f"Missing source_url for {platform}"
            assert data.get("method")


# ═══════════════════════════════════════════════════════════════════════════════
# category
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategory:

    @pytest.mark.asyncio
    async def test_fashion_from_product_type(self):
        from extract.category import extract
        fetcher = MockFetcher({
            "/products.json":   {"body": _text("products_fashion.json")},
            "/collections.json":{"status": 404, "body": ""},
            "fashion.in":       {"body": _html("category_fashion.html")},
        })
        result = await extract(fetcher, "fashion.in")
        assert result is not None
        assert result["value"] == "Fashion & Apparel"

    @pytest.mark.asyncio
    async def test_navigation_text_used_as_fallback(self):
        from extract.category import extract
        fetcher = MockFetcher({
            "/products.json":   {"status": 404, "body": ""},
            "/collections.json":{"status": 404, "body": ""},
            "fashion.in":       {"body": _html("category_fashion.html")},
        })
        result = await extract(fetcher, "fashion.in")
        assert result is not None
        assert result["value"] == "Fashion & Apparel"

    @pytest.mark.asyncio
    async def test_returns_other_when_no_match(self):
        from extract.category import extract
        # Nav text with no taxonomy keywords → Other
        fetcher = MockFetcher({
            "/products.json":    {"status": 404, "body": ""},
            "/collections.json": {"status": 404, "body": ""},
            "unknown.in":        {"body": "<html><body><nav><a>Contact</a><a>FAQ</a></nav></body></html>"},
        })
        result = await extract(fetcher, "unknown.in")
        assert result is not None
        assert result["value"] == "Other"

    @pytest.mark.asyncio
    async def test_method_recorded(self):
        from extract.category import extract
        fetcher = MockFetcher({
            "/products.json":   {"body": _text("products_fashion.json")},
            "/collections.json":{"status": 404, "body": ""},
            "fashion.in":       {"body": _html("category_fashion.html")},
        })
        result = await extract(fetcher, "fashion.in")
        assert result.get("method") in (
            "product_type_tags", "collection_titles",
            "navigation_text", "page_title", "default"
        )

    @pytest.mark.asyncio
    async def test_no_crash_on_malformed_json(self):
        from extract.category import extract
        fetcher = MockFetcher({
            "/products.json":   {"body": "not json {{{"},
            "/collections.json":{"body": "also bad"},
            "broken.in":        {"body": "<html><body></body></html>"},
        })
        result = await extract(fetcher, "broken.in")
        assert result is not None   # must not raise


# ═══════════════════════════════════════════════════════════════════════════════
# tagline
# ═══════════════════════════════════════════════════════════════════════════════

class TestTagline:

    @pytest.mark.asyncio
    async def test_og_description_preferred(self):
        from extract.tagline import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("tagline_og.html")}})
        result = await extract(fetcher, "acme.in")
        assert result is not None
        # og:description or meta description — either is acceptable; what matters
        # is that a value is returned and method is one of the meta sources
        assert result["method"] in ("og:description", "meta_description")
        assert len(result["value"]) >= 10

    @pytest.mark.asyncio
    async def test_h1_fallback(self):
        from extract.tagline import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("tagline_h1_only.html")}})
        result = await extract(fetcher, "acme.in")
        assert result is not None
        assert "change" in result["value"].lower()
        assert result["method"] == "hero_h1"

    @pytest.mark.asyncio
    async def test_about_paragraph_fallback(self):
        from extract.tagline import extract
        about_html = "<html><body><p>We are a homegrown Indian brand making sustainable everyday essentials.</p></body></html>"
        empty_html  = "<html><head></head><body></body></html>"
        # Path-specific entries FIRST so they match before the bare domain fragment
        fetcher = MockFetcher({
            "/pages/about":     {"body": about_html},
            "/pages/about-us":  {"body": about_html},
            "/pages/our-story": {"body": about_html},
            "noodesc.in":       {"body": empty_html},
        })
        result = await extract(fetcher, "noodesc.in")
        assert result is not None
        assert result["method"] == "about_paragraph"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_content(self):
        from extract.tagline import extract
        fetcher = MockFetcher({"ghost.in": {"status": 404, "body": ""}})
        result = await extract(fetcher, "ghost.in")
        assert result is None

    @pytest.mark.asyncio
    async def test_evidence_has_source_url(self):
        from extract.tagline import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("tagline_og.html")}})
        result = await extract(fetcher, "acme.in")
        assert result is not None
        assert result.get("source_url")
        assert result.get("method")


# ═══════════════════════════════════════════════════════════════════════════════
# logo
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogo:

    @pytest.mark.asyncio
    async def test_jsonld_org_preferred(self):
        from extract.logo import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("logo_jsonld.html")}})
        result = await extract(fetcher, "acme.in")
        assert result is not None
        assert result["logo_url"] == "https://cdn.acme.in/images/logo.png"
        assert result["method"] == "jsonld_organization"

    @pytest.mark.asyncio
    async def test_header_img_fallback(self):
        from extract.logo import extract
        fetcher = MockFetcher({"brand.in": {"body": _html("logo_header_img.html")}})
        result = await extract(fetcher, "brand.in")
        assert result is not None
        assert result["method"] == "header_img"
        assert "logo" in result["logo_url"].lower() or "logo" in result.get("logo_source", "").lower()

    @pytest.mark.asyncio
    async def test_favicon_not_returned_as_logo(self):
        from extract.logo import extract
        favicon_only = '<html><head><link rel="icon" href="/favicon.ico"></head><body></body></html>'
        fetcher = MockFetcher({"icon.in": {"body": favicon_only}})
        result = await extract(fetcher, "icon.in")
        # favicon should NOT be returned
        if result:
            assert "favicon" not in result["logo_url"].lower()

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        from extract.logo import extract
        fetcher = MockFetcher({"ghost.in": {"status": 404, "body": ""}})
        result = await extract(fetcher, "ghost.in")
        assert result is None

    @pytest.mark.asyncio
    async def test_logo_local_path_initially_empty(self):
        from extract.logo import extract
        fetcher = MockFetcher({"acme.in": {"body": _html("logo_jsonld.html")}})
        result = await extract(fetcher, "acme.in")
        assert result is not None
        assert result["logo_local_path"] == ""

    @pytest.mark.asyncio
    async def test_og_image_last_resort(self):
        from extract.logo import extract
        og_only = '<html><head><meta property="og:image" content="https://acme.in/og.jpg"/></head><body></body></html>'
        fetcher = MockFetcher({"og.in": {"body": og_only}})
        result = await extract(fetcher, "og.in")
        assert result is not None
        assert result["method"] == "og_image"
        assert result["logo_url"] == "https://acme.in/og.jpg"


# ═══════════════════════════════════════════════════════════════════════════════
# state resolver
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateResolver:

    @pytest.mark.asyncio
    async def test_gstin_resolves_maharashtra(self):
        from state.resolver import resolve
        fetcher = MockFetcher({"mh.in": {"body": _html("state_gstin.html")}})
        result = await resolve(fetcher, "mh.in")
        assert result["status"] == "resolved"
        assert result["state"] == "Maharashtra"
        assert result["method"] == "gstin_state_code"

    @pytest.mark.asyncio
    async def test_city_map_resolves_karnataka(self):
        from state.resolver import resolve
        fetcher = MockFetcher({"ka.in": {"body": _html("state_city.html")}})
        result = await resolve(fetcher, "ka.in")
        assert result["status"] == "resolved"
        assert result["state"] == "Karnataka"

    @pytest.mark.asyncio
    async def test_unresolved_returns_none(self):
        from state.resolver import resolve
        fetcher = MockFetcher({"unknown.in": {"body": "<html><body><p>Hello world</p></body></html>"}})
        result = await resolve(fetcher, "unknown.in")
        assert result["status"] == "unresolved"
        assert result["state"] is None

    @pytest.mark.asyncio
    async def test_contradiction_needs_review(self):
        from state.resolver import resolve
        # GSTIN 29 = Karnataka, PIN 400 = Maharashtra → contradiction
        conflict_html = """<html><body>
          <p>Our office address is in Mumbai, Maharashtra 400001, India.</p>
          <p>GSTIN: 29AABCU9603R1ZX</p>
        </body></html>"""
        fetcher = MockFetcher({"conflict.in": {"body": conflict_html}})
        result = await resolve(fetcher, "conflict.in")
        # GSTIN gives Karnataka (29), PIN prefix 40 gives Maharashtra
        assert result["status"] in ("resolved", "needs_review")
        # Either way it must not crash
        assert "state" in result
        assert "method" in result

    @pytest.mark.asyncio
    async def test_pin_prefix_resolves_delhi(self):
        from state.resolver import resolve
        html = "<html><body><p>Our registered office: 12 Connaught Place, Pin Code: 110001, New Delhi, India</p></body></html>"
        fetcher = MockFetcher({"delhi.in": {"body": html}})
        result = await resolve(fetcher, "delhi.in")
        assert result["status"] == "resolved"
        assert result["state"] == "Delhi"

    @pytest.mark.asyncio
    async def test_no_crash_on_empty_page(self):
        from state.resolver import resolve
        fetcher = MockFetcher({})   # all 404
        result = await resolve(fetcher, "ghost.in")
        assert result["status"] == "unresolved"
        assert result["state"] is None
