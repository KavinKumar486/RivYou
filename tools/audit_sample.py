"""
tools/audit_sample.py — generate and score human-review audit sheets.

Sub-commands:
  make   <export.csv> <audit.csv> [--per-stratum N]
         Stratified sample from export.csv + needs_review + shopify-only rows.
         Pre-fills agent_first_pass column; leaves is_shopify/is_indian BLANK.

  score  <audit.csv>
         Reads human-filled is_shopify/is_indian columns.
         Reports precision, recall, F1 against agent verdicts.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
from pathlib import Path


# ── make ──────────────────────────────────────────────────────────────────────

async def _agent_first_pass(domain: str) -> str:
    """Fetch the domain with the production verifiers and summarise findings."""
    try:
        import aiosqlite
        from storage import Storage
        from fetcher import Fetcher
        from verify.shopify import verify as sv
        from verify.india import verify as iv

        storage = Storage(":memory:")
        await storage.init_db()
        fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=5)
        try:
            sr = await sv(fetcher, domain)
            ir = await iv(fetcher, domain)
        finally:
            await fetcher.close()

        shopify_summary = (
            f"shopify={sr['verdict']} families={list(sr['families'].keys())}"
        )
        india_summary = (
            f"india={ir['verdict']} BL={ir['signals']['BL']} "
            f"IC={ir['signals']['IC']}"
        )
        return f"{shopify_summary} | {india_summary}"
    except Exception as e:
        return f"error: {e}"


async def _make(export_csv: str, audit_csv: str,
                per_stratum: int, db_path: str) -> None:
    import sqlite3

    rows_export: list[dict] = []
    if Path(export_csv).exists():
        rows_export = list(csv.DictReader(
            open(export_csv, encoding="utf-8")))

    # Pull needs_review + shopify-but-not-india from DB
    extra_rows: list[dict] = []
    if Path(db_path).exists():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        for row in con.execute(
            "SELECT domain, shopify_verdict, india_verdict FROM stores "
            "WHERE india_verdict='needs_review' LIMIT 40"
        ):
            extra_rows.append({"domain": row[0], "_stratum": "needs_review",
                                "shopify_verdict": row[1],
                                "india_verdict": row[2]})
        for row in con.execute(
            "SELECT domain, shopify_verdict, india_verdict FROM stores "
            "WHERE is_shopify=1 AND (is_india=0 OR is_india IS NULL) "
            "AND india_verdict!='needs_review' LIMIT 40"
        ):
            extra_rows.append({"domain": row[0],
                                "_stratum": "shopify_not_india",
                                "shopify_verdict": row[1],
                                "india_verdict": row[2]})
        con.close()

    # Stratify export rows by category
    strata: dict[str, list[dict]] = {}
    for r in rows_export:
        s = r.get("category") or "Other"
        strata.setdefault(s, []).append(r)

    sampled: list[dict] = []
    for s, items in strata.items():
        random.shuffle(items)
        for item in items[:per_stratum]:
            item["_stratum"] = s
            sampled.append(item)

    # Add needs_review and shopify-only strata (up to 20 each)
    nr = [r for r in extra_rows if r["_stratum"] == "needs_review"]
    sni = [r for r in extra_rows if r["_stratum"] == "shopify_not_india"]
    random.shuffle(nr);  sampled.extend(nr[:20])
    random.shuffle(sni); sampled.extend(sni[:20])

    if not sampled:
        print("No rows to sample. Run extract+export first.")
        sys.exit(1)

    print(f"Fetching agent first-pass for {len(sampled)} domains …")
    out_rows = []
    for i, row in enumerate(sampled, 1):
        domain = row.get("domain", "")
        print(f"  [{i}/{len(sampled)}] {domain}", flush=True)
        afp = await _agent_first_pass(domain)
        out_rows.append({
            "domain":          domain,
            "stratum":         row.get("_stratum", ""),
            "category":        row.get("category", ""),
            "state":           row.get("state", ""),
            "agent_first_pass": afp,
            # Human fills these — left blank
            "is_shopify":      "",
            "is_indian":       "",
            "notes":           "",
        })

    fieldnames = ["domain", "stratum", "category", "state",
                  "agent_first_pass", "is_shopify", "is_indian", "notes"]
    with open(audit_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nWrote {len(out_rows)} rows → {audit_csv}")
    print("Human: fill is_shopify (y/n) and is_indian (y/n) then run: "
          "python tools/audit_sample.py score " + audit_csv)


def _score(audit_csv: str) -> None:
    rows = list(csv.DictReader(open(audit_csv, encoding="utf-8")))
    labeled = [r for r in rows if r.get("is_shopify") in ("y", "n")]
    if not labeled:
        print("No labeled rows found. Fill is_shopify and is_indian first.")
        sys.exit(1)

    # Parse agent verdict from agent_first_pass column
    tp = fp = fn = tn = 0
    for r in labeled:
        afp = r.get("agent_first_pass", "")
        agent_shopify = "shopify=verified" in afp
        human_shopify = r["is_shopify"] == "y"
        if agent_shopify and human_shopify:  tp += 1
        elif agent_shopify and not human_shopify: fp += 1
        elif not agent_shopify and human_shopify: fn += 1
        else: tn += 1

    prec   = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1     = 2 * prec * recall / (prec + recall) if (prec + recall) else float("nan")

    print(f"\nShopify confusion matrix (n={len(labeled)})")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision={prec:.3f}  Recall={recall:.3f}  F1={f1:.3f}")

    # India
    india_labeled = [r for r in rows if r.get("is_indian") in ("y", "n")]
    if india_labeled:
        itp = ifp = ifn = itn = 0
        for r in india_labeled:
            afp = r.get("agent_first_pass", "")
            agent_india = "india=verified" in afp
            human_india = r["is_indian"] == "y"
            if agent_india and human_india:       itp += 1
            elif agent_india and not human_india: ifp += 1
            elif not agent_india and human_india: ifn += 1
            else: itn += 1
        iprec   = itp / (itp + ifp) if (itp + ifp) else float("nan")
        irecall = itp / (itp + ifn) if (itp + ifn) else float("nan")
        print(f"\nIndia confusion matrix (n={len(india_labeled)})")
        print(f"  TP={itp}  FP={ifp}  FN={ifn}  TN={itn}")
        print(f"  Precision={iprec:.3f}  Recall={irecall:.3f}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make")
    m.add_argument("export_csv")
    m.add_argument("audit_csv")
    m.add_argument("--per-stratum", type=int, default=20)
    m.add_argument("--db", default="data/rivyou.db")

    s = sub.add_parser("score")
    s.add_argument("audit_csv")

    args = ap.parse_args()
    if args.cmd == "make":
        asyncio.run(_make(args.export_csv, args.audit_csv,
                          args.per_stratum, args.db))
    else:
        _score(args.audit_csv)


if __name__ == "__main__":
    main()
