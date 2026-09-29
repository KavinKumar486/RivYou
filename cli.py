"""
Rivyou pipeline CLI.

Stages:
    init
    seed
    verify-shopify
    verify-india
    extract
    export
"""

import argparse
import asyncio
import logging

from storage import Storage
from fetcher import Fetcher


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger("cli")


async def _make_storage(
    db_path: str = "data/rivyou.db",
) -> Storage:
    storage = Storage(db_path)
    await storage.init_db()
    return storage


async def cmd_init(args) -> None:
    storage = await _make_storage(args.db)

    logger.info(
        "Database initialised at %s",
        storage.db_path,
    )


async def cmd_seed(args) -> None:
    storage = await _make_storage(args.db)

    sources_to_run: list[str] = args.sources or [
        "tranco",
        "d2c",
        "commoncrawl",
        "neighbors",
    ]

    logger.info(
        "Running sources: %s",
        sources_to_run,
    )

    all_candidates: list[dict] = []

    if "tranco" in sources_to_run:
        from sources.tranco import get_candidates

        all_candidates.extend(
            get_candidates()
        )

    if "d2c" in sources_to_run:
        from sources.lists import get_candidates

        all_candidates.extend(
            get_candidates()
        )

    if "commoncrawl" in sources_to_run:
        from sources.commoncrawl import get_candidates

        all_candidates.extend(
            get_candidates()
        )

    if "neighbors" in sources_to_run:
        from sources.neighbors import get_seed_stores
        from sources.neighbors import expand

        fetcher = Fetcher(storage)

        try:
            neighbor_cands = await expand(
                fetcher,
                get_seed_stores(),
                rounds=1,
            )

            all_candidates.extend(
                neighbor_cands
            )

        finally:
            await fetcher.close()

    seen: set[str] = set()
    rows: list[tuple] = []

    for entry in all_candidates:
        domain = entry.get(
            "domain",
            "",
        ).strip().lower()

        if not domain or domain in seen:
            continue

        seen.add(domain)
        rows.append((
            domain,
            entry.get("source", "unknown"),
        ))

    new_count = await storage.save_candidates_bulk(rows)

    logger.info(
        "Seed complete: %d new candidates inserted "
        "(total unique: %d)",
        new_count,
        len(seen),
    )


async def cmd_verify_shopify(args) -> None:
    from verify.shopify import verify

    storage = await _make_storage(args.db)
    concurrency = args.concurrency or 50
    fetcher = Fetcher(storage, max_concurrency=concurrency)

    try:
        if args.limit:
            candidates = (
                await storage.get_candidates_without_store()
            )[:args.limit]
        else:
            candidates = (
                await storage.get_unverified_candidates()
            )

        logger.info(
            "%d candidates to verify for Shopify",
            len(candidates),
        )

        verified = 0
        uncertain = 0
        rejected = 0
        inconclusive = 0
        done = 0

        domain_sem = asyncio.Semaphore(concurrency)

        async def _verify_one(domain: str) -> None:
            nonlocal verified, uncertain, rejected, inconclusive, done

            async with domain_sem:
                try:
                    result = await verify(fetcher, domain)
                    verdict = result["verdict"]
                    is_shopify = verdict == "verified"
                    inc = result["inconclusive"]

                    await storage.save_store_verification(
                        domain=domain,
                        is_shopify=is_shopify,
                        is_india=None,
                        inconclusive=inc,
                        shopify_verdict=verdict,
                        evidence={"shopify": result["evidence"]},
                    )

                    if inc:              inconclusive += 1
                    elif verdict == "verified":   verified += 1
                    elif verdict == "uncertain":  uncertain += 1
                    else:                rejected += 1
                except Exception:
                    logger.exception("verify-shopify failed for %s", domain)

                done += 1
                if done % 50 == 0 or done == len(candidates):
                    logger.info("  progress %d/%d  verified=%d rejected=%d inconclusive=%d",
                                done, len(candidates), verified, rejected, inconclusive)

        logger.info("concurrency: domain_sem=%d fetcher.semaphore=%d",
                    concurrency, fetcher.semaphore._value)
        await asyncio.gather(*[_verify_one(d) for d in candidates])

        logger.info(
            "verify-shopify done: verified=%d "
            "uncertain=%d rejected=%d "
            "inconclusive=%d",
            verified,
            uncertain,
            rejected,
            inconclusive,
        )

    finally:
        await fetcher.close()


