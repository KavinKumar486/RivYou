"""Export needs_review.csv and rejected.csv alongside stores_verified.csv."""
import sqlite3, csv, json, sys
from pathlib import Path

db = sys.argv[1] if len(sys.argv) > 1 else "data/audit.db"
out_dir = Path("data")
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row

# needs_review
rows = c.execute("""
    SELECT s.domain, s.shopify_verdict, s.india_verdict, s.india_support, s.verified_at
    FROM stores s
    WHERE s.india_verdict = 'needs_review'
    ORDER BY s.domain
""").fetchall()

with open(out_dir / "needs_review.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["domain","shopify_verdict","india_verdict","india_support","verified_at"])
    w.writeheader()
    w.writerows([dict(r) for r in rows])
print(f"needs_review.csv: {len(rows)} rows")

# rejected (India stage only — already confirmed Shopify)
rows = c.execute("""
    SELECT s.domain, s.shopify_verdict, s.india_verdict, s.verified_at
    FROM stores s
    WHERE s.shopify_verdict = 'verified' AND s.india_verdict = 'rejected'
    ORDER BY s.domain
""").fetchall()

with open(out_dir / "rejected.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["domain","shopify_verdict","india_verdict","verified_at"])
    w.writeheader()
    w.writerows([dict(r) for r in rows])
print(f"rejected.csv: {len(rows)} rows")

# inconclusive
rows = c.execute("""
    SELECT s.domain, s.shopify_verdict, s.inconclusive, s.verified_at
    FROM stores s
    WHERE s.inconclusive = 1
    ORDER BY s.domain
""").fetchall()

with open(out_dir / "inconclusive.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["domain","shopify_verdict","inconclusive","verified_at"])
    w.writeheader()
    w.writerows([dict(r) for r in rows])
print(f"inconclusive.csv: {len(rows)} rows")

c.close()
print("\nAll output files written to data/")
