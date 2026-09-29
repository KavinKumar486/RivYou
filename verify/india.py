"""
India verifier — production version.

Signal categories:

  BL  (Business-Location)  — hard evidence the business operates from India
      gstin         valid GSTIN pattern (2-digit state code + PAN format)
      pin_code      6-digit India Post PIN in address context
      address       city/state name near address/office/registered keyword
      company_reg   CIN / LLPIN pattern

  BL_SOFT — weaker location signal; needs corroboration
      phone_91      +91 number on contact or footer page

  IC  (India-Commerce) — the business trades in/from India
      currency_inr  store currency is INR / ₹
      upi_cod       UPI, COD, or BharatPe references
      indian_gw     Razorpay, Cashfree, PayU, Juspay, Paytm
      indian_ship   Shiprocket, Delhivery, BlueDart, Delhivery, DTDC
      made_in_india "Made in India" / "Proudly Indian" copy

  WEAK — never sufficient alone
      tld_in        .in / .co.in domain
      india_mention plain "India" text with no address context

  NEGATIVE — evidence against Indian operation
      foreign_address  non-Indian country in address context
      non_inr_currency explicit USD/GBP/EUR/AUD pricing

Verdict rule:
  verified     — >= 1 BL  AND (>= 1 IC  OR >= 2 BL)
                 india_support = "strong"  if >= 2 BL and >= 1 IC
                               = "moderate" otherwise
  needs_review — IC >= 2 with no BL; BL_SOFT only; any contradiction
  rejected     — no BL, < 2 IC, or NEGATIVE dominates

Pages checked: homepage + /pages/contact, /pages/about[-us], /pages/our-story,
               /policies/terms-of-service, /policies/privacy-policy
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import tldextract

if TYPE_CHECKING:
    from fetcher import Fetcher

# ── GSTIN ─────────────────────────────────────────────────────────────────────
# Format: 2-digit state code + 5-char PAN prefix + 4 digits + 1 char + Z + 1 char
_GSTIN_RE = re.compile(
    r'\b([0-3][0-9][A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b'
)
# Valid state codes 01–38 (plus a few UT codes up to 38)
_VALID_STATE_CODES = {f"{i:02d}" for i in range(1, 39)}

# CIN: U/L + 5 digits + state(2) + year(4) + PLC/LLC/FLC + 6 digits
_CIN_RE = re.compile(r'\b[UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b')

# ── PIN code ──────────────────────────────────────────────────────────────────
# 6-digit codes 100000–999999 in an address-like context
_PIN_RE = re.compile(
    r'(?:pin\s*(?:code)?|postal\s*code|zip)\s*[:\-]?\s*([1-9]\d{5})\b'
    r'|(?<=[,\s])([1-9]\d{5})\s*(?:,?\s*India\b)',
    re.IGNORECASE,
)

# ── Phone ─────────────────────────────────────────────────────────────────────
_PHONE_91_RE = re.compile(r'(?:\+91|0091)[\s\-]?\d{10}\b')

# ── INR / currency ────────────────────────────────────────────────────────────
_INR_RE = re.compile(r'₹|(?:Rs\.?\s*\d)|(?:\bINR\b)', re.IGNORECASE)
_FOREIGN_CCY_RE = re.compile(
    r'\b(?:USD|US\$|\$\s*\d|GBP|£|EUR|€|AUD|CAD)\b', re.IGNORECASE
)

# ── Commerce signals ──────────────────────────────────────────────────────────
_UPI_COD_RE = re.compile(
    r'\bupi\b|bharatpe|cash\s+on\s+delivery|\bcod\b(?!\s*[a-z]{3,})',
    re.IGNORECASE,
)
_INDIAN_GW_RE = re.compile(
    r'razorpay|cashfree|payu\b|juspay|paytm', re.IGNORECASE
)
_INDIAN_SHIP_RE = re.compile(
    r'shiprocket|delhivery|bluedart|ecom\s*express|shadowfax|dtdc|india\s*post',
    re.IGNORECASE,
)
_MADE_IN_INDIA_RE = re.compile(
    r'made\s+in\s+india|proudly\s+indian|brand\s+from\s+india',
    re.IGNORECASE,
)

# ── Address indicators ────────────────────────────────────────────────────────
_ADDR_CONTEXT_RE = re.compile(
    r'\b(?:address|office|registered|located|headquarter|regd\.?\s*office)\b',
    re.IGNORECASE,
)
_INDIAN_CITIES = re.compile(
    r'\b(?:new\s+delhi|delhi|mumbai|bangalore|bengaluru|chennai|hyderabad'
    r'|kolkata|pune|ahmedabad|jaipur|lucknow|surat|vadodara|bhopal'
    r'|indore|nagpur|coimbatore|kochi|gurgaon|gurugram|noida'
    r'|ghaziabad|faridabad|chandigarh|dehradun|patna|ranchi)\b',
    re.IGNORECASE,
)
_INDIAN_STATES = re.compile(
    r'\b(?:gujarat|maharashtra|karnataka|tamil\s+nadu|telangana'
    r'|rajasthan|uttar\s+pradesh|west\s+bengal|kerala|haryana'
    r'|madhya\s+pradesh|andhra\s+pradesh|punjab|bihar|odisha'
    r'|jharkhand|uttarakhand|himachal\s+pradesh|assam|chhattisgarh)\b',
    re.IGNORECASE,
)
_FOREIGN_COUNTRY_RE = re.compile(
    r'\b(?:united\s+states|united\s+kingdom|australia|canada|singapore'
    r'|germany|france|netherlands|japan|china|hong\s+kong|dubai|uae'
    r'|\busa\b|\buk\b|\bau\b)\b',
    re.IGNORECASE,
)

# Pages to scrape for India signals
_PAGES = [
    "",
    "/pages/contact",
    "/pages/contact-us",
    "/pages/about",
    "/pages/about-us",
    "/pages/our-story",
    "/policies/terms-of-service",
    "/policies/privacy-policy",
    "/policies/shipping-policy",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_pin(text: str) -> str | None:
    for m in _PIN_RE.finditer(text):
        pin = m.group(1) or m.group(2)
        if pin:
            return pin
    return None


def _valid_gstin(gstin: str) -> bool:
    return gstin[:2] in _VALID_STATE_CODES


def _has_addr_context(text: str, radius: int = 300) -> bool:
    """Return True if an address-context keyword appears anywhere in *text*."""
    return bool(_ADDR_CONTEXT_RE.search(text))


# ── public API ────────────────────────────────────────────────────────────────

async def verify(fetcher: "Fetcher", domain: str) -> dict:
    """
    Verify whether *domain* is an Indian business.

    Returns::

        {
            "domain":         str,
            "verdict":        "verified" | "needs_review" | "rejected",
            "india_support":  "strong" | "moderate" | "none",
            "signals":        {"BL": [...], "BL_soft": [...], "IC": [...],
                               "weak": [...], "negative": [...]},
            "evidence":       [{"type", "value", "source_url", "method"}, ...],
        }
    """
    domain = domain.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]

    base = f"https://{domain}"

    signals: dict[str, list[str]] = {
        "BL": [], "BL_soft": [], "IC": [], "weak": [], "negative": []
    }
    evidence: list[dict] = []

    def _ev(typ: str, value: str, source_url: str, method: str) -> None:
        evidence.append({"type": typ, "value": value,
                         "source_url": source_url, "method": method})

    # ── Gather HTML from all pages ────────────────────────────────────────
    combined_html = ""
    page_html: dict[str, str] = {}   # url → body

    for path in _PAGES:
        url = f"{base}{path}"
        resp = await fetcher.fetch(url)
        if resp and resp.get("status") == 200:
            body = resp.get("body", "")
            page_html[url] = body
            combined_html += "\n" + body

    if not combined_html.strip():
        return {
            "domain": domain, "verdict": "rejected",
            "india_support": "none", "signals": signals, "evidence": evidence,
        }

    # ── BL signals ────────────────────────────────────────────────────────

    # GSTIN
    for url, html in page_html.items():
        for m in _GSTIN_RE.finditer(html):
            gstin = m.group(1)
            if _valid_gstin(gstin) and "gstin" not in [s.split(":")[0] for s in signals["BL"]]:
                signals["BL"].append(f"gstin:{gstin}")
                _ev("BL", f"gstin:{gstin}", url, "html_regex")

    # CIN
    for url, html in page_html.items():
        for m in _CIN_RE.finditer(html):
            if "cin" not in [s.split(":")[0] for s in signals["BL"]]:
                signals["BL"].append(f"cin:{m.group(0)}")
                _ev("BL", f"cin:{m.group(0)}", url, "html_regex")

    # PIN code
    for url, html in page_html.items():
        pin = _extract_pin(html)
        if pin and "pin_code" not in [s.split(":")[0] for s in signals["BL"]]:
            signals["BL"].append(f"pin_code:{pin}")
            _ev("BL", f"pin_code:{pin}", url, "html_regex")

    # Indian address — city or state name in address context
    for url, html in page_html.items():
        if _has_addr_context(html):
            city_m = _INDIAN_CITIES.search(html)
            state_m = _INDIAN_STATES.search(html)
            hit = city_m or state_m
            if hit and "address" not in [s.split(":")[0] for s in signals["BL"]]:
                signals["BL"].append(f"address:{hit.group(0).lower()}")
                _ev("BL", f"address:{hit.group(0).lower()}", url, "html_parse")

    # BL_SOFT — +91 phone
    for url, html in page_html.items():
        m = _PHONE_91_RE.search(html)
        if m and not signals["BL_soft"]:
            signals["BL_soft"].append(f"phone_91:{m.group(0)}")
            _ev("BL_soft", f"phone_91:{m.group(0)}", url, "html_regex")

    # ── IC signals ────────────────────────────────────────────────────────
    for url, html in page_html.items():
        if _INR_RE.search(html) and "currency_inr" not in signals["IC"]:
            signals["IC"].append("currency_inr")
            _ev("IC", "currency_inr", url, "html_regex")

        if _UPI_COD_RE.search(html) and "upi_cod" not in signals["IC"]:
            signals["IC"].append("upi_cod")
            _ev("IC", "upi_cod", url, "html_regex")

        if _INDIAN_GW_RE.search(html) and "indian_gateway" not in signals["IC"]:
            signals["IC"].append("indian_gateway")
            _ev("IC", "indian_gateway", url, "html_regex")

        if _INDIAN_SHIP_RE.search(html) and "indian_shipping" not in signals["IC"]:
            signals["IC"].append("indian_shipping")
            _ev("IC", "indian_shipping", url, "html_regex")

        if _MADE_IN_INDIA_RE.search(html) and "made_in_india" not in signals["IC"]:
            signals["IC"].append("made_in_india")
            _ev("IC", "made_in_india", url, "html_regex")

    # ── Weak signals ──────────────────────────────────────────────────────
    ext = tldextract.extract(domain)
    if ext.suffix in ("in", "co.in"):
        signals["weak"].append("tld_in")
        _ev("weak", "tld_in", base, "domain_suffix")

    # ── Negative signals ──────────────────────────────────────────────────
    for url, html in page_html.items():
        if _has_addr_context(html):
            if _FOREIGN_COUNTRY_RE.search(html):
                signals["negative"].append("foreign_address")
                _ev("negative", "foreign_address", url, "html_parse")
                break

    for url, html in page_html.items():
        if _FOREIGN_CCY_RE.search(html) and not _INR_RE.search(html):
            signals["negative"].append("non_inr_currency")
            _ev("negative", "non_inr_currency", url, "html_regex")
            break

    # ── Verdict ───────────────────────────────────────────────────────────
    bl  = len(signals["BL"])
    bls = len(signals["BL_soft"])
    ic  = len(signals["IC"])
    neg = len(signals["negative"])

    # Promote BL_soft to BL when there is corroborating IC (>=2) or another BL
    effective_bl = bl + (bls if (bl >= 1 or ic >= 2) else 0)

    contradiction = (
        "foreign_address" in signals["negative"] and bl >= 1
    )

    if contradiction:
        verdict = "needs_review"
        india_support = "none"
    elif neg > 0 and effective_bl == 0 and ic < 2:
        verdict = "rejected"
        india_support = "none"
    elif effective_bl >= 1 and (ic >= 1 or effective_bl >= 2):
        verdict = "verified"
        india_support = "strong" if (bl >= 2 and ic >= 1) else "moderate"
    elif ic >= 2 and bl == 0:
        verdict = "needs_review"
        india_support = "none"
    elif bls >= 1 and bl == 0:
        verdict = "needs_review"
        india_support = "none"
    else:
        verdict = "rejected"
        india_support = "none"

    return {
        "domain":        domain,
        "verdict":       verdict,
        "india_support": india_support,
        "signals":       signals,
        "evidence":      evidence,
    }
