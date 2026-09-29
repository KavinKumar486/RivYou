import aiosqlite
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, db_path: str = "data/rivyou.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()

    async def init_db(self):
        """Initialize / migrate the SQLite schema."""
        async with aiosqlite.connect(self.db_path) as db:
            # WAL mode: allows concurrent reads + one writer without blocking fetcher
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS candidates (
                    domain           TEXT PRIMARY KEY,
                    source           TEXT,
                    first_seen       TEXT,
                    canonical_domain TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS stores (
                    domain          TEXT PRIMARY KEY,
                    is_shopify      BOOLEAN,
                    shopify_verdict TEXT,
                    is_india        BOOLEAN,
                    india_verdict   TEXT,
                    india_support   TEXT,
                    inconclusive    BOOLEAN DEFAULT FALSE,
                    verified_at     TEXT
                )
            """)

            for col, typedef in [
                ("shopify_verdict", "TEXT"),
                ("india_verdict", "TEXT"),
                ("india_support", "TEXT"),
            ]:
                try:
                    await db.execute(
                        f"ALTER TABLE stores ADD COLUMN {col} {typedef}"
                    )
                except Exception:
                    pass

            await db.execute("""
                CREATE TABLE IF NOT EXISTS evidence (
                    domain        TEXT,
                    check_type    TEXT,
                    evidence_json TEXT,
                    PRIMARY KEY (domain, check_type)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS fetch_cache (
                    url_hash     TEXT PRIMARY KEY,
                    url          TEXT,
                    method       TEXT,
                    status_code  INTEGER,
                    headers_json TEXT,
                    body_path    TEXT,
                    fetched_at   TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    run_id     TEXT PRIMARY KEY,
                    start_time TEXT,
                    end_time   TEXT,
                    command    TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS extracted (
                    domain          TEXT PRIMARY KEY,
                    contacts_json   TEXT,
                    socials_json    TEXT,
                    category        TEXT,
                    category_method TEXT,
                    tagline         TEXT,
                    tagline_method  TEXT,
                    logo_url        TEXT,
                    logo_local_path TEXT,
                    logo_source     TEXT,
                    state           TEXT,
                    state_method    TEXT,
                    state_status    TEXT,
                    extracted_at    TEXT
                )
            """)

            await db.commit()
            logger.info("Database initialized.")

    # ── candidates ────────────────────────────────────────────────────────────

    async def get_candidate(self, domain: str) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT * FROM candidates WHERE domain = ?",
                (domain,),
            )

            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_candidate(
        self,
        domain: str,
        source: str,
        canonical_domain: Optional[str] = None,
    ):
        first_seen = datetime.utcnow().isoformat() + "Z"

        async with self._write_lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO candidates (
                        domain,
                        source,
                        first_seen,
                        canonical_domain
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(domain) DO NOTHING
                """, (
                    domain,
                    source,
                    first_seen,
                    canonical_domain,
                ))

                await db.commit()

    async def save_candidates_bulk(
        self,
        rows: List[tuple],
    ) -> int:
        """Insert (domain, source) rows. Existing domains are skipped.

        Returns the number of newly inserted rows.
        """
        if not rows:
            return 0

        first_seen = datetime.utcnow().isoformat() + "Z"
        payload = [
            (domain, source, first_seen, None)
            for domain, source in rows
        ]

        async with self._write_lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM candidates"
                )
                before = (await cursor.fetchone())[0]

                await db.executemany("""
                    INSERT INTO candidates (
                        domain,
                        source,
                        first_seen,
                        canonical_domain
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(domain) DO NOTHING
                """, payload)

                await db.commit()

                cursor = await db.execute(
                    "SELECT COUNT(*) FROM candidates"
                )
                after = (await cursor.fetchone())[0]

        return after - before

    async def get_all_candidates(self) -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT domain FROM candidates"
            )

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_unverified_candidates(self) -> List[str]:
        """Candidates with no store row, or marked inconclusive."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT c.domain
                FROM candidates c
                LEFT JOIN stores s ON c.domain = s.domain
                WHERE s.domain IS NULL
                   OR s.inconclusive = 1
            """)

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_candidates_without_store(self) -> List[str]:
        """Candidates that have never been written to stores (no retries)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT c.domain
                FROM candidates c
                LEFT JOIN stores s ON c.domain = s.domain
                WHERE s.domain IS NULL
            """)

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_shopify_hits(self) -> List[str]:
        """Confirmed Shopify stores not yet India-verified."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT domain
                FROM stores
                WHERE is_shopify = 1
                  AND inconclusive = 0
                  AND (
                      is_india IS NULL
                      OR india_verdict IS NULL
                  )
            """)

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_verified_indian_stores(self) -> List[str]:
        """Confirmed Shopify + India stores not yet extracted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT s.domain
                FROM stores s
                LEFT JOIN extracted e ON s.domain = e.domain
                WHERE s.is_shopify = 1
                  AND s.is_india = 1
                  AND s.inconclusive = 0
                  AND e.domain IS NULL
            """)

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    # ── store verification ───────────────────────────────────────────────────

    async def save_store_verification(
        self,
        domain: str,
        is_shopify: bool,
        is_india: Optional[bool],
        inconclusive: bool = False,
        evidence: Optional[Dict] = None,
        shopify_verdict: Optional[str] = None,
        india_verdict: Optional[str] = None,
        india_support: Optional[str] = None,
    ):
        verified_at = datetime.utcnow().isoformat() + "Z"

        async with self._write_lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO stores (
                        domain,
                        is_shopify,
                        shopify_verdict,
                        is_india,
                        india_verdict,
                        india_support,
                        inconclusive,
                        verified_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                        is_shopify      = excluded.is_shopify,
                        shopify_verdict = excluded.shopify_verdict,
                        is_india        = excluded.is_india,
                        india_verdict   = excluded.india_verdict,
                        india_support   = excluded.india_support,
                        inconclusive    = excluded.inconclusive,
                        verified_at     = excluded.verified_at
                """, (
                    domain,
                    is_shopify,
                    shopify_verdict,
                    is_india,
                    india_verdict,
                    india_support,
                    inconclusive,
                    verified_at,
                ))

                if evidence:
                    for check_type in ("shopify", "india"):
                        if check_type in evidence:
                            await db.execute("""
                                INSERT INTO evidence (
                                    domain,
                                    check_type,
                                    evidence_json
                                )
                                VALUES (?, ?, ?)
                                ON CONFLICT(domain, check_type)
                                DO UPDATE SET
                                    evidence_json = excluded.evidence_json
                            """, (
                                domain,
                                check_type,
                                json.dumps(evidence[check_type]),
                            ))

                await db.commit()

    async def save_india_verification(
        self,
        domain: str,
        is_india: bool,
        india_verdict: str,
        india_support: str,
        evidence: list,
    ):
        """Update only India columns — never touches shopify_verdict."""
        verified_at = datetime.utcnow().isoformat() + "Z"

        async with self._write_lock:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                await db.execute("PRAGMA busy_timeout=30000")
                await db.execute("""
                    UPDATE stores SET
                        is_india      = ?,
                        india_verdict = ?,
                        india_support = ?,
                        verified_at   = ?
                    WHERE domain = ?
                """, (
                    is_india,
                    india_verdict,
                    india_support,
                    verified_at,
                    domain,
                ))

                if evidence:
                    await db.execute("""
                        INSERT INTO evidence (
                            domain,
                            check_type,
                            evidence_json
                        )
                        VALUES (?, 'india', ?)
                        ON CONFLICT(domain, check_type)
                        DO UPDATE SET
                            evidence_json = excluded.evidence_json
                    """, (
                        domain,
                        json.dumps(evidence),
                    ))

                await db.commit()

    # ── extracted fields ──────────────────────────────────────────────────────

    async def save_extracted(self, domain: str, fields: Dict):
        extracted_at = datetime.utcnow().isoformat() + "Z"

        async with self._write_lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO extracted (
                        domain,
                        contacts_json,
                        socials_json,
                        category,
                        category_method,
                        tagline,
                        tagline_method,
                        logo_url,
                        logo_local_path,
                        logo_source,
                        state,
                        state_method,
                        state_status,
                        extracted_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(domain) DO UPDATE SET
                        contacts_json   = excluded.contacts_json,
                        socials_json    = excluded.socials_json,
                        category        = excluded.category,
                        category_method = excluded.category_method,
                        tagline         = excluded.tagline,
                        tagline_method  = excluded.tagline_method,
                        logo_url        = excluded.logo_url,
                        logo_local_path = excluded.logo_local_path,
                        logo_source     = excluded.logo_source,
                        state           = excluded.state,
                        state_method    = excluded.state_method,
                        state_status    = excluded.state_status,
                        extracted_at    = excluded.extracted_at
                """, (
                    domain,
                    json.dumps(fields.get("contacts") or []),
                    json.dumps(fields.get("socials") or {}),
                    fields.get("category"),
                    fields.get("category_method"),
                    fields.get("tagline"),
                    fields.get("tagline_method"),
                    fields.get("logo_url"),
                    fields.get("logo_local_path"),
                    fields.get("logo_source"),
                    fields.get("state"),
                    fields.get("state_method"),
                    fields.get("state_status"),
                    extracted_at,
                ))

                await db.commit()

    async def get_all_extracted(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                "SELECT * FROM extracted"
            )

            rows = await cursor.fetchall()

            result = []

            for row in rows:
                r = dict(row)

                r["contacts"] = json.loads(
                    r.pop("contacts_json") or "[]"
                )

                r["socials"] = json.loads(
                    r.pop("socials_json") or "{}"
                )

                result.append(r)

            return result

    async def get_export_records(
        self,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get records for export.

        If status is None, preserve existing behavior and
        return extracted records only.

        If status is provided, filter by stores.india_verdict
        and include extracted fields when available.
        """

        if status is None:
            return await self.get_all_extracted()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    s.domain,
                    s.india_verdict,
                    e.contacts_json,
                    e.socials_json,
                    e.category,
                    e.category_method,
                    e.tagline,
                    e.tagline_method,
                    e.logo_url,
                    e.logo_local_path,
                    e.logo_source,
                    e.state,
                    e.state_method,
                    e.state_status,
                    e.extracted_at
                FROM stores s
                LEFT JOIN extracted e
                    ON s.domain = e.domain
                WHERE s.india_verdict = ?
                ORDER BY s.domain
            """, (status,))

            rows = await cursor.fetchall()

            result = []

            for row in rows:
                r = dict(row)

                r["contacts"] = json.loads(
                    r.pop("contacts_json") or "[]"
                )

                r["socials"] = json.loads(
                    r.pop("socials_json") or "{}"
                )

                result.append(r)

            return result