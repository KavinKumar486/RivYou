import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from typing import Optional, Dict, Any

import httpx
from storage import Storage

log = logging.getLogger(__name__)

USER_AGENT = "RivyouBot/0.2 (academic research; contact: rivyou.research@example.com)"
CACHE_DIR = Path("data/cache_bodies")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

class Fetcher:
    def __init__(self, storage: Storage, min_interval: float = 1.0, max_concurrency: int = 50):
        self.storage = storage
        self.min_interval = min_interval
        self._domain_last_request: Dict[str, float] = {}
        self._robots_cache: Dict[str, Optional[RobotFileParser]] = {}
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self._cache_write_lock = asyncio.Lock()   # serialise fetch_cache writes
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=15.0,
            limits=httpx.Limits(max_connections=max_concurrency)
        )

    async def close(self):
        await self.client.aclose()

    def _cache_key(self, url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    async def _throttle(self, domain: str) -> None:
        now = time.monotonic()
        last_req = self._domain_last_request.get(domain, 0)
        wait = self.min_interval - (now - last_req)
        if wait > 0:
            await asyncio.sleep(wait)
        self._domain_last_request[domain] = time.monotonic()

    async def _check_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain in self._robots_cache:
            rp = self._robots_cache[domain]
            return rp.can_fetch(USER_AGENT, url) if rp else True

        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        try:
            await self._throttle(domain)
            async with self.semaphore:
                resp = await self.client.get(robots_url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                rp = RobotFileParser()
                rp.parse(resp.text.splitlines())
                self._robots_cache[domain] = rp
                return rp.can_fetch(USER_AGENT, url)
            self._robots_cache[domain] = None
            return True
        except Exception:
            self._robots_cache[domain] = None
            return True

    async def _get_cached(self, url: str) -> Optional[Dict[str, Any]]:
        url_hash = self._cache_key(url)
        import aiosqlite
        async with aiosqlite.connect(self.storage.db_path, timeout=30.0) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM fetch_cache WHERE url_hash = ?", (url_hash,))
            row = await cursor.fetchone()
            
            if not row:
                return None
                
            body = ""
            body_path = row["body_path"]
            if body_path and Path(body_path).exists():
                with open(body_path, "r", encoding="utf-8") as f:
                    body = f.read()

            return {
                "status": row["status_code"],
                "headers": json.loads(row["headers_json"]),
                "body": body,
                "url": row["url"],
                "fetched_at": row["fetched_at"]
            }

    async def _set_cached(self, url: str, method: str, status_code: int, headers: Dict, body: str) -> None:
        url_hash = self._cache_key(url)
        body_path = ""

        if body:
            path = CACHE_DIR / f"{url_hash}.html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            body_path = str(path)

        fetched_at = time.time()

        import aiosqlite
        async with self.storage._write_lock:
            async with aiosqlite.connect(
                self.storage.db_path, timeout=30.0
            ) as db:
                await db.execute("PRAGMA busy_timeout=30000")
                await db.execute("""
                    INSERT INTO fetch_cache (url_hash, url, method, status_code, headers_json, body_path, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url_hash) DO UPDATE SET
                        url=excluded.url,
                        method=excluded.method,
                        status_code=excluded.status_code,
                        headers_json=excluded.headers_json,
                        body_path=excluded.body_path,
                        fetched_at=excluded.fetched_at
                """, (url_hash, url, method, status_code, json.dumps(headers), body_path, fetched_at))
                await db.commit()

    async def fetch(self, url: str, method: str = "GET", refresh: bool = False) -> Optional[Dict[str, Any]]:
        if not refresh:
            cached = await self._get_cached(url)
            if cached is not None:
                return cached

        if not await self._check_robots(url):
            log.info(f"Robots.txt disallowed fetch for {url}")
            return None

        parsed = urlparse(url)
        domain = parsed.netloc

        for attempt in range(3):
            await self._throttle(domain)
            try:
                async with self.semaphore:
                    resp = await self.client.request(method, url)
                
                body = resp.text[:1_000_000] # max 1MB
                await self._set_cached(url, method, resp.status_code, dict(resp.headers), body)
                
                return {
                    "status": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": body,
                    "url": str(resp.url),
                    "fetched_at": time.time()
                }
            except httpx.HTTPError as e:
                log.debug(f"HTTPError on {url} (attempt {attempt+1}): {e}")
                if attempt == 2:
                    return {
                        "status": -1,
                        "error": str(e),
                        "url": url,
                        "fetched_at": time.time()
                    }
                await asyncio.sleep(2 ** attempt) # Exponential backoff
            except Exception as e:
                log.error(f"Unexpected error fetching {url}: {e}")
                return {
                    "status": -1,
                    "error": str(e),
                    "url": url,
                    "fetched_at": time.time()
                }
