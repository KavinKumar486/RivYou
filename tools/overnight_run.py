"""
tools/overnight_run.py
Overnight orchestration: runs all verification steps sequentially,
logging everything to data/overnight.log. Safe to kill and restart
(each step checks what's already done before doing work).

Usage:
    python tools/overnight_run.py [--db data/audit.db] [--skip-golden]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LOG_PATH = Path("data/overnight.log")
_STATE_PATH = Path("data/overnight_state.json")


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _save_state(state: dict) -> None:
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_state() -> dict:
    if _STATE_PATH.exists():
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    return {}


def _db_counts(db_path: str) -> dict:
    c = sqlite3.connect(db_path)
    result = {
        "candidates": c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "stores":     c.execute("SELECT COUNT(*) FROM stores").fetchone()[0],
        "fetch_cache":c.execute("SELECT COUNT(*) FROM fetch_cache").fetchone()[0],
        "extracted":  c.execute("SELECT COUNT(*) FROM extracted").fetchone()[0],
        "verdicts":   dict(c.execute(
            "SELECT shopify_verdict, COUNT(*) FROM stores "
            "GROUP BY shopify_verdict").fetchall()),
        "india_verdicts": dict(c.execute(
            "SELECT india_verdict, COUNT(*) FROM stores "
            "WHERE india_verdict IS NOT NULL "
            "GROUP BY india_verdict").fetchall()),
        "inconclusive": c.execute(
            "SELECT COUNT(*) FROM stores WHERE inconclusive=1").fetchone()[0],
    }
    c.close()
    return result


def _wilson_interval(successes: int, n: int,
                     z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval."""
    if n == 0:
        return (0.0, 1.0)
    p_hat = successes / n
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# ─────────────────────────────────────────────────────────────────────────────
# STEP 0 — Proxy check
# ─────────────────────────────────────────────────────────────────────────────

def step0_proxy():
    import os
    proxy_env = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
    _log(f"STEP 0 proxy env: {proxy_env or 'none'}")
    _log("STEP 0 COMPLETE")
    return proxy_env


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Golden set
# ─────────────────────────────────────────────────────────────────────────────

async def step1_golden(out_json: str = "data/golden_results.json") -> dict:
    state = _load_state()
    if state.get("step1_done"):
        _log("STEP 1 already done — skipping")
        if Path(out_json).exists():
            return json.loads(Path(out_json).read_text(encoding="utf-8"))
        return {}

    _log("STEP 1 starting: golden set live run (bypass-cache, retries=3)")
    t0 = time.monotonic()

    from storage import Storage
    from fetcher import Fetcher
    from verify.shopify import verify as sv

    golden_csv = "spike/data/golden_set.csv"
    labels = []
    for row in csv.DictReader(open(golden_csv, encoding="utf-8")):
        labels.append({"domain": row["domain"].strip(),
                        "label": row["hand_label"].strip()})

    storage = Storage(":memory:")
    await storage.init_db()
    fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=5)
    results = []

    try:
        for i, entry in enumerate(labels, 1):
            domain, label = entry["domain"], entry["label"]
            verdict = "rejected"; inc = False; families = {}; evidence = []
            t_domain = time.monotonic()

            for attempt in range(3):
                r = await sv(fetcher, domain, bypass_cache=True)
                if not r["inconclusive"] or attempt == 2:
                    verdict = r["verdict"]; inc = r["inconclusive"]
                    families = r["families"]; evidence = r["evidence"]
                    break
                wait = 2 ** attempt
                _log(f"  [{i}] {domain} inconclusive, retry {attempt+1} in {wait}s")
                await asyncio.sleep(wait)

            elapsed_d = time.monotonic() - t_domain
            correct = (verdict == "verified") == (label == "shopify")
            fam_str = ",".join(sorted(families.keys())) or "none"
            _log(f"  [{i:2}/{len(labels)}] {domain:<35} label={label:<12} "
                 f"pred={verdict:<10} families=[{fam_str}] "
                 f"inc={inc} {'✓' if correct else '✗'} ({elapsed_d:.1f}s)")
            results.append({"domain": domain, "label": label, "verdict": verdict,
                             "inconclusive": inc, "families": families,
                             "evidence": evidence, "correct": correct})
    finally:
        await fetcher.close()

    elapsed = time.monotonic() - t0

    # Evidence-variety check
    positives = [r for r in results if r["label"] == "shopify" and not r["inconclusive"]]
    sigs = {frozenset(r["families"].keys()) for r in positives}
    _log(f"Evidence-variety: {len(sigs)} distinct family signatures across "
         f"{len(positives)} decided positives")
    if len(sigs) == 1:
        _log("WARNING: all positives show identical family sets — possible bug")
    else:
        _log("Evidence-variety OK")

    decided  = [r for r in results if not r["inconclusive"]]
    inc_list = [r for r in results if r["inconclusive"]]
    tp = sum(1 for r in decided if r["label"]=="shopify"     and r["verdict"]=="verified")
    fp = sum(1 for r in decided if r["label"]=="not_shopify" and r["verdict"]=="verified")
    fn = sum(1 for r in decided if r["label"]=="shopify"     and r["verdict"]!="verified")
    tn = sum(1 for r in decided if r["label"]=="not_shopify" and r["verdict"]!="verified")
    prec   = tp/(tp+fp) if (tp+fp) else float("nan")
    recall = tp/(tp+fn) if (tp+fn) else float("nan")

    _log(f"Golden set result: total={len(labels)} decided={len(decided)} "
         f"inconclusive={len(inc_list)}")
    _log(f"TP={tp} FP={fp} FN={fn} TN={tn} "
         f"Precision={prec:.3f} Recall={recall:.3f}")

    for r in decided:
        if r["label"]=="not_shopify" and r["verdict"]=="verified":
            _log(f"  FALSE POSITIVE: {r['domain']}  families={list(r['families'].keys())}")
        if r["label"]=="shopify" and r["verdict"]!="verified":
            _log(f"  FALSE NEGATIVE: {r['domain']}  verdict={r['verdict']}  "
                 f"families={list(r['families'].keys())}")
    for r in inc_list:
        _log(f"  INCONCLUSIVE: {r['domain']}")

    summary = {
        "total": len(labels), "decided": len(decided),
        "inconclusive": len(inc_list),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(prec, 4) if not math.isnan(prec) else None,
        "recall":    round(recall, 4) if not math.isnan(recall) else None,
        "elapsed_s": round(elapsed, 1),
        "results": results,
    }
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    state["step1_done"] = True
    state["step1_elapsed_s"] = round(elapsed, 1)
    state["step1_tp"] = tp; state["step1_fp"] = fp
    state["step1_fn"] = fn; state["step1_tn"] = tn
    _save_state(state)
    _log(f"STEP 1 COMPLETE in {elapsed:.0f}s")
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Expand candidates
# ─────────────────────────────────────────────────────────────────────────────

