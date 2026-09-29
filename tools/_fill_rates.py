"""Compute real field fill rates from stores_verified.json"""
import json, sys
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "data/stores_verified.json"
records = json.loads(Path(path).read_text(encoding="utf-8"))
n = len(records)

fields = [
    ("contacts",  lambda r: bool(r.get("contacts"))),
    ("socials",   lambda r: bool(r.get("socials"))),
    ("category",  lambda r: bool(r.get("category") and r["category"] != "Other")),
    ("tagline",   lambda r: bool(r.get("tagline"))),
    ("logo_url",  lambda r: bool(r.get("logo_url"))),
    ("state",     lambda r: r.get("state_status") == "resolved"),
]

print(f"\nFill rates — {n} extracted records\n")
print(f"{'Field':<12} {'Filled':>7} {'Total':>7} {'Rate':>7}  Method breakdown")
print("-" * 70)

for field, check in fields:
    filled = sum(1 for r in records if check(r))
    rate   = filled / n if n else 0

    # method breakdown
    if field == "state":
        methods = {}
        for r in records:
            if check(r):
                m = r.get("state_method", "unknown")
                methods[m] = methods.get(m, 0) + 1
    elif field == "category":
        methods = {}
        for r in records:
            if check(r):
                m = r.get("category_method", "unknown")
                methods[m] = methods.get(m, 0) + 1
    elif field == "tagline":
        methods = {}
        for r in records:
            if check(r):
                m = r.get("tagline_method", "unknown")
                methods[m] = methods.get(m, 0) + 1
    elif field == "logo_url":
        methods = {}
        for r in records:
            if check(r):
                m = r.get("logo_source", "unknown")[:30]
                methods["logo_source"] = methods.get("logo_source", 0) + 1
    else:
        methods = {}

    method_str = "  ".join(f"{k}:{v}" for k,v in sorted(methods.items(), key=lambda x:-x[1])[:3])
    print(f"{field:<12} {filled:>7} {n:>7} {rate:>7.1%}  {method_str}")

# Category distribution
print("\nCategory distribution:")
cats = {}
for r in records:
    c = r.get("category") or "None"
    cats[c] = cats.get(c, 0) + 1
for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"  {cat:<30} {count}")

# State distribution
print("\nState distribution (resolved):")
states = {}
for r in records:
    if r.get("state_status") == "resolved":
        s = r.get("state") or "None"
        states[s] = states.get(s, 0) + 1
for st, count in sorted(states.items(), key=lambda x: -x[1]):
    print(f"  {st:<30} {count}")

print("\nState method breakdown (all records):")
smethods = {}
for r in records:
    m = r.get("state_method") or "none"
    smethods[m] = smethods.get(m, 0) + 1
for m, count in sorted(smethods.items(), key=lambda x: -x[1]):
    print(f"  {m:<25} {count}")
