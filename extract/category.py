"""
Category extractor.

Maps a store to one of 12 taxonomy buckets using a chain of signals:
  1. Shopify product_type / tags  (from /products.json)
  2. Collection titles            (from /collections.json)
  3. Product titles               (from /products.json)
  4. Navigation link text         (homepage <nav> / <header>)
  5. JSON-LD @type Product / offers

Taxonomy buckets (12 + Other):
  Fashion & Apparel
  Beauty & Personal Care
  Food & Beverage
  Home & Decor
  Jewellery & Accessories
  Health & Wellness
  Electronics & Audio
  Pet
  Baby & Kids
  Sports & Fitness
  Books & Stationery
  Other

Returns:
    {"value": bucket, "source_url": str, "method": str}  or None
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fetcher import Fetcher

# ── taxonomy keyword map ──────────────────────────────────────────────────────
_TAXONOMY: list[tuple[str, list[str]]] = [
    ("Fashion & Apparel", [
        "apparel", "fashion", "clothing", "clothes", "shirt", "tshirt", "t-shirt",
        "kurta", "saree", "sari", "dress", "jeans", "trouser", "pant", "top",
        "jacket", "hoodie", "sweatshirt", "ethnic", "wear", "outfit", "footwear",
        "shoe", "sneaker", "sandal", "bag", "handbag", "wallet", "accessories",
        "watch", "sunglasses", "belt", "cap", "hat",
    ]),
    ("Beauty & Personal Care", [
        "beauty", "skincare", "skin care", "haircare", "hair care", "cosmetics",
        "makeup", "serum", "moisturizer", "moisturiser", "sunscreen", "spf",
        "face wash", "shampoo", "conditioner", "body wash", "perfume", "fragrance",
        "lipstick", "foundation", "toner", "cleanser", "grooming", "beard",
        "personal care", "wellness", "ayurved",
    ]),
    ("Food & Beverage", [
        "food", "snack", "beverage", "drink", "tea", "coffee", "juice", "water",
        "protein bar", "granola", "muesli", "nutrition bar", "chocolate", "candy",
        "spice", "masala", "ghee", "honey", "jam", "sauce", "pickle", "chutney",
        "rice", "dal", "lentil", "flour", "organic food", "dry fruit", "nut",
    ]),
    ("Home & Decor", [
        "home", "decor", "furniture", "mattress", "pillow", "bedding", "curtain",
        "sofa", "table", "chair", "lamp", "candle", "plant", "pot", "garden",
        "kitchen", "cookware", "utensil", "storage", "organizer", "frame",
        "artwork", "painting", "rug", "carpet", "wall art", "living",
    ]),
    ("Jewellery & Accessories", [
        "jewellery", "jewelry", "ring", "necklace", "bracelet", "earring",
        "pendant", "chain", "bangle", "anklet", "gold", "silver", "diamond",
        "gemstone", "stone", "pearl", "mangalsutra",
    ]),
    ("Health & Wellness", [
        "health", "supplement", "vitamin", "protein", "whey", "probiotic",
        "immunity", "ayurvedic", "herbal", "medicine", "fitness supplement",
        "omega", "collagen", "biotin", "detox", "weight loss", "weight gain",
        "nutraceutical", "pharmacy",
    ]),
    ("Electronics & Audio", [
        "electronic", "audio", "earphone", "headphone", "speaker", "smartwatch",
        "watch", "gadget", "cable", "charger", "power bank", "mobile accessory",
        "laptop", "computer", "camera", "tech", "device", "wireless",
    ]),
    ("Pet", [
        "pet", "dog", "cat", "bird", "fish", "puppy", "kitten", "paw",
        "treat", "leash", "collar", "kennel", "aquarium",
    ]),
    ("Baby & Kids", [
        "baby", "kids", "children", "child", "toddler", "infant", "newborn",
        "diaper", "nappy", "toy", "nursery", "stroller", "pram", "feeding",
        "school", "backpack", "pencil", "crayon", "playmat",
    ]),
    ("Sports & Fitness", [
        "sport", "fitness", "gym", "yoga", "cycle", "cycling", "running",
        "cricket", "football", "badminton", "tennis", "swim", "outdoor",
        "activewear", "track", "athletic",
    ]),
    ("Books & Stationery", [
        "book", "stationery", "pen", "notebook", "diary", "planner",
        "art supply", "craft", "journal", "comic", "manga", "novel",
    ]),
]

_NAV_RE    = re.compile(r'<(?:nav|header)[^>]*>(.*?)</(?:nav|header)>',
                         re.DOTALL | re.IGNORECASE)
_LINK_TEXT = re.compile(r'<a[^>]*>([^<]{2,40})</a>', re.IGNORECASE)


def _score(text: str) -> tuple[str, int] | None:
    """Return (best_bucket, score) or None if nothing matches."""
    lower = text.lower()
    best_bucket, best_score = None, 0
    for bucket, keywords in _TAXONOMY:
        score = sum(1 for kw in keywords if kw in lower)
        if score > best_score:
            best_score = score
            best_bucket = bucket
    return (best_bucket, best_score) if best_bucket else None


async def extract(fetcher: "Fetcher", domain: str) -> dict | None:
    """
    Return {"value": bucket, "source_url": str, "method": str} or None.
    """
    base = f"https://{domain}"
    candidates: list[tuple[str, str, str]] = []   # (text_blob, source_url, method)

    # 1 + 3. /products.json — product_type, tags, titles
    prod_url = f"{base}/products.json?limit=20"
    resp = await fetcher.fetch(prod_url)
    if resp and resp.get("status") == 200:
        try:
            data = json.loads(resp["body"])
            parts: list[str] = []
            for p in data.get("products", []):
                parts.append(p.get("product_type", ""))
                parts.extend(p.get("tags", []))
                parts.append(p.get("title", ""))
            blob = " ".join(parts)
            candidates.append((blob, resp.get("url", prod_url), "product_type_tags"))
        except Exception:
            pass

    # 2. /collections.json — collection titles
    coll_url = f"{base}/collections.json"
    resp = await fetcher.fetch(coll_url)
    if resp and resp.get("status") == 200:
        try:
            data = json.loads(resp["body"])
            titles = " ".join(c.get("title", "") for c in data.get("collections", []))
            if titles:
                candidates.append((titles, resp.get("url", coll_url), "collection_titles"))
        except Exception:
            pass

    # 4. Homepage navigation text
    home_resp = await fetcher.fetch(base)
    if home_resp and home_resp.get("status") == 200:
        html = home_resp.get("body", "")
        src  = home_resp.get("url", base)
        nav_text = " ".join(m.group(1) for m in _LINK_TEXT.finditer(
            " ".join(nm.group(1) for nm in _NAV_RE.finditer(html))
        ))
        if nav_text:
            candidates.append((nav_text, src, "navigation_text"))
        # Also try full page title + meta description as lightweight fallback
        title_m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if title_m:
            candidates.append((title_m.group(1), src, "page_title"))

    # Score each candidate; take the best
    best_bucket, best_score, best_src, best_method = None, 0, base, "page_title"
    for blob, src, method in candidates:
        result = _score(blob)
        if result and result[1] > best_score:
            best_bucket, best_score = result
            best_src, best_method = src, method

    if not best_bucket:
        return {"value": "Other", "source_url": base, "method": "default"}

    return {"value": best_bucket, "source_url": best_src, "method": best_method}