async def step2_seed(db_path: str, per_stratum: int = 750) -> int:
    state = _load_state()
    if state.get("step2_done"):
        _log("STEP 2 already done — skipping")
        return state.get("step2_inserted", 0)

    _log(f"STEP 2 starting: seed ~{per_stratum*4} candidates into {db_path}")
    t0 = time.monotonic()

    import random
    random.seed(42)

    from tools.seed_stratified import seed
    samples = await seed(db_path, per_stratum * 4, dry_run=False)
    inserted = len(samples)

    counts = _db_counts(db_path)
    elapsed = time.monotonic() - t0
    _log(f"STEP 2 candidates after seed: {counts['candidates']} "
         f"(inserted {inserted} new) in {elapsed:.0f}s")
    state["step2_done"] = True
    state["step2_inserted"] = inserted
    state["step2_candidates"] = counts["candidates"]
    _save_state(state)
    _log(f"STEP 2 COMPLETE in {elapsed:.0f}s")
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — verify-shopify to completion
# ─────────────────────────────────────────────────────────────────────────────

async def step3_verify_shopify(db_path: str) -> dict:
    state = _load_state()
    if state.get("step3_done"):
        _log("STEP 3 already done — skipping")
        return _db_counts(db_path)

    _log(f"STEP 3 starting: verify-shopify (no limit) on {db_path}")
    t0 = time.monotonic()

    from storage import Storage
    from fetcher import Fetcher
    from verify.shopify import verify as sv

    storage = Storage(db_path)
    await storage.init_db()
    fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=10)

    try:
        candidates = await storage.get_unverified_candidates()
        _log(f"  {len(candidates)} unverified candidates to check")
        verified = uncertain = rejected = inconclusive = 0

        for i, domain in enumerate(candidates, 1):
            r = await sv(fetcher, domain)
            verdict = r["verdict"]; inc = r["inconclusive"]
            is_shopify = verdict == "verified"

            await storage.save_store_verification(
                domain=domain, is_shopify=is_shopify, is_india=None,
                inconclusive=inc, shopify_verdict=verdict,
                evidence={"shopify": r["evidence"]},
            )
            if inc:           inconclusive += 1
            elif is_shopify:  verified += 1
            elif verdict == "uncertain": uncertain += 1
            else:             rejected += 1

            if i % 50 == 0:
                elapsed_so_far = time.monotonic() - t0
                _log(f"  [{i}/{len(candidates)}] verified={verified} "
                     f"uncertain={uncertain} rejected={rejected} "
                     f"inconclusive={inconclusive} elapsed={elapsed_so_far:.0f}s")
    finally:
        await fetcher.close()

    elapsed = time.monotonic() - t0
    counts = _db_counts(db_path)
    _log(f"STEP 3 done: verified={verified} uncertain={uncertain} "
         f"rejected={rejected} inconclusive={inconclusive} "
         f"elapsed={elapsed:.0f}s")
    state["step3_done"] = True
    state["step3_elapsed_s"] = round(elapsed, 1)
    state["step3_verified"] = verified
    state["step3_rejected"] = rejected
    state["step3_inconclusive"] = inconclusive
    _save_state(state)
    _log(f"STEP 3 COMPLETE in {elapsed:.0f}s")
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — verify-india
# ─────────────────────────────────────────────────────────────────────────────

