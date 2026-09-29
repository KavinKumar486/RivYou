import sqlite3, sys
db = sys.argv[1] if len(sys.argv) > 1 else "data/audit.db"
c = sqlite3.connect(db)
st  = c.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
fc  = c.execute("SELECT COUNT(*) FROM fetch_cache").fetchone()[0]
vd  = dict(c.execute("SELECT shopify_verdict,COUNT(*) FROM stores GROUP BY shopify_verdict").fetchall())
inc = c.execute("SELECT COUNT(*) FROM stores WHERE inconclusive=1").fetchone()[0]
ind = dict(c.execute("SELECT india_verdict,COUNT(*) FROM stores WHERE india_verdict IS NOT NULL GROUP BY india_verdict").fetchall())
ext = c.execute("SELECT COUNT(*) FROM extracted").fetchone()[0]
print(f"stores={st}  fc={fc}  inc={inc}")
print(f"shopify: {vd}")
print(f"india:   {ind}")
print(f"extracted: {ext}")
c.close()