async def cmd_verify_india(args) -> None:
    from verify.india import verify

    storage = await _make_storage(args.db)
    concurrency = args.concurrency or 50
    fetcher = Fetcher(storage, max_concurrency=concurrency)

    try:
        shopify_hits = (
            await storage.get_shopify_hits()
        )

        if args.limit:
            shopify_hits = shopify_hits[
                :args.limit
            ]

        logger.info(
            "%d Shopify stores to verify for India",
            len(shopify_hits),
        )

        verified = 0
        needs_review = 0
        rejected = 0
        done = 0

        domain_sem = asyncio.Semaphore(concurrency)

        async def _verify_one(domain: str) -> None:
            nonlocal verified, needs_review, rejected, done

            async with domain_sem:
                try:
                    result = await verify(fetcher, domain)
                    verdict = result["verdict"]
                    is_india = verdict == "verified"

                    await storage.save_india_verification(
                        domain=domain,
                        is_india=is_india,
                        india_verdict=verdict,
                        india_support=result.get("india_support", "none"),
                        evidence=result["evidence"],
                    )

                    if verdict == "verified":      verified += 1
                    elif verdict == "needs_review": needs_review += 1
                    else:                           rejected += 1
                except Exception:
                    logger.exception("verify-india failed for %s", domain)

                done += 1
                if done % 20 == 0 or done == len(shopify_hits):
                    logger.info("  progress %d/%d  verified=%d needs_review=%d rejected=%d",
                                done, len(shopify_hits), verified, needs_review, rejected)

        logger.info("concurrency: domain_sem=%d fetcher.semaphore=%d",
                    concurrency, fetcher.semaphore._value)
        await asyncio.gather(*[_verify_one(d) for d in shopify_hits])

        logger.info(
            "verify-india done: verified=%d "
            "needs_review=%d rejected=%d",
            verified,
            needs_review,
            rejected,
        )

    finally:
        await fetcher.close()


async def cmd_extract(args) -> None:
    from extract.run import (
        extract_store,
        fill_rate_report,
    )

    storage = await _make_storage(args.db)
    fetcher = Fetcher(storage)

    try:
        domains = (
            await storage.get_verified_indian_stores()
        )

        if args.limit:
            domains = domains[:args.limit]

        logger.info(
            "%d verified Indian stores to extract",
            len(domains),
        )

        for i, domain in enumerate(
            domains,
            1,
        ):
            fields = await extract_store(
                fetcher,
                domain,
            )

            await storage.save_extracted(
                domain,
                fields,
            )

            if (
                i % 10 == 0
                or i == len(domains)
            ):
                logger.info(
                    "extracted %d/%d",
                    i,
                    len(domains),
                )

        all_records = (
            await storage.get_all_extracted()
        )

        report = fill_rate_report(
            all_records
        )

        logger.info(
            "Fill-rate report (%d records)",
            len(all_records),
        )

        for field, stats in report.items():
            logger.info(
                "%-14s %3d/%3d %.0f%% %s",
                field,
                stats["filled"],
                stats["total"],
                stats["rate"] * 100,
                stats["miss_reason"],
            )

    finally:
        await fetcher.close()


