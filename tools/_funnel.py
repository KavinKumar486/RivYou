"""Quick funnel report from the DB."""
import sqlite3, sys, math

db = sys.argv[1] if len(sys.argv) > 1 else "data/audit.db"
c = sqlite3.connect(db)

print("\n=== Per-source Shopify funnel ===")
rows = c.execute("""
    SELECT c.source,
           SUM(CASE WHEN s.shopify_verdict='verified'  AND s.inconclusive=0 THEN 1 ELSE 0 END) as verified,
           SUM(CASE WHEN s.shopify_verdict='uncertain' AND s.inconclusive=0 THEN 1 ELSE 0 END) as uncertain,
           SUM(CASE WHEN s.shopify_verdict='rejected'  AND s.inconclusive=0 THEN 1 ELSE 0 END) as rejected,
           SUM(CASE WHEN s.inconclusive=1                                    THEN 1 ELSE 0 END) as inconclusive,
           COUNT(*) as total_decided
    FROM stores s JOIN candidates c ON s.domain=c.domain
    GROUP BY c.source ORDER BY c.source
""").fetchall()

def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = k/n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    margin = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / denom
    return (max(0, center-margin), min(1, center+margin))

print(f"{'Source':<20} {'Ver':>5} {'Unc':>5} {'Rej':>5} {'Inc':>5} {'Decided':>7} {'Rate':>7} {'95% CI':>16} {'LB':>7} {'UB':>7}")
print("-"*100)
for src, ver, unc, rej, inc, tot in rows:
    decided = ver + unc + rej
    rate = ver/decided if decided else 0
    lo, hi = wilson(ver, decided) if decided else (0,0)
    # lower bound: all inconclusive = miss
    total = decided + inc
    lb = ver/total if total else 0
    # upper bound: inconclusive at same rate
    ub = rate
    print(f"{src:<20} {ver:>5} {unc:>5} {rej:>5} {inc:>5} {decided:>7} {rate:>7.1%} [{lo:.1%}–{hi:.1%}] {lb:>7.1%} {ub:>7.1%}")

print("\n=== India funnel (so far) ===")
ind_rows = c.execute("""
    SELECT c.source,
           SUM(CASE WHEN s.india_verdict='verified'     THEN 1 ELSE 0 END) as ind_ver,
           SUM(CASE WHEN s.india_verdict='needs_review' THEN 1 ELSE 0 END) as ind_nr,
           SUM(CASE WHEN s.india_verdict='rejected'     THEN 1 ELSE 0 END) as ind_rej,
           SUM(CASE WHEN s.shopify_verdict='verified' AND s.inconclusive=0 THEN 1 ELSE 0 END) as shopify_ver
    FROM stores s JOIN candidates c ON s.domain=c.domain
    WHERE s.shopify_verdict='verified'
    GROUP BY c.source ORDER BY c.source
""").fetchall()

print(f"{'Source':<20} {'IndVer':>7} {'NeedsRev':>9} {'IndRej':>7} {'ShopVer':>8} {'India%':>7}")
print("-"*70)
for src, iv, nr, ir, sv in ind_rows:
    decided = iv + nr + ir
    rate = iv/decided if decided else 0
    print(f"{src:<20} {iv:>7} {nr:>9} {ir:>7} {sv:>8} {rate:>7.1%}")

c.close()
