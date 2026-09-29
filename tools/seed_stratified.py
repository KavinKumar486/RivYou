"""
tools/seed_stratified.py
Seed ~500 candidates stratified across sources from existing candidate files.
Does NOT hit the network or CC CDX.

Usage:
    python tools/seed_stratified.py --db data/audit.db --n 500
    python tools/seed_stratified.py --db data/audit.db --n 500 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

# Ensure repo root is on sys.path when running as a script from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


_SPIKE_CANDIDATES = Path("spike/data/spike_candidates.json")
_CC_CANDIDATES    = Path("spike/data/cc_candidates.json")
_DATA_CC          = Path("data/cc_candidates.json")

# Proportions of the ~500 target
_STRATA = {
    "tranco":              125,
    "d2c_curated":         125,
    "commoncrawl_q1":      125,   # myshopify_subdomains
    "commoncrawl_q2":      125,   # in_ecom_paths
}


def _load_spike_by_source() -> dict[str, list[str]]:
    """Load spike_candidates.json → {source: [domain, ...]}"""
    data = json.loads(_SPIKE_CANDIDATES.read_text(encoding="utf-8"))
    by_source: dict[str, list[str]] = {"tranco": [], "d2c_curated": []}
    for row in data:
        for src in row.get("sources", []):
            if src in by_source:
                by_source[src].append(row["domain"])
    return by_source


def _load_cc_by_query() -> dict[str, list[str]]:
    """Load CC candidates → {cc_query: [domain, ...]}"""
    for path in (_DATA_CC, _CC_CANDIDATES):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            by_q: dict[str, list[str]] = {
                "myshopify_subdomains": [],
                "in_ecom_paths": [],
            }
            for row in data:
                q = row.get("cc_query", "")
                if q in by_q:
                    by_q[q].append(row["domain"])
            return by_q
    return {"myshopify_subdomains": [], "in_ecom_paths": []}


async def seed(db_path: str, n: int = 500, dry_run: bool = False,
               per_stratum: int = 0) -> list[dict]:
    """
    per_stratum overrides _STRATA values when > 0.
    n is total target (used only when per_stratum == 0, divided equally).
    """
    from storage import Storage
    from utils import normalize_domain

    by_src  = _load_spike_by_source()
    by_cc   = _load_cc_by_query()

    pool: dict[str, list[str]] = {
        "tranco":         by_src.get("tranco", []),
        "d2c_curated":    by_src.get("d2c_curated", []),
        "commoncrawl_q1": by_cc.get("myshopify_subdomains", []),
        "commoncrawl_q2": by_cc.get("in_ecom_paths", []),
    }

    # Determine per-stratum target
    if per_stratum > 0:
        strata_targets = {src: per_stratum for src in _STRATA}
    else:
        each = n // len(_STRATA)
        strata_targets = {src: each for src in _STRATA}

    # Adjust counts if pool smaller than target
    samples: list[dict] = []
    for src, target in strata_targets.items():
        items = list(set(pool.get(src, [])))
        random.shuffle(items)
        take = min(target, len(items))
        for d in items[:take]:
            norm = normalize_domain(d) if "myshopify" not in d else d.lower()
            if norm:
                samples.append({"domain": norm, "source": src})

    print(f"Sampled {len(samples)} candidates across {len(strata_targets)} strata:")
    for src in strata_targets:
        cnt = sum(1 for s in samples if s["source"] == src)
        print(f"  {src:<25} {cnt}")

    if dry_run:
        print("[dry-run] Not writing to DB.")
        return samples

    storage = Storage(db_path)
    await storage.init_db()
    inserted = 0
    for s in samples:
        existing = await storage.get_candidate(s["domain"])
        if existing is None:
            await storage.save_candidate(s["domain"], s["source"])
            inserted += 1
    print(f"Inserted {inserted} new candidates into {db_path}")
    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",      default="data/audit.db")
    ap.add_argument("--n",       type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed",    type=int, default=42,
                    help="random seed for reproducibility")
    args = ap.parse_args()
    random.seed(args.seed)
    asyncio.run(seed(args.db, args.n, args.dry_run))


if __name__ == "__main__":
    main()
