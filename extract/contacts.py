"""
Contacts extractor.

Extracts email addresses and phone numbers from store pages.

Email:
  - href="mailto:..." anchors (primary)
  - regex fallback across visible text
  - Junk domains dropped: sentry.io, example.com, wixpress.com, sentry-cdn.com,
    shopify.com, googletagmanager.com, etc.

Phone:
  - href="tel:..." anchors (primary)
  - +91 / 0091 / 10-digit bare Indian number regex fallback
  - Normalised to +91XXXXXXXXXX form where country code is detectable

Returns:
    list of {"type": "email"|"phone", "value": str, "source_url": str, "method": str}
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

# ── junk email domains ────────────────────────────────────────────────────────
_JUNK_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "example.com", "example.org", "example.net",
    "sentry.io", "sentry-cdn.com",
    "wixpress.com", "wix.com",
    "shopify.com", "myshopify.com", "shopifyemail.com",
    "googletagmanager.com", "google.com", "gmail.com",
    "mailchimp.com", "klaviyo.com", "omnisend.com",
    "domain.com", "yourdomain.com", "email.com",
    "acme.com", "test.com",
})

# ── regexes ───────────────────────────────────────────────────────────────────
_MAILTO_RE    = re.compile(r'href=["\']mailto:([^"\'?\s]+)', re.IGNORECASE)
_TEL_RE       = re.compile(r'href=["\']tel:([^"\'?\s]+)',    re.IGNORECASE)
_EMAIL_RE     = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)
_PHONE_IN_RE  = re.compile(
    r'(?:\+91|0091)[\s\-]?(\d{5}[\s\-]?\d{5})'   # +91 / 0091
    r'|\b([6-9]\d{9})\b'                           # bare 10-digit mobile
)

_PAGES = [
    "",
    "/pages/contact",
    "/pages/contact-us",
    "/pages/about",
    "/pages/about-us",
]


def _clean_email(raw: str) -> str | None:
    raw = raw.strip().lower()
    if "@" not in raw:
        return None
    domain = raw.split("@", 1)[1].split("?")[0].split(">")[0]
    if domain in _JUNK_EMAIL_DOMAINS:
        return None
    if not re.match(r'^[a-z0-9.\-]+\.[a-z]{2,}$', domain):
        return None
    return raw.split("?")[0]


def _clean_phone(raw: str) -> str | None:
    digits = re.sub(r'[\s\-\(\)]', '', raw)
    if digits.startswith("0091"):
        digits = "+91" + digits[4:]
    elif digits.startswith("+91"):
        pass
    elif len(digits) == 10 and digits[0] in "6789":
        digits = "+91" + digits
    else:
        return None
    if len(digits) != 13:
        return None
    return digits


async def extract(fetcher: "Fetcher", domain: str) -> list[dict]:
    """Return contact evidence list for *domain*."""
    base = f"https://{domain}"
    emails: dict[str, str] = {}   # value → source_url
    phones: dict[str, str] = {}

    for path in _PAGES:
        url = f"{base}{path}"
        resp = await fetcher.fetch(url)
        if not (resp and resp.get("status") == 200):
            continue
        html = resp.get("body", "")
        src  = resp.get("url", url)

        # mailto: hrefs
        for m in _MAILTO_RE.finditer(html):
            email = _clean_email(m.group(1))
            if email and email not in emails:
                emails[email] = src

        # tel: hrefs
        for m in _TEL_RE.finditer(html):
            phone = _clean_phone(m.group(1))
            if phone and phone not in phones:
                phones[phone] = src

        # email regex fallback (only if no mailto found yet)
        if not emails:
            for m in _EMAIL_RE.finditer(html):
                email = _clean_email(m.group(0))
                if email and email not in emails:
                    emails[email] = src

        # phone regex fallback
        if not phones:
            for m in _PHONE_IN_RE.finditer(html):
                raw = (m.group(1) or m.group(2) or "").replace(" ", "").replace("-", "")
                if m.group(1):
                    raw = "+91" + raw
                phone = _clean_phone(raw)
                if phone and phone not in phones:
                    phones[phone] = src

    result: list[dict] = []
    for val, src in emails.items():
        result.append({"type": "email", "value": val, "source_url": src, "method": "mailto_href"})
    for val, src in phones.items():
        result.append({"type": "phone", "value": val, "source_url": src, "method": "tel_href"})
    return result
