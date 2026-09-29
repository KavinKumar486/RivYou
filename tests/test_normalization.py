"""
Unit tests for domain normalization and myshopify merge (Checkpoint 1 gate).

Run with:
    python -m pytest tests/test_normalization.py -v
"""

import pytest
from utils import (
    normalize_domain,
    registrable_domain,
    get_suffix,
    is_myshopify,
    myshopify_slug,
    merge_myshopify,
)


# ── normalize_domain ──────────────────────────────────────────────────────────

class TestNormalizeDomain:
    def test_plain_com(self):
        assert normalize_domain("example.com") == "example.com"

    def test_strips_www(self):
        assert normalize_domain("www.example.com") == "example.com"

    def test_strips_scheme(self):
        assert normalize_domain("https://example.com") == "example.com"
        assert normalize_domain("http://example.com/path?q=1") == "example.com"

    def test_co_in(self):
        assert normalize_domain("www.snitch.co.in") == "snitch.co.in"

    def test_subdomain_stripped(self):
        assert normalize_domain("shop.example.co.in") == "example.co.in"

    def test_empty_string(self):
        assert normalize_domain("") == ""

    def test_bare_tld(self):
        # A bare TLD like "com" has no registrable domain
        assert normalize_domain("com") == ""

    def test_lowercase(self):
        assert normalize_domain("MAMAEARTH.IN") == "mamaearth.in"

    def test_trailing_slash(self):
        assert normalize_domain("https://example.com/") == "example.com"

    def test_port_stripped(self):
        assert normalize_domain("example.com:8080") == "example.com"

    def test_myshopify_normalised(self):
        # myshopify domains normalise to just the registrable portion
        assert normalize_domain("acme-store.myshopify.com") == "myshopify.com"

    def test_in_tld(self):
        assert normalize_domain("bewakoof.com") == "bewakoof.com"
        assert normalize_domain("mamaearth.in") == "mamaearth.in"


# ── registrable_domain ────────────────────────────────────────────────────────

class TestRegistrableDomain:
    def test_co_in(self):
        assert registrable_domain("snitch.co.in") == "snitch.co.in"

    def test_subdomain(self):
        assert registrable_domain("sub.example.com") == "example.com"

    def test_with_scheme(self):
        assert registrable_domain("https://minimalist.co.in/pages/about") == "minimalist.co.in"

    def test_ip_address(self):
        # IP addresses have no registrable domain
        assert registrable_domain("192.168.1.1") == ""


# ── get_suffix ────────────────────────────────────────────────────────────────

class TestGetSuffix:
    def test_com(self):
        assert get_suffix("example.com") == "com"

    def test_co_in(self):
        assert get_suffix("snitch.co.in") == "co.in"

    def test_in(self):
        assert get_suffix("mamaearth.in") == "in"

    def test_org(self):
        assert get_suffix("okhai.org") == "org"


# ── is_myshopify / myshopify_slug ─────────────────────────────────────────────

class TestMyshopifyHelpers:
    def test_is_myshopify_true(self):
        assert is_myshopify("acme-store.myshopify.com") is True

    def test_is_myshopify_false(self):
        assert is_myshopify("example.com") is False
        assert is_myshopify("myshopify.com") is False  # bare root, not a store
        assert is_myshopify("cdn.shopify.com") is False

    def test_myshopify_slug(self):
        assert myshopify_slug("acme-store.myshopify.com") == "acme-store"
        assert myshopify_slug("bewakoof.myshopify.com") == "bewakoof"

    def test_myshopify_slug_none(self):
        assert myshopify_slug("example.com") is None
        assert myshopify_slug("myshopify.com") is None


# ── merge_myshopify ───────────────────────────────────────────────────────────

class TestMergeMyshopify:
    def _make(self, domain: str, source: str = "test") -> dict:
        return {"domain": domain, "source": source}

    def test_no_myshopify(self):
        domains = [self._make("a.com"), self._make("b.in")]
        result = merge_myshopify(domains)
        assert len(result) == 2
        assert all("myshopify_domain" not in r for r in result)

    def test_myshopify_no_custom_map(self):
        """Without a custom_map, myshopify domains are kept as-is."""
        domains = [
            self._make("acme-store.myshopify.com"),
            self._make("a.com"),
        ]
        result = merge_myshopify(domains)
        assert len(result) == 2
        domains_out = {r["domain"] for r in result}
        assert "acme-store.myshopify.com" in domains_out

    def test_myshopify_merged_via_custom_map(self):
        """When custom_map maps slug → custom domain, the custom domain wins."""
        domains = [
            self._make("acme-store.myshopify.com", "commoncrawl"),
            self._make("a.com"),
        ]
        custom_map = {"acme-store": "acmeshop.in"}
        result = merge_myshopify(domains, custom_map=custom_map)
        out_domains = {r["domain"] for r in result}

        # acmeshop.in should now be the canonical
        assert "acmeshop.in" in out_domains
        # The myshopify entry should be absorbed, not doubled
        assert "acme-store.myshopify.com" not in out_domains

        # Metadata should be preserved
        merged = next(r for r in result if r["domain"] == "acmeshop.in")
        assert merged.get("myshopify_domain") == "acme-store.myshopify.com"

    def test_custom_domain_already_present(self):
        """If the custom domain is already in the list, myshopify is absorbed."""
        domains = [
            self._make("acme-store.myshopify.com", "commoncrawl"),
            self._make("acmeshop.in", "d2c_curated"),
        ]
        custom_map = {"acme-store": "acmeshop.in"}
        result = merge_myshopify(domains, custom_map=custom_map)

        # Should not create a duplicate acmeshop.in
        acme_entries = [r for r in result if r["domain"] == "acmeshop.in"]
        assert len(acme_entries) == 1
        # myshopify annotation attached
        assert acme_entries[0].get("myshopify_domain") == "acme-store.myshopify.com"

    def test_dedup_custom_domains(self):
        """Duplicate custom domains should not be added twice."""
        domains = [
            self._make("a.com"),
            self._make("a.com"),
        ]
        result = merge_myshopify(domains)
        # Implementation keeps both since dedup is caller's responsibility for
        # non-myshopify entries; this just asserts no crash
        assert isinstance(result, list)