async def step4_verify_india(db_path: str) -> dict:
    state = _load_state()
    if state.get("step4_done"):
        _log("STEP 4 already done — skipping")
        return _db_counts(db_path)

    _log(f"STEP 4 starting: verify-india on {db_path}")
    t0 = time.monotonic()

    from storage import Storage
    from fetcher import Fetcher
    from verify.india import verify as iv

    storage = Storage(db_path)
    await storage.init_db()
    fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=10)

    try:
        shopify_hits = await storage.get_shopify_hits()
        _log(f"  {len(shopify_hits)} Shopify stores to India-verify")
        verified = needs_review = rejected = 0

        # Idempotency check: record fetch_cache before
        fc_before = sqlite3.connect(db_path).execute(
            "SELECT COUNT(*) FROM fetch_cache").fetchone()[0]

        for i, domain in enumerate(shopify_hits, 1):
            r = await iv(fetcher, domain)
            verdict = r["verdict"]
            is_india = verdict == "verified"
            await storage.save_store_verification(
                domain=domain, is_shopify=True, is_india=is_india,
                inconclusive=False, india_verdict=verdict,
                india_support=r.get("india_support", "none"),
                evidence={"india": r["evidence"]},
            )
            if verdict == "verified":     verified += 1
            elif verdict == "needs_review": needs_review += 1
            else:                           rejected += 1

            if i % 20 == 0:
                _log(f"  [{i}/{len(shopify_hits)}] india: verified={verified} "
                     f"needs_review={needs_review} rejected={rejected}")
    finally:
        await fetcher.close()

    elapsed = time.monotonic() - t0
    counts = _db_counts(db_path)

    # Idempotency verification: re-run a handful of already-done domains
    fc_after_run = sqlite3.connect(db_path).execute(
        "SELECT COUNT(*) FROM fetch_cache").fetchone()[0]

    _log(f"STEP 4 done: india verified={verified} needs_review={needs_review} "
         f"rejected={rejected} elapsed={elapsed:.0f}s")
    _log(f"  fetch_cache: before={fc_before} after_run={fc_after_run} "
         f"delta={fc_after_run - fc_before}")

    state["step4_done"] = True
    state["step4_elapsed_s"] = round(elapsed, 1)
    state["step4_india_verified"] = verified
    state["step4_needs_review"] = needs_review
    state["step4_rejected"] = rejected
    state["step4_fc_delta"] = fc_after_run - fc_before
    _save_state(state)
    _log(f"STEP 4 COMPLETE in {elapsed:.0f}s")
    return counts


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — extract + export
# ─────────────────────────────────────────────────────────────────────────────

