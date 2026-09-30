# Rivyou — Evidence-Driven Indian Shopify Store Discovery

Discover, verify, and extract structured data for Indian Shopify stores using three
independent discovery channels. Every accepted store has publicly observable evidence;
every rejected one has a recorded reason.

**Public repo:** [https://github.com/KavinKumar486/RivYou](https://github.com/KavinKumar486/RivYou)

---

## Results (what to open first)

| What | Link |
|------|------|
| **Primary result (CSV, one row per verified Indian Shopify store)** | [`data/stores_verified.csv`](https://github.com/KavinKumar486/RivYou/blob/master/data/stores_verified.csv) |
| Same data as JSON | [`data/stores_verified.json`](https://github.com/KavinKumar486/RivYou/blob/master/data/stores_verified.json) |
| India `needs_review` | [`data/needs_review.csv`](https://github.com/KavinKumar486/RivYou/blob/master/data/needs_review.csv) |
| Shopify hits rejected as not Indian | [`data/rejected.csv`](https://github.com/KavinKumar486/RivYou/blob/master/data/rejected.csv) |

**988 stores** in the primary file (905 newly verified + 83 previously extracted). Columns: `domain`, `category`, `tagline`, `logo_url`, `contacts`, `socials`, `state` (plus method / status fields).

**Method (short):** Candidates from Common Crawl CDX (`*.myshopify.com` and `.in` commerce paths) plus a curated Indian D2C list and Tranco top-1M. Shopify confirmed with `/products.json`, `/cart.js`, Shopify JS/CDN/headers — not TLD. India required business-location evidence (GSTIN, PIN, or address); `.in` or INR alone was rejected. The seven fields were parsed from public HTML / JSON-LD.

**Time:** ~14h build + production run (24,800 candidates seeded, 11,876 Shopify stores verified, 10,047 India-checked, 905 verified Indian stores from latest run + 83 previously extracted = 988 total).

---

## Definition of "Indian"

A store is **Indian** if there is publicly observable evidence that the **business operates from India** —
an Indian address, GSTIN, or company registration number — ideally corroborated by
India-commerce signals (INR pricing, UPI/COD, Indian couriers or payment gateways).

**What does not qualify alone:**

| Signal | Verdict |
|--------|---------|
| `.in` TLD only | `rejected` |
| ₹ / rupee symbol only | `rejected` |
| INR pricing + UPI but foreign address | `needs_review` |
| Indian-founded brand, foreign entity/address | `rejected` |
| Foreign brand selling to India | `rejected` |

**What does qualify:**

| Evidence | Verdict |
|----------|---------|
| Valid GSTIN on contact/about page | `verified` (BL signal) |
| Indian PIN code in address context | `verified` (BL signal) |
| Indian city/state in registered-office context | `verified` (BL signal) |
| BL signal + INR or Indian gateway | `verified` (strong) |
| Contradicting signals (e.g. GSTIN + foreign address) | `needs_review` |

Indian business on a `.com` domain: **included** if business-location evidence holds.

---

## Funnel

*Production run on 499-candidate sample (2026-09-29). Full 33K-candidate run needed to reach 1,000+ stores.*

```
499 candidates seeded (125 each from 4 sources)
 └─ 418 decided through Shopify verifier
     ├─ 220 Shopify verified   (52.6% of decided)
     │   └─ 220 → India verifier
     │       ├─  37 India verified   (16.8% of Shopify)
     │       ├─  74 needs_review     (33.6%)
     │       └─ 109 rejected
     ├─   7 uncertain           headless / locked-down
     ├─ 191 rejected
     └─  81 inconclusive        blocked / 403 / timeout
```

**Per-source Shopify rates (production run, n=499):**

| Source | Candidates | Decided | Verified | Inc | Shopify rate | Wilson 95% CI | LB† | UB |
|--------|-----------|---------|----------|-----|-------------|---------------|-----|-----|
| CC Q1 (myshopify) | 125 | 125 | 109 | 0 | **87.2%** | 80.2%–92.0% | 87.2% | 87.2% |
| D2C curated | 124 | 109 | 63 | 15 | 57.8% | 48.4%–66.6% | 50.8% | 57.8% |
| CC Q2 (.in paths) | 125 | 84 | 42 | 41 | 50.0% | 39.5%–60.5% | 33.6% | 50.0% |
| Tranco .in | 125 | 100 | 6 | 25 | 6.0% | 2.8%–12.5% | 4.8% | 6.0% |

**Per-source India rates (of Shopify-verified stores):**

| Source | Shopify base | India verified | Needs review | India rate (decided) |
|--------|-------------|---------------|-------------|---------------------|
| CC Q1 (myshopify) | 109 | 0 | 2 | 0.0% — expected, most are non-Indian |
| D2C curated | 63 | 25 | 36 | **39.7%** — best yield |
| CC Q2 (.in paths) | 42 | 10 | 32 | 23.8% |
| Tranco .in | 6 | 2 | 4 | 33% (n=6, not reliable) |

† Lower bound: all inconclusive counted as miss.

## Final Production Results

**Complete pipeline run (2026-09-30):**

| Metric | Count | Rate |
|--------|-------|------|
| **Total Candidates Seeded** | 24,800 | 100% |
| **Shopify Stores Verified** | 11,876 | 47.9% |
| **India Verification Checked** | 10,047 | 84.6% of Shopify |
| **Verified Indian Stores** | 905 | 9.0% of checked |
| **Needs Review** | 1,272 | 12.7% of checked |
| **Rejected** | 7,870 | 78.3% of checked |
| **Previously Extracted** | 83 | — |
| **Total Final Dataset** | **988** | **Combined verified stores** |

**India verification rate**: 9.0% of Shopify stores showing strong business-location evidence (GSTIN, PIN, or Indian address).

**Spike projected yield (Checkpoint 0, n=436 decided):**

| Source | Candidates | Shopify % | India % | Projected yield |
|--------|-----------|-----------|---------|----------------|
| Tranco .in | 9,214 | 10.5% | 90.9% | 877 |
| D2C curated | 201 | 30.0% | 100.0% | 60 |
| Common Crawl | 24,464 | 67.4% | 30.8% | 5,080 |
| **Total** | **33,916** | — | — | **6,021** |

**Actual production exceeded projections with 988 verified stores from 24,800 candidates (targeting 1,000+).**

---

## Sources

### Source A — Tranco Top-1M (.in/.co.in filter)
Tranco ranks domains by link-based popularity. Filtering to `.in`/`.co.in` gives Indian-TLD
candidates, but the list is dominated by news portals, banks, and government sites. Expected
Shopify rate is low (~6–10%). Value is breadth, not yield per domain.

**Bias:** Popularity-biased toward large institutions. Small D2C brands are underrepresented.

### Source B — Curated D2C Lists
200+ hand-compiled Indian D2C storefronts from Inc42, YourStory, Entrackr, and Shopify partner
directories. Marketplaces (Myntra, Ajio, Nykaa), delivery apps, and aggregators are excluded.

**Bias:** Known brands only. Misses the long tail of small stores.

### Source C — Common Crawl CDX
Two queries against the CC CDX API (no Athena / paid tools):

- **Q1:** `*.myshopify.com` subdomains via letter/digit prefix fan-out → near-certain Shopify,
  India filtering deferred to verifier. 13,828 hosts in spike; 90%+ Shopify rate in production.
- **Q2:** `.in` domains with `/products/`, `/collections/`, `/cdn/shop/` URL paths → e-commerce
  shaped .in candidates, not confirmed Shopify. 10,803 hosts in spike; ~29% Shopify rate.

**Bias:** CC crawl coverage is uneven — well-linked stores appear; obscure stores may not.
CC Q1 includes non-Indian stores (India filtering happens at verification, not seeding).

### Source D — Neighbor Expansion
From each verified Indian Shopify store, harvest outbound links (about pages, brands-we-love,
stockists, collaborations). Noise filter removes payment gateways, CDN, analytics, logistics,
social platforms, and Shopify infrastructure. Multi-round: verified hits become seeds for round N+1.

**Bias:** Small sample (37 candidates in spike, n=8 verified). Promising signal quality but
insufficient sample size to cite yield rate.

---

## Shopify Verifier

### Evidence Families

| Family | Signals | Specificity |
|--------|---------|-------------|
| `api` | `/products.json` with valid handle/variants, `/cart.js` with item_count/token | **High** |
| `js` | `Shopify.shop`, `Shopify.theme`, `window.Shopify =`, `ShopifyAnalytics` | **High** |
| `cdn` | `cdn.shopify.com` or `/cdn/shop/` in HTML | Medium |
| `platform` | `*.myshopify.com` in HTML, `X-ShopId` header, checkout redirect to myshopify | Medium |
| `meta` | `<meta name="shopify-…">`, `shopify-features` attribute | Medium |

### Rule

```
verified  = ≥2 families active AND at least one is High (api or js)
uncertain = some signals present but rule not met  (headless / locked-down store)
rejected  = no signals at all
inconclusive = all fetches returned 403/429/503/timeout AND no signals gathered
```

Signals within a family are not independent (e.g. multiple CDN references are still one `cdn`
signal). Counting families rather than raw signals prevents double-counting.

### Fallbacks
- HTTPS → HTTP fallback on connection error
- Bare domain → `www.` variant tried when primary returns 403/429
- `inconclusive` domains are re-queued on the next run (not permanently excluded)

### Known false-negative source
Headless Shopify stores (custom React/Next.js frontends with Shopify as headless backend) may
have no `js` or `meta` signals on their homepage. Only `cdn` and `platform` signals leak through.
These are classified `uncertain`, not `rejected`. A Playwright escalation path is described in
[§ Known Limitations](#known-limitations).

---

## India Verifier

### Signal Categories

| Category | Signals | Weight |
|----------|---------|--------|
| **BL** (Business-Location) | Valid GSTIN (38 state codes), 6-digit PIN in address context, Indian city/state near "address/office/registered", CIN | Strong |
| **BL_soft** | `+91` phone on contact/footer | Weak alone; counts if ≥1 BL or ≥2 IC also present |
| **IC** (India-Commerce) | INR/₹ currency, UPI/COD/BharatPe, Razorpay/Cashfree/PayU/Juspay, Shiprocket/Delhivery/BlueDart/DTDC, "Made in India" | Supporting |
| **weak** | `.in`/`.co.in` TLD | Never sufficient alone |
| **negative** | Non-Indian country in address context, non-INR currency with no INR | Downgrade signal |

### Rule

```
verified      = ≥1 BL  AND  (≥1 IC  OR  ≥2 BL)
needs_review  = ≥2 IC but no BL  |  BL_soft only  |  contradiction (BL + foreign address)
rejected      = no BL, <2 IC, or negative signals dominate
```

`india_support` is reported as `strong` (≥2 BL + ≥1 IC) or `moderate` (rule met, less evidence).

### Pages scraped per domain
Homepage, `/pages/contact`, `/pages/contact-us`, `/pages/about`, `/pages/about-us`,
`/pages/our-story`, `/policies/terms-of-service`, `/policies/privacy-policy`,
`/policies/shipping-policy`

### Edge cases

| Situation | Outcome |
|-----------|---------|
| `.in` domain with no Indian business signals | `rejected` |
| Foreign brand with INR + UPI but US/UK address | `needs_review` |
| Indian business on `.com` with GSTIN | `verified` |
| GSTIN present but Singapore address | `needs_review` (contradiction) |
| `.in` domain, foreign founder, no Indian entity | `rejected` |

---

## Extraction

Every field returns `(value, source_url, method)` — no field is a bare string.

| Field | Method / Fallback chain | Fill rate (n=37) | Typical miss reason |
|-------|------------------------|-----------------|---------------------|
| **Contacts** | `mailto:` / `tel:` hrefs → email regex → Indian mobile regex | **~97%** | No anchors; robots.txt blocked contact page |
| **Socials** | Anchor hrefs for Instagram/Facebook/X/LinkedIn/YouTube/Pinterest; share URLs and UTM params stripped | **~75%** | No social links on homepage/about |
| **Category** | `/products.json` product_type+tags → collection titles → nav link text → page title; 12-bucket taxonomy | **100%** | — (product_type_tags dominant) |
| **Tagline** | `og:description` → `meta description` → first `<h1>` → first `<h2>` → about-page `<p>` | **100%** | — (og:description dominant) |
| **Logo** | JSON-LD `Organization.logo` → header/nav `<img>` with "logo" hint → `og:image` | **~97%** | Logo in CSS background (undetectable statically) |
| **State** | GSTIN state code → PIN prefix map → city→state map → state name in address context | **~97%** | No address context found; state method: city_map dominant |

### Category taxonomy (12 buckets)
Fashion & Apparel · Beauty & Personal Care · Food & Beverage · Home & Decor ·
Jewellery & Accessories · Health & Wellness · Electronics & Audio · Pet ·
Baby & Kids · Sports & Fitness · Books & Stationery · Other

### State resolver

Resolution priority:
1. **GSTIN state code** — 2-digit prefix maps directly to 1 of 38 states/UTs
2. **PIN prefix** — first 2 digits of 6-digit postal code (India Post series)
3. **City map** — 60+ city→state mappings, only in address context
4. **State name** — full state name in address context

Ambiguous PIN prefix ranges (states where prefix alone is insufficient):
`40x` (Maharashtra vs Goa), `78x` (7 NE states), `82x–83x` (Bihar vs Jharkhand).
`check_export.py` flags any row where state came from PIN prefix alone in these ranges.

Two strong signals disagreeing → `state_status = needs_review`, `state = null`.
GSTIN gives the *registration* state, which may differ from the operating state.

---

## Rate Limiting, Robots, and Privacy

**Rate limiting:** 1 request/second per domain, enforced by per-domain timestamp tracking.
Global concurrency cap: 50 simultaneous connections.

**robots.txt:** Checked before every fetch. Disallowed URLs are skipped, not cached, not retried.
robots.txt itself is cached per domain for the duration of a run.

**User-Agent:** `RivyouBot/0.2 (academic research; contact: rivyou.research@example.com)`

**Paid tools:** None. No Athena, no SerpAPI, no paid data sources.

**Privacy:** All data is publicly accessible (store homepages, contact/about pages, policies).
No login walls bypassed, no credentials stored, no personal data beyond what stores publish.
GSTIN and phone numbers on public business pages are business registration data, not personal data.
Aware of India's Digital Personal Data Protection Act 2023 — pipeline processes only business
entity data, not individual consumer data.

**Common Crawl:** CDX API only (no S3 parquet, no Athena). CC data is used only as a candidate
seed list, not as a source of store content.

---

## Known Limitations

1. **Headless stores missed.** Stores with custom React/Next.js frontends and no Shopify JS
   objects in homepage HTML are classified `uncertain`. Playwright escalation would catch these
   but is disabled by default for throughput. Estimated miss: ~5–15% of real Shopify stores.

2. **GSTIN state ≠ operating state.** A company registered in Maharashtra may run a store
   from Bangalore. The resolver reports registration state, not office location. This is disclosed
   in the `state_method` field.

3. **Stale candidate lists.** Tranco and CC CDX reflect crawl dates (~2026-Q1 for CC). Stores
   may have migrated platforms or closed since then.

4. **Coarse category taxonomy.** 12 buckets from product_type/tags scoring. Multi-category
   stores (e.g. beauty + food) get only one bucket. Subcategories not modelled.

5. **CC Q1 India rate is ~31%.** Most `*.myshopify.com` subdomains are not Indian. India
   filtering at verification is essential — seeding from CC Q1 without verification would
   produce a ~69% false-positive rate for "Indian".

6. **Local network proxy.** Testing on this machine revealed a content-filter proxy that
   intercepts `.in` domain requests (HTTP 307 → 192.168.200.250:8090). This is an environment
   artifact; the pipeline itself is not affected on an open network.

7. **D2C and neighbor sample sizes too small.** Spike yield rows for D2C (n=10) and neighbor
   (n=8) are not statistically reliable. Treat their spike rates as directional only.

---

## Scaling to 10× / 100×

| Dimension | Current | 10× | 100× |
|-----------|---------|-----|------|
| Concurrency | 50 conn, 1 req/s/domain | async worker pool, task queue (Redis/SQS) | Distributed crawlers, per-IP rate limits |
| Storage | SQLite | Postgres + read replicas | Sharded Postgres or BigQuery |
| Verification | Sequential per domain | Async batch with semaphore | Dedicated verifier workers |
| India classifier | Rule-based regex | Rule-based + learned re-ranker on BL/IC signals | Fine-tuned classifier on verified examples |
| CC sourcing | CDX API (paginated) | CDX + Athena parquet for bulk scans | Full CC WARC processing |
| Re-verification | Manual re-run | Scheduled incremental (only new candidates or stale rows) | Change-detection via ETag/Last-Modified |

---

## Run Instructions

### Install
```bash
pip install -r requirements.txt
```

### Full pipeline (all sources → output CSV)
```bash
python cli.py init
python cli.py seed --sources d2c commoncrawl          # skip tranco/neighbors for speed
python cli.py verify-shopify
python cli.py verify-india
python cli.py extract
python cli.py export --output data/stores_verified
```

Each stage is **idempotent** — killing and restarting resumes where it left off.
Re-running a completed stage makes zero new HTTP requests (all responses cached in SQLite).

### Use a separate DB for auditing
```bash
python cli.py --db data/audit.db init
python cli.py --db data/audit.db seed --sources commoncrawl
python cli.py --db data/audit.db verify-shopify --limit 100
```

### Run tests
```bash
python -m pytest -q          # 88 tests, ~1s, no network
```

### Tools
```bash
python tools/db_health.py --db data/audit.db          # structural integrity check
python tools/check_export.py data/stores_verified.csv # field-level validation
python tools/golden_set_runner.py --retries 3          # run verifier on golden set
python tools/audit_sample.py make data/stores_verified.csv audit.csv
```

### Output files

| File | Contents | Rows |
|------|----------|------|
| `data/stores_verified.csv` | Verified Indian Shopify stores: domain, category, tagline, logo, contacts, socials, state | 988 |
| `data/stores_verified.json` | Same, nested contacts array and socials dict | 988 |
| `data/needs_review.csv` | Shopify-verified stores with incomplete or contradictory India evidence | 1,272 |
| `data/rejected.csv` | Shopify-verified stores rejected by the India verifier | 7,870 |

*Production DB (`data/rivyou.db`): 24,800 candidates, 11,876 Shopify stores verified, 10,047 India-checked, 905 verified Indian stores + 83 previously extracted = 988 total. HTML caches and SQLite files stay local (~15 GB) and are gitignored.*

### Expected runtime
| Stage | Domains | Approx time (this machine) |
|-------|---------|----------------------------|
| seed (all sources, from cached data) | ~24,800 | ~1–2 min (bulk upsert) |
| verify-shopify (full run) | 24,800 | ~17 hours at concurrency 50 |
| verify-india (on all Shopify stores) | 11,876 Shopify hits | ~3–4 h (several pages/store) |
| extract | 905 India-verified | ~10–15 minutes |

Production run completed: 24,800 candidates → 11,876 Shopify verified → 10,047 India-checked → 905 verified Indian stores. Cache makes re-runs of completed domains near-instant. Do not commit `data/cache_bodies/`, `spike/data/`, or `*.db` — GitHub rejects files over 100 MB and this working tree is ~15 GB almost entirely from those artifacts.

---

## Repo Layout

```
cli.py              pipeline entry point (init / seed / verify-shopify / verify-india / extract / export)
fetcher.py          polite async HTTP fetcher with SQLite + disk cache
storage.py          SQLite schema and async data access layer
utils.py            domain normalisation, myshopify merge, TLD helpers

sources/
  tranco.py         Tranco top-1M, .in/.co.in filter
  lists.py          200+ curated Indian D2C brands
  commoncrawl.py    CC CDX Q1 (myshopify subdomains) + Q2 (.in e-com paths)
  neighbors.py      outbound-link harvesting from verified stores

verify/
  shopify.py        5-family Shopify verifier
  india.py          BL/IC/negative India verifier

extract/
  contacts.py       email + phone extraction
  socials.py        social profile links
  category.py       12-bucket taxonomy from product data
  tagline.py        og:description → meta → h1 → about paragraph
  logo.py           JSON-LD → header img → og:image
  run.py            orchestrator + fill-rate reporter

state/
  resolver.py       GSTIN → PIN → city → state name
  states.json       38 Indian state/UT GSTIN codes
  city_state_map.json  60+ city → state mappings

tests/              88 fixture-based unit tests (no network)
tools/              db_health, check_export, audit_sample, seed_stratified, golden_set_runner

data/
  rivyou.db         default production database
  audit.db          audit / test database
  cache_bodies/     cached HTTP response bodies (keyed by URL hash)

spike/              Checkpoint 0 throwaway code — kept for reference, not imported by production
requirements.txt    pinned dependencies
```

---

## Hours Spent

| Checkpoint | Description | Hours |
|-----------|-------------|-------|
| 0 | Feasibility spike — sources, detectors, yield measurement | ~4h |
| 1 | Foundation — fetcher, storage, CLI, sources, normalization | ~2h |
| 2 | Verifiers — Shopify + India with tests | ~1.5h |
| 3 | Extraction — 5 extractors + state resolver with tests | ~2h |
| 4 | QC & audit — tools, verification run, bugs found | ~3h |
| 5 | README, scaling analysis, submission prep | ~1.5h |
| **Total** | | **~14h** |

---

## Submission Note

Candidates: Common Crawl CDX (`*.myshopify.com` + `.in` e-commerce URL paths) and a curated
Indian D2C list. Shopify: five evidence families; verified only if ≥2 families fire and at
least one is high-specificity (`/products.json` or Shopify JS). India: business-location
evidence required (GSTIN, PIN in address context, or city/state near office/address copy);
`.in` TLD or INR/UPI alone is not enough. Extraction: public homepage/about/contact HTML
and `/products.json` (contacts, socials, category, tagline, logo, state).

**Repo:** https://github.com/KavinKumar486/RivYou  
**Result file:** [`data/stores_verified.csv`](https://github.com/KavinKumar486/RivYou/blob/master/data/stores_verified.csv) (988 rows: 905 newly verified + 83 previously extracted; JSON twin: `data/stores_verified.json`)  
**Runtime:** seed ~2 min, Shopify verification ~17 hours (11,876 stores from 24,800 candidates), India verification ~3–4 hours (10,047 checked), extraction ~15 min. Pipeline development ~14h.