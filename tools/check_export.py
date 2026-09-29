"""
tools/check_export.py — validate the exported CSV for structural and data issues.

Usage:
    python tools/check_export.py data/output.csv [--check-urls 30]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


REQUIRED_COLS = {
    "domain", "category", "tagline", "logo_url",
    "state", "state_status", "extracted_at",
}

# Taglines so generic they add no signal
_GENERIC_TAGLINES = {
    "welcome", "welcome to our store", "home", "shop", "online store",
    "coming soon", "undefined", "null", "",
}

# PIN-prefix-only states where the 2-digit prefix is ambiguous
# These are documented; the verifier may still produce them.
_AMBIGUOUS_PIN_STATES = {
    # prefix 40-44 is Maharashtra; 30x is Goa shares 30 with Rajasthan edge
    "Goa",   # pin prefix 40x used by Mumbai suburbs AND Goa 403xxx
    # Northeast: 78x covers Assam/Meghalaya/Mizoram/Manipur/Nagaland/Arunachal/Tripura
    "Meghalaya", "Mizoram", "Manipur", "Nagaland", "Arunachal Pradesh",
    "Tripura", "Sikkim",
}

_URL_RE = re.compile(r'^https?://', re.IGNORECASE)


def check(csv_path: str, check_urls: int = 0) -> list[dict]:
    findings: list[dict] = []

    def issue(level, field, detail, domain=""):
        findings.append({"level": level, "field": field,
                          "detail": detail, "domain": domain})

    path = Path(csv_path)
    if not path.exists():
        issue("ERROR", "file", f"{csv_path} not found")
        return findings

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        issue("ERROR", "file", "empty CSV")
        return findings

    cols = set(rows[0].keys())
    for c in REQUIRED_COLS:
        if c not in cols:
            issue("ERROR", "schema", f"missing column: {c}")

    total = len(rows)
    stats: dict[str, int] = {
        "dupe_domain": 0, "blank_category": 0, "other_category": 0,
        "generic_tagline": 0, "relative_logo": 0,
        "blank_state": 0, "ambiguous_pin_state": 0,
        "blank_domain": 0,
    }
    seen_domains: set[str] = set()
    url_sample: list[tuple[str, str]] = []   # (domain, logo_url)

    for row in rows:
        domain = (row.get("domain") or "").strip()
        if not domain:
            stats["blank_domain"] += 1
            issue("ERROR", "domain", "blank domain row", domain)
            continue

        if domain in seen_domains:
            stats["dupe_domain"] += 1
            issue("ERROR", "domain", "duplicate domain", domain)
        seen_domains.add(domain)

        cat = (row.get("category") or "").strip()
        if not cat:
            stats["blank_category"] += 1
            issue("WARN", "category", "blank", domain)
        elif cat == "Other":
            stats["other_category"] += 1

        tag = (row.get("tagline") or "").strip().lower()
        if tag in _GENERIC_TAGLINES:
            stats["generic_tagline"] += 1
            issue("WARN", "tagline", f"generic: '{row.get('tagline','')}'", domain)

        logo = (row.get("logo_url") or "").strip()
        if logo and not _URL_RE.match(logo):
            stats["relative_logo"] += 1
            issue("ERROR", "logo_url", f"relative URL: {logo}", domain)
        if logo and check_urls and len(url_sample) < check_urls:
            url_sample.append((domain, logo))

        state = (row.get("state") or "").strip()
        st_status = (row.get("state_status") or "").strip()
        if not state and st_status != "unresolved":
            stats["blank_state"] += 1
            issue("WARN", "state", f"blank but status={st_status!r}", domain)
        st_method = (row.get("state_method") or "").strip()
        if state in _AMBIGUOUS_PIN_STATES and st_method == "pin_prefix":
            stats["ambiguous_pin_state"] += 1
            issue("WARN", "state", f"ambiguous PIN prefix → {state}", domain)

    # Summary findings
    issue("INFO", "summary", f"total rows: {total}")
    for k, v in stats.items():
        issue("INFO", f"stat_{k}", str(v))

    # Optional logo URL reachability
    if check_urls and url_sample:
        import httpx
        print(f"\nChecking {len(url_sample)} logo URLs …")
        for domain, logo_url in url_sample:
            try:
                r = httpx.head(logo_url, follow_redirects=True, timeout=10.0)
                if r.status_code >= 400:
                    issue("WARN", "logo_url", f"HTTP {r.status_code}", domain)
                else:
                    issue("OK", "logo_url", f"HTTP {r.status_code}", domain)
            except Exception as e:
                issue("WARN", "logo_url", f"fetch error: {e}", domain)

    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--check-urls", type=int, default=0,
                    help="HEAD-check this many logo URLs (0=skip)")
    args = ap.parse_args()

    findings = check(args.csv_path, args.check_urls)

    errors = [f for f in findings if f["level"] == "ERROR"]
    warns  = [f for f in findings if f["level"] == "WARN"]

    print(f"\n{'Level':<6}  {'Field':<20}  {'Domain':<30}  Detail")
    print("-" * 90)
    for f in findings:
        if f["level"] in ("ERROR", "WARN"):
            print(f"{f['level']:<6}  {f['field']:<20}  {f['domain']:<30}  {f['detail']}")

    print()
    for f in findings:
        if f["level"] == "INFO":
            print(f"  {f['field']}: {f['detail']}")

    print(f"\nSummary: {len(errors)} errors, {len(warns)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