async def cmd_export(args) -> None:
    import csv
    import json
    from pathlib import Path

    storage = await _make_storage(args.db)

    records = await storage.get_export_records(
        args.status
    )

    if not records:
        logger.info(
            "No records found for the requested export."
        )
        return

    output = Path(args.output)

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fmt = args.format

    if fmt in ("json", "both"):
        json_path = Path(
            str(output) + ".json"
        )

        json_path.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        logger.info(
            "Wrote %d records -> %s",
            len(records),
            json_path,
        )

    if fmt in ("csv", "both"):
        csv_path = Path(
            str(output) + ".csv"
        )

        flat_fields = [
            "domain",
            "india_verdict",
            "category",
            "tagline",
            "logo_url",
            "contacts",
            "socials",
            "state",
            "state_status",
            "category_method",
            "tagline_method",
            "logo_source",
            "state_method",
            "extracted_at",
        ]

        with open(
            csv_path,
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=flat_fields,
                extrasaction="ignore",
            )

            writer.writeheader()

            for record in records:
                row = dict(record)
                row["contacts"] = json.dumps(
                    record.get("contacts") or [],
                    ensure_ascii=False,
                )
                row["socials"] = json.dumps(
                    record.get("socials") or {},
                    ensure_ascii=False,
                )
                writer.writerow(row)

        logger.info(
            "Wrote %d records -> %s",
            len(records),
            csv_path,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rivyou Indian Shopify "
            "store discovery pipeline"
        )
    )

    parser.add_argument(
        "--db",
        default="data/rivyou.db",
        help=(
            "SQLite database path "
            "(default: data/rivyou.db)"
        ),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # init
    sub.add_parser(
        "init",
        help="Initialise the SQLite database",
    )

    # seed
    seed_p = sub.add_parser(
        "seed",
        help="Collect candidates from sources into DB",
    )

    seed_p.add_argument(
        "--sources",
        nargs="+",
        choices=[
            "tranco",
            "d2c",
            "commoncrawl",
            "neighbors",
        ],
        metavar="SOURCE",
        help=(
            "Sources to run (default: all). "
            "Choices: tranco d2c commoncrawl neighbors"
        ),
    )

    # verify-shopify
    vs_p = sub.add_parser(
        "verify-shopify",
        help="Run Shopify verifier on candidates",
    )

    vs_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Max domains to verify in this run "
            "(0 = no limit)"
        ),
    )

    vs_p.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help=(
            "Max in-flight HTTP fetches "
            "(default: 50)"
        ),
    )

    # verify-india
    vi_p = sub.add_parser(
        "verify-india",
        help="Run India verifier on Shopify hits",
    )

    vi_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Max domains to verify in this run "
            "(0 = no limit)"
        ),
    )

    vi_p.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help=(
            "Max in-flight HTTP fetches "
            "(default: 50)"
        ),
    )

    # extract
    ex_p = sub.add_parser(
        "extract",
        help=(
            "Extract store fields for "
            "verified Indian stores"
        ),
    )

    ex_p.add_argument(
        "--limit",
        type=int,
        default=0,
        help=(
            "Max stores to extract in this run "
            "(0 = no limit)"
        ),
    )

    # export
    exp_p = sub.add_parser(
        "export",
        help="Export results to CSV / JSON",
    )

    exp_p.add_argument(
        "--format",
        choices=[
            "csv",
            "json",
            "both",
        ],
        default="both",
        help="Output format (default: both)",
    )

    exp_p.add_argument(
        "--status",
        choices=[
            "verified",
            "needs_review",
            "rejected",
        ],
        default=None,
        help="Filter by India verification status",
    )

    exp_p.add_argument(
        "--output",
        default="data/output",
        help=(
            "Output path prefix "
            "(default: data/output)"
        ),
    )

    args = parser.parse_args()

    dispatch = {
        "init": cmd_init,
        "seed": cmd_seed,
        "verify-shopify": cmd_verify_shopify,
        "verify-india": cmd_verify_india,
        "extract": cmd_extract,
        "export": cmd_export,
    }

    asyncio.run(
        dispatch[args.command](args)
    )


if __name__ == "__main__":
    main()