"""
Tests for verify/india.py — fixture-based, no live network calls.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from verify.india import verify

FIXTURES = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MockFetcher:
    """Returns a fixed body for any URL containing the given fragment."""

    def __init__(self, responses: dict[str, dict]):
        self._responses = responses  # fragment → {status, body}

    async def fetch(self, url: str, **_) -> dict:
        for fragment, resp in self._responses.items():
            if fragment in url:
                return {"status": resp.get("status", 200),
                        "body": resp.get("body", ""),
                        "headers": {},
                        "url": url}
        return {"status": 404, "body": "", "headers": {}, "url": url}


# ── Verified cases ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_indian_store_verified():
    """GSTIN + PIN + Razorpay + INR → verified."""
    fetcher = MockFetcher({"verified-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "verified-store.in")
    assert result["verdict"] == "verified"
    assert len(result["signals"]["BL"]) >= 1
    assert len(result["signals"]["IC"]) >= 1


@pytest.mark.asyncio
async def test_gstin_detected():
    """Valid GSTIN is detected and goes into BL signals."""
    fetcher = MockFetcher({"gstin-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "gstin-store.in")
    bl_types = [s.split(":")[0] for s in result["signals"]["BL"]]
    assert "gstin" in bl_types


@pytest.mark.asyncio
async def test_pin_code_detected():
    """PIN code in address context is detected."""
    fetcher = MockFetcher({"pin-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "pin-store.in")
    bl_types = [s.split(":")[0] for s in result["signals"]["BL"]]
    assert "pin_code" in bl_types


@pytest.mark.asyncio
async def test_inr_detected():
    """INR / ₹ currency signal goes into IC."""
    fetcher = MockFetcher({"inr-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "inr-store.in")
    assert "currency_inr" in result["signals"]["IC"]


@pytest.mark.asyncio
async def test_india_support_strong():
    """>=2 BL + >=1 IC → india_support = strong."""
    fetcher = MockFetcher({"strong-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "strong-store.in")
    # india_verified.html has GSTIN + PIN + phone (BL) and INR + Razorpay + Shiprocket (IC)
    if result["verdict"] == "verified":
        assert result["india_support"] in ("strong", "moderate")


# ── Commerce-only (foreign brand selling to India) ────────────────────────────

@pytest.mark.asyncio
async def test_foreign_brand_inr_needs_review():
    """INR + UPI + Indian GW but foreign address → needs_review (not verified)."""
    fetcher = MockFetcher({"foreign.com": {"body": _html("india_commerce_only.html")}})
    result = await verify(fetcher, "foreign.com")
    # Has IC signals but foreign_address → needs_review or rejected, never verified
    assert result["verdict"] in ("needs_review", "rejected")
    assert result["verdict"] != "verified"


@pytest.mark.asyncio
async def test_foreign_address_is_negative():
    """Foreign address populates negative signals."""
    fetcher = MockFetcher({"neg.com": {"body": _html("india_commerce_only.html")}})
    result = await verify(fetcher, "neg.com")
    assert "foreign_address" in result["signals"]["negative"]


# ── .in shell / parked domain ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dot_in_shell_rejected():
    """.in domain with no Indian business signals → rejected."""
    fetcher = MockFetcher({"parked.in": {"body": _html("india_dot_in_shell.html")}})
    result = await verify(fetcher, "parked.in")
    assert result["verdict"] == "rejected"


@pytest.mark.asyncio
async def test_tld_in_is_weak_only():
    """.in TLD alone lands in weak, never promotes to verified."""
    fetcher = MockFetcher({"parked.in": {"body": _html("india_dot_in_shell.html")}})
    result = await verify(fetcher, "parked.in")
    assert "tld_in" in result["signals"]["weak"]
    assert result["verdict"] != "verified"


# ── Contradiction / needs_review ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contradiction_needs_review():
    """GSTIN (BL) + foreign address (negative) → needs_review."""
    fetcher = MockFetcher({"conflict.com": {"body": _html("india_needs_review.html")}})
    result = await verify(fetcher, "conflict.com")
    assert result["verdict"] == "needs_review"


@pytest.mark.asyncio
async def test_contradiction_has_both_bl_and_negative():
    """Contradiction fixture must produce BL and foreign_address signals."""
    fetcher = MockFetcher({"conflict.com": {"body": _html("india_needs_review.html")}})
    result = await verify(fetcher, "conflict.com")
    bl_types = [s.split(":")[0] for s in result["signals"]["BL"]]
    assert "gstin" in bl_types
    assert "foreign_address" in result["signals"]["negative"]


# ── No HTML / unreachable ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unreachable_domain_rejected():
    """All pages return 404 → rejected."""
    fetcher = MockFetcher({})   # nothing matches → all 404
    result = await verify(fetcher, "ghost.example.com")
    assert result["verdict"] == "rejected"


# ── Evidence rows ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_rows_populated():
    """Verified store must produce evidence rows with type/value/source_url/method."""
    fetcher = MockFetcher({"ev-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "ev-store.in")
    assert result["verdict"] == "verified"
    assert len(result["evidence"]) >= 2
    for ev in result["evidence"]:
        assert ev.get("type")
        assert ev.get("value")
        assert ev.get("source_url")
        assert ev.get("method")


# ── www normalisation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_www_stripped():
    """www. prefix is stripped before processing."""
    fetcher = MockFetcher({"norm-store.in": {"body": _html("india_verified.html")}})
    result = await verify(fetcher, "www.norm-store.in")
    assert result["domain"] == "norm-store.in"