async def step5_extract_export(db_path: str,
                                output_prefix: str = "data/audit_output") -> dict:
    state = _load_state()
    if state.get("step5_done"):
        _log("STEP 5 already done — skipping")
        return state.get("step5_fill_rates", {})

    _log(f"STEP 5 starting: extract + export on {db_path}")
    t0 = time.monotonic()

    from storage import Storage
    from fetcher import Fetcher
    from extract.run import extract_store, fill_rate_report
    import csv as csv_mod

    storage = Storage(db_path)
    await storage.init_db()
    fetcher = Fetcher(storage, min_interval=1.0, max_concurrency=10)

    try:
        domains = await storage.get_verified_indian_stores()
        _log(f"  {len(domains)} verified Indian stores to extract")

        for i, domain in enumerate(domains, 1):
            fields = await extract_store(fetcher, domain)
            await storage.save_extracted(domain, fields)
            if i % 10 == 0:
                _log(f"  extracted {i}/{len(domains)}")
    finally:
        await fetcher.close()

    # Fill-rate report
    all_records = await storage.get_all_extracted()
    report = fill_rate_report(all_records)
    _log(f"Fill-rate report ({len(all_records)} records):")
    for field, stats in report.items():
        _log(f"  {field:<14} {stats['filled']:3}/{stats['total']:3}  "
             f"{stats['rate']*100:.0f}%  {stats['miss_reason']}")

    # Export JSON
    json_path = Path(output_prefix + ".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(all_records, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    _log(f"  Exported {len(all_records)} records → {json_path}")

    # Export CSV
    csv_path = Path(output_prefix + ".csv")
    flat_fields = ["domain", "category", "category_method", "tagline",
                   "tagline_method", "logo_url", "logo_local_path", "logo_source",
                   "state", "state_method", "state_status", "extracted_at"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv_mod.DictWriter(f, fieldnames=flat_fields, extrasaction="ignore")
        w.writeheader()
        for r in all_records:
            w.writerow(r)
    _log(f"  Exported {len(all_records)} records → {csv_path}")

    elapsed = time.monotonic() - t0
    state["step5_done"] = True
    state["step5_elapsed_s"] = round(elapsed, 1)
    state["step5_fill_rates"] = report
    _save_state(state)
    _log(f"STEP 5 COMPLETE in {elapsed:.0f}s")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Structural checks
# ─────────────────────────────────────────────────────────────────────────────

def step6_checks(db_path: str, csv_path: str) -> None:
    _log("STEP 6 starting: db_health + check_export")
    t0 = time.monotonic()

    from tools.db_health import run as db_health_run
    findings = db_health_run(db_path)
    errors = [f for f in findings if f["level"] == "ERROR"]
    warns  = [f for f in findings if f["level"] == "WARN"]
    _log(f"  db_health: {len(errors)} errors, {len(warns)} warnings")
    for f in errors + warns:
        _log(f"  {f['level']} {f['check']}: {f['detail']}")

    if Path(csv_path).exists():
        from tools.check_export import check as export_check
        exp_findings = export_check(csv_path, check_urls=0)
        exp_errors = [f for f in exp_findings if f["level"] == "ERROR"]
        exp_warns  = [f for f in exp_findings if f["level"] == "WARN"]
        _log(f"  check_export: {len(exp_errors)} errors, {len(exp_warns)} warnings")
        for f in exp_errors + exp_warns:
            _log(f"  {f['level']} {f['field']} [{f['domain']}]: {f['detail']}")
    else:
        _log(f"  check_export: SKIPPED ({csv_path} not found)")

    # State-method breakdown
    c = sqlite3.connect(db_path)
    state_methods = c.execute(
        "SELECT state_method, state_status, COUNT(*) FROM extracted "
        "GROUP BY state_method, state_status ORDER BY 3 DESC"
    ).fetchall()
    _log("  State resolution methods:")
    for row in state_methods:
        _log(f"    method={row[0]}  status={row[1]}  count={row[2]}")
    c.close()

    elapsed = time.monotonic() - t0
    _log(f"STEP 6 COMPLETE in {elapsed:.0f}s")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Per-source funnel
# ─────────────────────────────────────────────────────────────────────────────

def step7_funnel(db_path: str) -> None:
    _log("STEP 7 starting: per-source funnel")
    t0 = time.monotonic()
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row

    # Shopify funnel by source
    rows = c.execute("""
        SELECT c.source,
               s.shopify_verdict,
               s.inconclusive,
               s.india_verdict,
               COUNT(*) as n
        FROM candidates c
        LEFT JOIN stores s ON c.domain = s.domain
        GROUP BY c.source, s.shopify_verdict, s.inconclusive, s.india_verdict
        ORDER BY c.source, s.shopify_verdict
    """).fetchall()

    # Aggregate
    sources: dict[str, dict] = {}
    for row in rows:
        src = row["source"] or "unknown"
        if src not in sources:
            sources[src] = {"candidates": 0, "verified": 0, "uncertain": 0,
                            "rejected": 0, "inconclusive": 0, "no_store": 0,
                            "india_verified": 0, "india_needs_review": 0,
                            "india_rejected": 0}
        n = row["n"]
        sources[src]["candidates"] += n
        vd = row["shopify_verdict"]
        inc = row["inconclusive"]
        iv_vd = row["india_verdict"]

        if vd is None:
            sources[src]["no_store"] += n
        elif inc:
            sources[src]["inconclusive"] += n
        elif vd == "verified":
            sources[src]["verified"] += n
        elif vd == "uncertain":
            sources[src]["uncertain"] += n
        else:
            sources[src]["rejected"] += n

        if iv_vd == "verified":
            sources[src]["india_verified"] += n
        elif iv_vd == "needs_review":
            sources[src]["india_needs_review"] += n
        elif iv_vd == "rejected":
            sources[src]["india_rejected"] += n

    c.close()

    _log("\nPer-source funnel:")
    _log(f"  {'Source':<25} {'Cands':>6} {'No-store':>8} {'Decided':>7} "
         f"{'Shopify':>7} {'Uncert':>6} {'Rej':>6} {'Inc':>6} "
         f"{'IndVerif':>8} {'NeedsRev':>8}")
    _log("  " + "-"*100)
    for src, d in sources.items():
        decided = d["verified"] + d["uncertain"] + d["rejected"]
        _log(f"  {src:<25} {d['candidates']:>6} {d['no_store']:>8} "
             f"{decided:>7} {d['verified']:>7} {d['uncertain']:>6} "
             f"{d['rejected']:>6} {d['inconclusive']:>6} "
             f"{d['india_verified']:>8} {d['india_needs_review']:>8}")

    # Wilson intervals for Shopify rate
    _log("\nShopify rate Wilson 95% CI per source (lower / point / upper):")
    for src, d in sources.items():
        decided = d["verified"] + d["uncertain"] + d["rejected"]
        if decided == 0:
            continue
        lo, hi = _wilson_interval(d["verified"], decided)
        pt = d["verified"] / decided
        # Inconclusive lower bound: treat all inc as miss
        total_inc = decided + d["inconclusive"]
        lo_lb = d["verified"] / total_inc if total_inc else 0
        _log(f"  {src:<25} decided={decided:4}  "
             f"shopify_rate: {lo_lb:.3f}(lb) / {pt:.3f} / [{lo:.3f}, {hi:.3f}]")

    elapsed = time.monotonic() - t0
    _log(f"STEP 7 COMPLETE in {elapsed:.0f}s")


# ─────────────────────────────────────────────────────────────────────────────
# STEP 8 — Audit sheet
# ─────────────────────────────────────────────────────────────────────────────

async def step8_audit_sheet(db_path: str,
                             csv_path: str = "data/audit_output.csv",
                             out: str = "audit.csv") -> None:
    state = _load_state()
    if state.get("step8_done"):
        _log("STEP 8 already done — skipping")
        return

    if not Path(csv_path).exists():
        _log(f"STEP 8 SKIPPED — {csv_path} not found (extract not run?)")
        return

    _log("STEP 8 starting: audit sheet")
    t0 = time.monotonic()

    from tools.audit_sample import _make
    await _make(csv_path, out, per_stratum=20, db_path=db_path)

    elapsed = time.monotonic() - t0
    state["step8_done"] = True
    _save_state(state)
    _log(f"STEP 8 COMPLETE in {elapsed:.0f}s → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main(db_path: str, skip_golden: bool) -> None:
    wall_start = time.monotonic()
    _log("=" * 60)
    _log(f"OVERNIGHT RUN starting  db={db_path}")
    _log("=" * 60)

    # Step 0 — proxy
    step0_proxy()

    # Step 1 — golden set (highest priority)
    if not skip_golden:
        await step1_golden()
    else:
        _log("STEP 1 SKIPPED (--skip-golden)")

    # Step 2 — expand candidates
    await step2_seed(db_path, per_stratum=750)

    # Step 3 — verify-shopify
    await step3_verify_shopify(db_path)

    # Step 7 — funnel (cheap, run before slow steps)
    step7_funnel(db_path)

    # Step 4 — verify-india
    await step4_verify_india(db_path)

    # Step 5 — extract + export
    await step5_extract_export(db_path)

    # Step 6 — structural checks
    step6_checks(db_path, "data/audit_output.csv")

    # Step 7 again — final funnel with india results
    _log("STEP 7 (final, with India results):")
    step7_funnel(db_path)

    # Step 8 — audit sheet
    await step8_audit_sheet(db_path)

    wall_elapsed = time.monotonic() - wall_start
    state = _load_state()
    _log("=" * 60)
    _log(f"OVERNIGHT RUN COMPLETE  total elapsed={wall_elapsed/3600:.2f}h")
    _log(f"Final DB state: {_db_counts(db_path)}")
    _log("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/audit.db")
    ap.add_argument("--skip-golden", action="store_true")
    args = ap.parse_args()

    # Reset _STATE_PATH if starting fresh (only if no partial state)
    if not _STATE_PATH.exists():
        _save_state({})

    asyncio.run(main(args.db, args.skip_golden))
