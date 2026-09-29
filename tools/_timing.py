"""Show inter-request timing from fetch_cache to confirm burst vs serial pattern."""
import sqlite3, sys
db = sys.argv[1] if len(sys.argv) > 1 else "data/burst_test.db"
c = sqlite3.connect(db)
rows = c.execute("SELECT CAST(fetched_at AS REAL) FROM fetch_cache ORDER BY fetched_at LIMIT 30").fetchall()
times = [r[0] for r in rows]
if len(times) < 2:
    print("Not enough data")
    sys.exit(0)
print(f"{'Gap':>8}  timestamp")
print("-" * 40)
for i, t in enumerate(times[:20]):
    gap = t - times[i-1] if i > 0 else 0
    print(f"{gap:>8.3f}s  {t:.3f}")
print(f"\nFirst {min(20,len(times))} fetches in {times[min(19,len(times)-1)] - times[0]:.2f}s")
print(f"Avg gap: {(times[min(19,len(times)-1)] - times[0]) / (min(20,len(times))-1):.3f}s")
c.close()
