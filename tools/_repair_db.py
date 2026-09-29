"""Repair rows where verify-india wiped shopify_verdict via the old buggy code."""
import sqlite3, sys

db = sys.argv[1] if len(sys.argv) > 1 else "data/audit.db"
c = sqlite3.connect(db)

# All rows with NULL shopify_verdict but is_shopify=1 are confirmed Shopify
# (verify-india only runs on stores that passed verify-shopify)
fixed = c.execute(
    "UPDATE stores SET shopify_verdict='verified', inconclusive=0 "
    "WHERE shopify_verdict IS NULL AND is_shopify=1"
).rowcount
c.commit()
print(f"Fixed {fixed} corrupted rows")

nulls = c.execute("SELECT COUNT(*) FROM stores WHERE shopify_verdict IS NULL").fetchone()[0]
vd    = dict(c.execute("SELECT shopify_verdict,COUNT(*) FROM stores GROUP BY shopify_verdict").fetchall())
ind   = dict(c.execute("SELECT india_verdict,COUNT(*) FROM stores WHERE india_verdict IS NOT NULL GROUP BY india_verdict").fetchall())
print(f"Remaining NULLs: {nulls}")
print(f"Shopify verdicts: {vd}")
print(f"India verdicts so far: {ind}")
c.close()
