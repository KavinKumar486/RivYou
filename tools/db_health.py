"""
tools/db_health.py  — structural integrity check for rivyou.db

Usage:
    python tools/db_health.py --db data/rivyou.db

Exit 0  = all checks pass.
Exit 1  = at least one ERROR-level finding.
Prints a table of all findings regardless.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run(db_path: str) -> list[dict]:
    findings: list[dict] = []

    def ok(check, detail=""):
        findings.append({"level": "OK",    "check": check, "detail": detail})

    def warn(check, detail=""):
        findings.append({"level": "WARN",  "check": check, "detail": detail})

    def err(check, detail=""):
        findings.append({"level": "ERROR", "check": check, "detail": detail})

    if not Path(db_path).exists():
        err("db_exists", f"{db_path} not found")
        return findings

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # ── table existence ────────────────────────────────────────────────────
    expected_tables = {"candidates", "stores", "evidence", "fetch_cache",
                       "crawl_runs", "extracted"}
    existing = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for t in expected_tables:
        if t in existing:
            ok(f"table_{t}")
        else:
            err(f"table_{t}", "missing")

    # ── row counts ─────────────────────────────────────────────────────────
    for t in existing & expected_tables:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        ok(f"rowcount_{t}", str(n))

    # ── candidates: no null domain ─────────────────────────────────────────
    if "candidates" in existing:
        n = con.execute("SELECT COUNT(*) FROM candidates WHERE domain IS NULL OR domain=''").fetchone()[0]
        (err if n else ok)("candidates_no_null_domain", f"{n} null/empty")

    # ── candidates: no duplicate domains ──────────────────────────────────
    if "candidates" in existing:
        n = con.execute(
            "SELECT COUNT(*) FROM (SELECT domain FROM candidates GROUP BY domain HAVING COUNT(*)>1)"
        ).fetchone()[0]
        (err if n else ok)("candidates_no_dupe", f"{n} dupes")

    # ── stores: verdict column populated where not inconclusive ───────────
    if "stores" in existing:
        n = con.execute(
            "SELECT COUNT(*) FROM stores WHERE inconclusive=0 AND shopify_verdict IS NULL"
        ).fetchone()[0]
        (warn if n else ok)("stores_verdict_populated", f"{n} missing verdict")

    # ── stores: is_shopify consistent with verdict ─────────────────────────
    if "stores" in existing:
        n = con.execute(
            "SELECT COUNT(*) FROM stores "
            "WHERE shopify_verdict='verified' AND is_shopify!=1"
        ).fetchone()[0]
        (err if n else ok)("stores_shopify_consistent", f"{n} inconsistencies")

    # ── fetch_cache: no orphan body paths ─────────────────────────────────
    if "fetch_cache" in existing:
        missing_bodies = 0
        for row in con.execute(
            "SELECT body_path FROM fetch_cache WHERE body_path IS NOT NULL AND body_path!=''"
        ):
            if not Path(row[0]).exists():
                missing_bodies += 1
        (warn if missing_bodies else ok)(
            "fetch_cache_body_files", f"{missing_bodies} orphan paths")

    # ── extracted: logo_url relative URLs ─────────────────────────────────
    if "extracted" in existing:
        n = con.execute(
            "SELECT COUNT(*) FROM extracted "
            "WHERE logo_url IS NOT NULL AND logo_url!='' "
            "AND logo_url NOT LIKE 'http%'"
        ).fetchone()[0]
        (err if n else ok)("extracted_logo_absolute", f"{n} relative logo URLs")

    # ── evidence: valid JSON ───────────────────────────────────────────────
    if "evidence" in existing:
        import json
        bad = 0
        for row in con.execute("SELECT domain, check_type, evidence_json FROM evidence"):
            try:
                json.loads(row[2] or "[]")
            except Exception:
                bad += 1
        (err if bad else ok)("evidence_valid_json", f"{bad} invalid")

    con.close()
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/rivyou.db")
    args = ap.parse_args()

    findings = run(args.db)

    errors = [f for f in findings if f["level"] == "ERROR"]
    warns  = [f for f in findings if f["level"] == "WARN"]

    col_w = {"OK": "\033[32mOK  \033[0m",
             "WARN": "\033[33mWARN\033[0m",
             "ERROR": "\033[31mERR \033[0m"}

    print(f"\n{'Level':<6}  {'Check':<40}  Detail")
    print("-" * 72)
    for f in findings:
        label = col_w.get(f["level"], f["level"])
        print(f"{label}  {f['check']:<40}  {f['detail']}")

    print(f"\nSummary: {len(errors)} errors, {len(warns)} warnings, "
          f"{len(findings)-len(errors)-len(warns)} ok")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
