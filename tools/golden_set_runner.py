"""
tools/golden_set_runner.py
Run the production Shopify verifier against every domain in golden_set.csv.

Usage:
    python tools/golden_set_runner.py [--golden spike/data/golden_set.csv]
                                      [--out data/golden_results.json]
                                      [--retries 3]
                                      [--bypass-cache]

--bypass-cache forces fresh fetches even if the URL is in fetch_cache.

Outputs:
  - data/golden_results.json  — per-domain results
  - Prints confusion matrix + FP/FN list to stdout
  - Evidence-variety check: fails loudly if all positives show identical families
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def run_golden(golden_csv: str, out_json: str,
                     retries: int, bypass_cache: bool) -> dict:
    from storage import Storage
    from fetcher import Fetcher
    from verify.shopify import verify as sv

    labels: list[dict] = []
    for row in csv.DictReader(open(golden_csv, encoding="utf-8")):
        labels.append({
            "domain": row["domain"].strip(),
            "label":  row["hand_label"].strip(),
        })

    # Use a temp file DB (not :memory:) so all connections share the same schema
    import tempfile, os
    _tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp.close()
    storage = Storage(_tmp.name)
    await storage.init_db()
    fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=10)

    results = []
    t0 = time.monotonic()
    try:
        for i, entry in enumerate(labels, 1):
            domain = entry["domain"]
            label  = entry["label"]
            verdict = "rejected"
            inc     = False
            families: dict = {}
            evidence: list = []

            for attempt in range(retries):
                # bypass_cache=True forces a fresh HTTP fetch via fetcher.fetch(refresh=True)
                r = await sv(fetcher, domain, bypass_cache=bypass_cache)
                if not r["inconclusive"] or attempt == retries - 1:
                    verdict  = r["verdict"]
                    inc      = r["inconclusive"]
                    families = r["families"]
                    evidence = r["evidence"]
                    break
                wait = 2 ** attempt
                print(f"    inconclusive, retry {attempt+1}/{retries} in {wait}s …",
                      flush=True)
                await asyncio.sleep(wait)

            pred_shopify  = verdict == "verified"
            label_shopify = label == "shopify"
            correct = pred_shopify == label_shopify

            fam_str = ",".join(sorted(families.keys())) if families else "none"
            print(f"[{i:2}/{len(labels)}] {domain:<35} "
                  f"label={label:<12} pred={verdict:<10} "
                  f"families=[{fam_str}] inc={inc}  "
                  f"{'✓' if correct else '✗'}", flush=True)

            results.append({
                "domain":       domain,
                "label":        label,
                "verdict":      verdict,
                "inconclusive": inc,
                "families":     families,
                "evidence":     evidence,
                "correct":      correct,
            })
    finally:
        await fetcher.close()
        try:
            os.unlink(_tmp.name)
        except Exception:
            pass

    elapsed = time.monotonic() - t0

    # ── Evidence-variety sanity check ─────────────────────────────────────
    # All 30 positives must NOT show identical family sets — that would indicate
    # a caching or short-circuit bug in the verifier
    positive_results = [r for r in results if r["label"] == "shopify"
                        and not r["inconclusive"]]
    if positive_results:
        family_signatures = {frozenset(r["families"].keys())
                             for r in positive_results}
        print(f"\nEvidence-variety check: {len(family_signatures)} distinct family "
              f"signatures across {len(positive_results)} positives")
        if len(family_signatures) == 1:
            print("WARNING: ALL positives show identical family sets — "
                  "possible caching or short-circuit bug. "
                  "Review evidence rows before trusting these results.")
        else:
            print("OK — family signatures vary as expected.")

    # ── Confusion matrix ──────────────────────────────────────────────────
    decided  = [r for r in results if not r["inconclusive"]]
    inc_list = [r for r in results if r["inconclusive"]]

    tp = sum(1 for r in decided
             if r["label"] == "shopify"     and r["verdict"] == "verified")
    fp = sum(1 for r in decided
             if r["label"] == "not_shopify" and r["verdict"] == "verified")
    fn = sum(1 for r in decided
             if r["label"] == "shopify"     and r["verdict"] != "verified")
    tn = sum(1 for r in decided
             if r["label"] == "not_shopify" and r["verdict"] != "verified")

    prec   = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")

    print(f"\n{'='*60}")
    print(f"Golden set: {len(labels)} total  |  "
          f"decided: {len(decided)}  inconclusive: {len(inc_list)}")
    print(f"TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    prec_str   = f"{prec:.3f}"   if not math.isnan(prec)   else "n/a"
    recall_str = f"{recall:.3f}" if not math.isnan(recall) else "n/a"
    print(f"Precision={prec_str}  Recall={recall_str}")
    print(f"Elapsed: {elapsed:.1f}s")

    if fp:
        print(f"\nFALSE POSITIVES ({fp}):")
        for r in decided:
            if r["label"] == "not_shopify" and r["verdict"] == "verified":
                sig = list(r["families"].keys())
                evs = [e["value"] for e in r["evidence"]]
                print(f"  {r['domain']:<35}  families={sig}")
                print(f"    evidence signals: {evs}")

    if fn:
        print(f"\nFALSE NEGATIVES ({fn}):")
        for r in decided:
            if r["label"] == "shopify" and r["verdict"] != "verified":
                sig = list(r["families"].keys())
                print(f"  {r['domain']:<35}  verdict={r['verdict']}  "
                      f"families={sig}")

    if inc_list:
        print(f"\nINCONCLUSIVE after {retries} retries ({len(inc_list)}):")
        for r in inc_list:
            print(f"  {r['domain']}")

    # ── Save ──────────────────────────────────────────────────────────────
    summary = {
        "total": len(labels), "decided": len(decided),
        "inconclusive": len(inc_list),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(prec, 4)   if not math.isnan(prec)   else None,
        "recall":    round(recall, 4) if not math.isnan(recall) else None,
        "elapsed_s": round(elapsed, 1),
        "bypass_cache": bypass_cache,
        "results":   results,
    }

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\nResults written → {out_json}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden",       default="spike/data/golden_set.csv")
    ap.add_argument("--out",          default="data/golden_results.json")
    ap.add_argument("--retries",      type=int, default=3)
    ap.add_argument("--bypass-cache", action="store_true",
                    help="Force fresh HTTP fetches (ignore fetch_cache)")
    args = ap.parse_args()
    asyncio.run(run_golden(args.golden, args.out, args.retries,
                           args.bypass_cache))


if __name__ == "__main__":
    main()
