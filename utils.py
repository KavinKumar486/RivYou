"""
Shared utilities for the Rivyou pipeline.
Handles domain normalization, myshopify→custom-domain merge, and TLD helpers.
"""

import re
import tldextract

# Compiled once — myshopify subdomain pattern
_MYSHOPIFY_RE = re.compile(r'^([a-z0-9][a-z0-9\-]*)\.myshopify\.com$', re.IGNORECASE)


def registrable_domain(domain: str) -> str:
    """
    Return the registrable domain (e.g. 'example.co.in') for any input,
    stripping scheme, path, port, and www prefix.

    Returns empty string if the input has no registrable portion (e.g. bare IPs).
    """
    # Strip scheme
    domain = domain.strip()
    if "://" in domain:
        domain = domain.split("://", 1)[1]
    # Strip path/query/port
    domain = domain.split("/")[0].split("?")[0].split("#")[0].split(":")[0]

    ext = tldextract.extract(domain)
    # Use non-deprecated API when available
    if hasattr(ext, "top_domain_under_public_suffix"):
        return (ext.top_domain_under_public_suffix or "").lower()
    return (ext.registered_domain or "").lower()


def get_suffix(domain: str) -> str:
    """Return the public suffix (TLD) for a domain, e.g. 'co.in', 'com'."""
    ext = tldextract.extract(domain)
    return ext.suffix or ""


def normalize_domain(domain: str) -> str:
    """
    Canonical form of a domain for dedup and storage:
      - Lowercase
      - Strip scheme, path, port
      - Strip leading 'www.' (one level only)
      - Returns the registrable domain (e.g. 'example.co.in')

    Returns empty string for invalid / unresolvable inputs.
    """
    reg = registrable_domain(domain)
    if not reg:
        return ""
    # Strip www. prefix (tldextract already drops subdomains, but be explicit)
    if reg.startswith("www."):
        reg = reg[4:]
    return reg


def is_myshopify(domain: str) -> bool:
    """Return True if domain is a *.myshopify.com subdomain."""
    return bool(_MYSHOPIFY_RE.match(domain.lower().strip()))


def myshopify_slug(domain: str) -> str | None:
    """
    Return the slug portion of a myshopify.com domain, or None.
    e.g. 'acme-store.myshopify.com' → 'acme-store'
    """
    m = _MYSHOPIFY_RE.match(domain.lower().strip())
    return m.group(1) if m else None


def merge_myshopify(domains: list[dict], custom_map: dict[str, str] | None = None) -> list[dict]:
    """
    Merge *.myshopify.com entries with their custom domain equivalents.

    Algorithm:
      1. Walk all records. Any custom domain whose homepage redirects to (or
         whose HTML contains) a matching *.myshopify.com becomes the canonical.
      2. When a myshopify entry and a custom-domain entry share the same slug,
         keep the CUSTOM domain as canonical and attach the myshopify subdomain
         as metadata.
      3. If no custom_map entry exists, the myshopify domain is kept as-is.

    Args:
        domains: list of dicts with at least a 'domain' key.
        custom_map: optional pre-built {slug: custom_domain} mapping from live
                    redirect checks.  When None, only static slug matching is done.

    Returns a deduplicated list where myshopify domains are merged into their
    custom-domain counterpart wherever possible.
    """
    custom_map = custom_map or {}

    # Index all non-myshopify domains by registrable_domain for fast lookup
    custom_by_reg: dict[str, dict] = {}
    myshopify_entries: list[dict] = []
    out: list[dict] = []

    for entry in domains:
        d = entry.get("domain", "").lower().strip()
        if is_myshopify(d):
            myshopify_entries.append(entry)
        else:
            reg = normalize_domain(d) or d
            if reg not in custom_by_reg:
                custom_by_reg[reg] = entry
            out.append(entry)

    # Try to merge each myshopify entry
    for entry in myshopify_entries:
        d = entry["domain"].lower().strip()
        slug = myshopify_slug(d)

        # Check explicit custom_map first
        custom = custom_map.get(slug) if slug else None
        if custom:
            reg = normalize_domain(custom) or custom
            if reg in custom_by_reg:
                # Already have it — annotate with myshopify origin
                existing = custom_by_reg[reg]
                existing.setdefault("myshopify_domain", d)
            else:
                # Add the custom domain as canonical, carrying source metadata
                merged = dict(entry)
                merged["domain"] = reg
                merged["myshopify_domain"] = d
                out.append(merged)
                custom_by_reg[reg] = merged
        else:
            # No custom domain known — keep myshopify as canonical for now
            if d not in {e["domain"] for e in out}:
                out.append(entry)

    return out
