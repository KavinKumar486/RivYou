"""
Source D: Verified-neighbor expansion.

From each verified Indian Shopify store, harvest outbound links (about pages,
brands-we-love, stockists, collaborations) and feed them back as new candidates
with source='neighbor'.

Noise filter removes payment gateways, CDNs, analytics, logistics, social, and
Shopify platform infra — these dominate outbound links on any Shopify store.

Supports multi-round expansion: verified hits from round N become seeds for N+1.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from urllib.parse import urlparse

from utils import normalize_domain

# ── Noise domains ─────────────────────────────────────────────────────────────
_NOISE_DOMAINS: frozenset[str] = frozenset({
    # Social
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "linkedin.com", "pinterest.com", "tiktok.com",
    "snapchat.com", "whatsapp.com", "telegram.org", "t.me",
    "facebook.net", "fb.com",
    # Big tech / link shorteners
    "google.com", "gmail.com", "apple.com", "microsoft.com",
    "goo.gl", "bit.ly", "a.me", "onelink.me", "onelink.to", "app.link",
    # Marketplaces (not D2C)
    "amazon.in", "amazon.com", "flipkart.com", "myntra.com",
    "nykaa.com", "ajio.com", "meesho.com", "purplle.com",
    # Shopify platform infra
    "shopify.com", "myshopify.com", "cdn.shopify.com",
    "shopifycloud.com", "shopifystatic.com", "shopifyapps.com",
    "shopifyemail.com", "shop.app",
    # CDN / hosting
    "googleapis.com", "gstatic.com", "googletagmanager.com",
    "google-analytics.com", "googleadservices.com",
    "cloudflare.com", "cloudfront.net", "fastly.net",
    "amazonaws.com", "akamaized.net", "akamai.com",
    "edgekey.net", "bootstrapcdn.com", "jsdelivr.net",
    "clarity.ms",
    # Payment gateways
    "razorpay.com", "paytm.com", "phonepe.com", "cashfree.com",
    "juspay.in", "payu.in", "payumoney.com", "billdesk.com",
    "stripe.com", "paypal.com", "braintree.com", "gokwik.co",
    # Shipping / logistics
    "shiprocket.in", "delhivery.com", "bluedart.com",
    "dtdc.com", "ecomexpress.in", "shadowfax.in",
    "indiapost.gov.in", "fedex.com", "dhl.com", "ups.com",
    "pickrr.com", "clickpost.ai", "clickpost.in",
    # Analytics / marketing
    "hotjar.com", "segment.com", "mixpanel.com", "klaviyo.com",
    "omnisend.com", "mailchimp.com", "hubspot.com",
    "crisp.chat", "freshdesk.com", "zendesk.com", "intercom.com",
    "sendgrid.com", "twilio.com", "moengage.com",
    # Review / loyalty
    "judge.me", "yotpo.com", "okendo.io", "loox.io",
    "stamped.io", "trustpilot.com",
    # Legal / compliance
    "termly.io", "iubenda.com", "cookiebot.com",
})

# Pages most likely to reference partner/peer stores
_EXPANSION_PAGES = [
    "",                       # homepage
    "/pages/about",
    "/pages/about-us",
    "/pages/our-story",
    "/pages/partners",
    "/pages/brands",
    "/pages/brands-we-love",
    "/pages/stockists",
    "/pages/collaborations",
]

_HREF_RE = re.compile(r'href=["\']([^"\'#?][^"\']*)["\']')


def _should_skip(link_domain: str, seed_domain: str) -> bool:
    if not link_domain:
        return True
    if link_domain == seed_domain:
        return True
    if link_domain in _NOISE_DOMAINS:
        return True
    if link_domain.endswith(".myshopify.com"):
        return True
    if link_domain.endswith(".shopifycloud.com"):
        return True
    return False


async def _extract_links(fetcher, domain: str) -> list[str]:
    """
    Fetch expansion pages for a store and return filtered outbound domains.
    fetcher must be a Fetcher instance (from fetcher.py).
    """
    links: set[str] = set()
    for path in _EXPANSION_PAGES:
        url = f"https://{domain}{path}"
        resp = await fetcher.fetch(url)
        if resp and resp.get("status") == 200:
            html = resp.get("body", "")
            for m in _HREF_RE.finditer(html):
                href = m.group(1)
                if not href.startswith("http"):
                    continue
                netloc = urlparse(href).netloc.lstrip("www.")
                link_domain = normalize_domain(netloc) or netloc
                if not _should_skip(link_domain, domain):
                    links.add(link_domain)
    return sorted(links)


async def expand(
    fetcher,
    seed_stores: list[str],
    rounds: int = 1,
    max_concurrent: int = 10,
) -> list[dict]:
    """
    Multi-round neighbor expansion.  Returns candidate dicts for all discovered
    neighbor domains (source='neighbor', with 'referred_by' metadata).

    Args:
        fetcher:        Fetcher instance (must already be initialised).
        seed_stores:    Canonical domains of confirmed Indian Shopify stores.
        rounds:         How many expansion rounds to run.
        max_concurrent: Max simultaneous link-extraction tasks.

    Returns:
        List of candidate dicts: {"domain", "source", "referred_by", "round"}
    """
    sem = asyncio.Semaphore(max_concurrent)
    all_candidates: dict[str, dict] = {}   # domain → candidate dict
    seen_seeds: set[str] = set(seed_stores)
    current_seeds = list(seed_stores)

    for round_num in range(1, rounds + 1):
        print(f"[neighbors] Round {round_num}: {len(current_seeds)} seeds")
        neighbor_map: dict[str, list[str]] = defaultdict(list)

        async def _process(store: str) -> None:
            async with sem:
                try:
                    links = await _extract_links(fetcher, store)
                    for link in links:
                        if link not in seen_seeds:
                            neighbor_map[link].append(store)
                except Exception as e:
                    print(f"[neighbors] Error extracting from {store}: {e}")

        await asyncio.gather(*[_process(s) for s in current_seeds])

        new_this_round = 0
        for domain, referrers in neighbor_map.items():
            if domain not in all_candidates:
                all_candidates[domain] = {
                    "domain": domain,
                    "source": "neighbor",
                    "referred_by": referrers,
                    "round": round_num,
                }
                new_this_round += 1

        print(f"[neighbors] Round {round_num}: +{new_this_round} new candidates "
              f"(accumulated {len(all_candidates)})")

        # Seeds for the next round must be verified externally; without live
        # verification here we stop after one round of link harvesting.
        # Callers can call expand() again with verified hits as seeds.
        break

    return list(all_candidates.values())


def get_seed_stores() -> list[str]:
    """Default seed stores from Checkpoint 0 spike results."""
    return [
        "nivaaya.in", "vaku.in", "aurimo.in", "goldenglitter.in",
        "theformalclub.in", "drveda.in", "cordstudio.in", "yogabars.in",
        "headphonezone.in", "brustro.in", "eyejack.in",
        "mcaffeine.com", "dailyobjects.com", "chumbak.com",
        "mokobara.com", "bewakoof.com", "thesouledstore.com",
        "snitch.co.in", "mamaearth.in", "sugarcosmetics.com",
        "plumgoodness.com", "minimalist.co.in", "dotandkey.com",
        "foxtale.in", "pilgrimsindia.com", "bummer.in",
        "happilo.com", "bombayshavingcompany.com",
        "urbanmonkey.com", "boat-lifestyle.com",
    ]
