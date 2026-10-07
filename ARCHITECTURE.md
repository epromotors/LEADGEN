# TEB Solutions LeadGen OS — Architecture & Flow Guide

> **Who this is for:** Anyone — business owner, developer, or AI agent —
> who wants to understand how this system works, what talks to what,
> and how information flows through it.
>
> **Current version:** v5.1.0 — Outreach Design Redesign, Inbox Email 2 Modal, Network Ports Migration & Reset Utilities (October 2026)
>
> **Last updated:** October 7, 2026 (v5.1.0 — Email 1 Redesign, Inbox Email 2 Modal, Ports 8001/5174, Reset Utility)

---

## The Big Picture (Plain English)

Think of this system as a **smart sales assistant** that:

```
You give it a list → It researches each business → It sends the right email
                           ↕
              You can pause & resume anytime
              All progress is saved and logged
```

```
┌─────────────────────────────────────────────────────────────────┐
│                    YOUR COMPUTER                                │
│                                                                 │
│  ┌───────────────┐          ┌─────────────────────────────┐    │
│  │  Web Browser  │◄────────►│  React App  (port 5174)     │    │
│  │  (your UI)    │          │  5 pages, live polling 8s   │    │
│  └───────────────┘          └──────────────┬──────────────┘    │
│                                            │ talks via HTTP     │
│                                            │ (Vite proxy /api)  │
│                                            ▼                    │
│                             ┌─────────────────────────────┐    │
│                             │  FastAPI Server (port 8001) │    │
│                             │  The brain of the system    │    │
│                             └──────────────┬──────────────┘    │
│                                            │                    │
│                    ┌───────────────────────┼──────────────┐    │
│                    ▼                       ▼              ▼    │
│          ┌─────────────┐      ┌────────────────┐  ┌──────────┐ │
│          │ PostgreSQL  │      │ Internet        │  │Hostinger │ │
│          │ Database    │      │ (audit websites)│  │1000/day  │ │
│          │ (6 tables)  │      │                │  │(rotate   │ │
│          └─────────────┘      └────────────────┘  │ senders) │ │
│                                                   └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 1: The Three Layers

### Layer 1 — The Interface (Frontend)
**React app** running at `http://localhost:5174` (Vite dev server)

What the user sees and clicks:
- Dashboard with KPI counters
- Leads table: checkboxes, bulk operations, ✏️ Edit Modal, ⚠️ scraped tagline warnings
- Edit Modal: inline field editing + **AI name suggestion banner** (auto-loads `suggested_name`)
- SEO Audit results: expandable rows, 11-axis score rings, PDF download
- Campaign page: pause/resume buttons, live countdown timer, expandable per-email logs
- Test Email panel (floating card, bottom-right + direct API test)
- **Converted Leads Inbox (v5.1.0)** — View positive replies, one-click Sync, and **Email 2 Compose & Preview Modal** with live HTML preview, template editor, and PDF attachment
- **Email Review page** — scan for domain-matched email mismatches across all leads; accept/dismiss corrections
- Activity log with timezone-corrected timestamps
- Sidebar navigation with real-time green badge for converted leads and orange badge for pending email reviews

### Layer 2 — The Brain (Backend)
**FastAPI server** running at `http://localhost:8001`

Does all the real work:
- Stores and retrieves data from PostgreSQL
- AI business name extraction during audits (`og:site_name` → JSON-LD → `<title>`)
- Website classification: **13-layer classifier v5** before audit
  - **4-variant URL chain** per domain: `https://www. → https:// → http://www. → http://`
  - **SPA/JS-framework detection** — React, Next.js, Vue, Angular sites pass immediately
  - Structural threshold lowered: 8000 → 2000 chars
- **55-factor SEO, UX & Local audit** (ReportLab PDF, multi-section, **11 performance axes**)
- PDF report generation
- **Branded Email 1 Outreach (v5.1.0)** — Modern 600px card container, `#0d1b2a` navy header, TEB Solutions logo banner, service pill, 4 usability pillars, live portfolio proof strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 dashed check grid, low-friction informational closing, and curiosity-gap spintax subjects
- **Converted Leads Follow-Up (Email 2)** — `GET /api/replies/preview-email2/{id}`, `POST /api/replies/send-email2/{id}` with custom HTML/subject override and PDF attachment
- **Direct Test Email API** — `POST /api/campaigns/send-test` for pre-campaign template verification
- **Hostinger 1000/day limit & multi-sender rotation** — tracks daily volume and pauses safely when all accounts hit capacity
- Email sending with pause/resume, 7-day skip, randomized 60–90s delays, per-email logging
- **`logger.py`** — IST-aware `TimedRotatingFileHandler`; `logs/leadgen.log`; 3-day retention
- **`POST /api/logs/frontend`** — batches JS errors from React UI into server log file
- **Semaphore-based batch audit processing** — `Semaphore(3)` rolling queue, `_BATCH_RUNNING` guard, 409 on double-trigger
- **Data Sanitization & Normalization (v4.3.1)**
  - **URL Root Trimming** — Strips internal paths from website URLs (e.g., `domain.com/page` → `domain.com/`) during import.
  - **Business Name Cleaning** — Truncates names at the first ` - ` or ` | ` separator to remove taglines/suffixes.
  - **Bulk Maintenance Endpoints** — Manual triggers to clean existing database records (`/clean-urls` and `/clean-names`).
- **Micro-session DB pattern** — connections released during long I/O (crawl/PDF generation)
- DB pool: 20 base + 40 overflow connections
- **Campaign readiness enforcement (v4.3.2)** - Fresh campaign leads require `audits.status = done`; the UI only selects successful audits and the backend rejects campaign creation when selected leads are missing a completed audit.
- **Safe Reset Utility (v5.1.0)** — `reset_leads_to_fresh.py` clears tracking timestamps, recovers stale running audits, and resyncs lead statuses with audit completion.

### Layer 3 — The Storage (Database)
**PostgreSQL** at `localhost:5432`, database: `leadgen`

6 tables:

Performance maintenance (v4.3.2):
- `pg_trgm` is enabled for faster partial search on lead names and emails.
- Hot-path indexes exist for lead status/search, audit status/site-status filters, campaign logs, activity logs, reply filters, and email review filters.
- After bulk DB cleanup or large imports, run `VACUUM (ANALYZE)` on core tables so PostgreSQL refreshes planner statistics.

- `leads` — every business contact (+`last_emailed_at`)
- `audits` — SEO check results (+`suggested_name` for AI-extracted clean name)
- `campaigns` — email batches (+`pending_lead_ids`, `next_email_at`, `paused_at`, `skipped_count`, `failed_count`)
- `campaign_email_logs` — per-email audit trail (sent / failed / skipped per campaign)
- `activity_log` — record of everything that happened
- **`email_corrections`** — detected domain-matched email mismatches awaiting admin review ← NEW v4.3.0

---

## Part 2: The Website Checker (13-Layer Pipeline + 4-Variant URL — v5)

Before auditing, the site is classified. **Every domain is tried in up to 4 URL forms** before being marked UNREACHABLE:

```
https://www.domain.com  →  https://domain.com  →  http://www.domain.com  →  http://domain.com
                                                                         ↓ (if all fail)
                                                               requests sync fallback (4 variants)
```

Classification layers applied to the first URL that returns a valid response:

```
Website URL goes in
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 SITE CLASSIFICATION PIPELINE v5                     │
│                                                                     │
│  Layer 1  ─── HTTP Status Code Check                                │
│               404 / 410 → NOT FOUND                                 │
│               500 / 502-504 → UNREACHABLE (try next variant)        │
│                                                                     │
│  Layer 2  ─── Redirect URL check                                    │
│               godaddy.com/domainfind? sedoparking.com?              │
│               → PARKED                                              │
│                                                                     │
│  Layer 3  ─── Content length                                        │
│               Page < 800 characters → PARKED                        │
│                                                                     │
│  Layer 4  ─── Strong parking signals (anywhere)                     │
│               "this domain is for sale"                             │
│               "hugedomains.com" "parkingcrew.net"                   │
│               → PARKED                                              │
│                                                                     │
│  Layer 5  ─── Parking signals in <title> only                       │
│               → PARKED                                              │
│                                                                     │
│  Layer 6  ─── Parking signals on thin pages (< 3,000 chars)         │
│               "namecheap.com" "dan.com" "godaddy.com/domain"        │
│               → PARKED                                              │
│                                                                     │
│  Layer 7  ─── Strong placeholder signals (anywhere)                 │
│               "apache2 ubuntu default page"                         │
│               "this account has been suspended"                     │
│               "welcome to wordpress" (factory fresh)                │
│               → DEMO                                                │
│                                                                     │
│  Layer 8  ─── Placeholder in <title> only                           │
│               <title>Coming Soon</title>                            │
│               <title>Site Offline</title>                           │
│               <title>Maintenance Mode</title>                       │
│               → DEMO   (❌ "Under Construction" removed — too broad) │
│                                                                     │
│  Layer 9  ─── Placeholder signals on thin pages (< 3,000 chars)     │
│               → DEMO   (❌ "coming soon"/"under construction"        │
│                            removed — appear in real site content)   │
│                                                                     │
│  Layer 10 ─── Soft-404 Detection                                    │
│               HTTP 200 but title says "Page Not Found"              │
│               → NOT FOUND                                           │
│                                                                     │
│  Layer 11 ─── SPA / JS-Framework Guard  ← NEW v5                   │
│               Page < 2,000 chars AND detects:                       │
│               • React     id="root"                                 │
│               • Next.js   /_next/static/                            │
│               • Vue       id="app"                                  │
│               • Angular   <app-root                                 │
│               • Nuxt      id="__nuxt"                               │
│               • Generic   chunk.*.js | bundle.js | main.*.js        │
│               → REAL (skip structural check — shell HTML is normal) │
│                                                                     │
│  Layer 12 ─── Structural Analysis  (threshold tightened v5)         │
│               Page < 2,000 chars (was 8,000) AND:                   │
│               ✗ No <nav> or menu, ✗ No phone/email                 │
│               ✗ Fewer than 3 real links (was 5)                     │
│               → DEMO (structurally dead)                            │
│                                                                     │
│  Layer 13 ─── Passed everything above?                              │
│               → REAL (run the full audit)                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
       │
  Result:  REAL / PARKED / DEMO / NOT_FOUND / UNREACHABLE
```

---

## Part 3: The SEO & UX Audit + AI Name Extraction (v5.0.0 — 55 Factors / 11 Axes)

Only runs on **REAL** sites. Checks **55 technical/UX/Local factors** across **11 axes** + extracts the clean business name:

```
Website HTML fetched
       │
       │  TECHNICAL (6 checks)
       ├─ 1.  SSL Certificate ──────────── Is https:// valid?
       ├─ 2.  XML Sitemap ──────────────── Does /sitemap.xml exist?
       ├─ 3.  robots.txt ──────────────── Does /robots.txt exist?
       ├─ 4.  Canonical Tag ────────────── <link rel="canonical"> present?
       ├─ 5.  Favicon ──────────────────── Browser tab icon present?
       ├─ 6.  Mobile Viewport ──────────── <meta name="viewport"> present?
       │
       │  ON-PAGE (4 checks)
       ├─ 7.  H1 Heading ──────────────── At least one <h1> tag?
       ├─ 8.  Meta Description ─────────── <meta name="description"> present?
       ├─ 9.  Image Alt Text ───────────── Any <img> missing alt=""?
       ├─ 10. Broken Links ─────────────── Any <a> hrefs returning errors?
       │
       │  PERFORMANCE ENGINE (3 checks)
       ├─ 11. Page Speed ──────────────── Response time estimate
       ├─ 12. WebP Images ─────────────── Using modern WebP format?
       ├─ 13. Minification ─────────────── CSS/JS minified?
       │
       │  STRUCTURED DATA (2 checks)
       ├─ 14. JSON-LD Schema ───────────── Structured data markup?
       ├─ 15. Open Graph Tags ──────────── og:title, og:image present?
       │
       │  SOCIAL (1+)
       ├─ 16. Social Profiles ─────────── FB/IG/LinkedIn/Twitter/YouTube?
       │
       │  UI/UX (10 checks)
       ├─ 17. Primary CTA Button ───────── "Get Quote", "Contact Us"?
       ├─ 18. CTA Above Fold ───────────── Visible without scrolling?
       ├─ 19. Hero Headline ────────────── Clear H1 value proposition?
       ├─ 20. Font Size ────────────────── Base font >= 14px?
       ├─ 21. Color Contrast ───────────── Clear readable text?
       ├─ 22. Navigation Links ─────────── Has a site menu?
       ├─ 23. Cookie Notice ────────────── GDPR/cookie banner present?
       ├─ 24. Live Chat ────────────────── WhatsApp, Tidio, Intercom widget?
       ├─ 25. Phone Number ─────────────── Clickable tel: link present?
       └─ 26. Address Present ──────────── Physical address in footer?
       │
       │  INDEXABILITY ← NEW v5.0.0 (4 checks)
       ├─ 27. No Noindex ───────────────── Page not blocked by noindex meta?
       ├─ 28. Clean URL ────────────────── Short hyphenated URL (no query strings)?
       ├─ 29. www/non-www Canonical ────── Consistent preferred version?
       └─ 30. No Soft 404 ──────────────── Returns real 404 for missing content?
       │
       │  CONTENT QUALITY ← NEW v5.0.0 (4 checks)
       ├─ 31. Word Count ───────────────── ≥300 words (not thin content)?
       ├─ 32. Unique Meta Tags ─────────── No duplicate title/description?
       ├─ 33. Keyword in Title ─────────── Primary keyword in <title>?
       └─ 34. Readable Content ─────────── Grade-8 reading level or below?
       │
       │  LOCAL SEO ← NEW v5.0.0 (5 checks)
       ├─ 35. NAP Consistency ──────────── Name/Address/Phone in footer/contact?
       ├─ 36. LocalBusiness Schema ─────── JSON-LD LocalBusiness markup?
       ├─ 37. Google Maps Embed ────────── Map iframe on contact page?
       ├─ 38. City in Title ────────────── City keyword in page title?
       └─ 39. Business Hours ───────────── Opening hours on site or in schema?
       │
       │  PERFORMANCE ← NEW v5.0.0 (6 checks)
       ├─ 40. TTFB < 600ms ─────────────── Server response under 600ms?
       ├─ 41. Page Size ────────────────── Total HTML under 3MB?
       ├─ 42. Render-Blocking ──────────── No blocking scripts in <head>?
       ├─ 43. Gzip Compression ─────────── Content-Encoding: gzip/br?
       ├─ 44. WebP Coverage ────────────── All images served as WebP?
       └─ 45. CSS/JS Minified ──────────── Assets are minified?
       │
       │  ADVANCED SCHEMA ← NEW v5.0.0 (5 checks)
       ├─ 46. FAQ Schema ───────────────── FAQPage JSON-LD present?
       ├─ 47. Product Schema ───────────── Product + Offer markup?
       ├─ 48. Breadcrumb Schema ────────── BreadcrumbList JSON-LD?
       ├─ 49. Review Schema ────────────── AggregateRating or Review?
       └─ 50. Schema @graph ────────────── Connected @graph structure?

       + AI Name Extraction (runs in parallel):
         Priority 1: og:site_name meta tag
         Priority 2: JSON-LD @type=Organization → name or legalName
         Priority 3: <title> first segment (splits on | - – :)
         Result stored in audits.suggested_name

       │
       ▼
Results saved to database
suggested_name stored for Edit Modal
Summary auto-generated
ReportLab PDF report created (multi-section, multi-page)
```

### Why AI Name Extraction matters

Scraped leads often have noisy names like:
```
"ADM Engineering | Plastic Manufacturing Company in Pune | HDPE Crates"
```
The AI extractor visits the actual website and finds the clean name:
```
"ADM Engineering"
```
The Edit Modal shows this as a purple AI suggestion banner — one click to apply.

---

## Part 4: The Campaign Engine

### Campaign Lifecycle

Campaign lead eligibility (v4.3.2):
- Fresh = lead has never been emailed AND its related audit row has `status = done`.
- `lead.status = audited` alone is not enough; stale, failed, running, or missing audit rows are not campaign-ready.
- The Campaigns UI receives `audit_status` from the leads API and disables selection for leads without a successful audit.
- The backend validates campaign creation and rejects any selected lead whose audit is missing or not `done`.

```
Create (draft)
    │
    ▼ [Send]
Sending ─────────────────────── [Pause] ──► Paused
    │                                           │
    │  for each lead:                      [Resume]
    │  ┌─────────────────────────────┐         │
    │  │ Check: status == 'paused'?  │◄────────┘
    │  │ YES → save pending_lead_ids │
    │  │       stop runner           │
    │  │                             │
    │  │ Check: last_emailed_at      │
    │  │   within 7 days? → SKIP     │
    │  │                             │
    │  │ Build email (SEO or no-site)│
    │  │   _pick_hook() selects best │
    │  │   failing issue as opener   │
    │  │ Send via SMTP               │
    │  │ Log to campaign_email_logs  │
    │  │ Update lead.last_emailed_at │
    │  │ Update pending_lead_ids     │
    │  │ Set next_email_at (+delay)  │
    │  │ Sleep 60–90 seconds         │  ← randomised, trust-building
    │  └─────────────────────────────┘
    │
    ▼ [all leads processed]
  Done
```

### 7-Day Skip Logic

```
Before sending each email:
  IF lead.last_emailed_at > (now - 7 days):
    → Log "skipped" to campaign_email_logs
    → campaign.skipped_count++
    → Continue to next lead
    → No email sent
```

### Pause / Resume

```
Pause triggered:
  → campaign.status = "paused" in DB
  → Runner checks this flag before EVERY email
  → Saves remaining lead IDs to campaign.pending_lead_ids
  → Saves sent/skipped/failed counts
  → Runner exits cleanly after current email finishes

Resume triggered:
  → campaign.status = "draft" (runner picks it up)
  → run_campaign() launched as new background task
  → pending_lead_ids used instead of full lead_ids
  → Continues from exact position
```

### Live Countdown Timer

```
Backend:
  Before asyncio.sleep(delay):
    campaign.next_email_at = datetime.utcnow() + timedelta(seconds=delay)
    DB commit

Frontend:
  Polls every 8 seconds
  useCountdown(next_email_at) hook:
    Every 1 second: remaining = target - Date.now()
    Displays: "🕐 Next in 6m 42s"
  Works across page navigation (polling runs globally)
```

### Email Routing (v5.1.0 Modernized Outreach)

```
                    REAL site?
                        │
           ─────────────┴──────────────
           │                          │
          YES                         NO
           │                          │
    Branded Design Proposal     New Website Pitch Email
    (build_html_email)         (build_no_site_email)
    ─────────────────────      ────────────────────────
    • 600px card, navy header  • Domain status context
    • TEB Solutions logo       • Cost of missing site
    • Service pill tag         • 11-day build roadmap
    • Domain observations H1   • Single "Reply YES" CTA
    • 4 Usability Pillars      • No PDF attachment
    • Portfolio Proof Strip
      (Hexaprime, Channelnexus, Sketchlife)
    • 2x2 Evaluation Grid
    • Low-Friction Closing
      ("Purely helpful context... no need to reply")
    • Curiosity-gap subjects
    • NO attachments (Email 1)
```

> **Email 1 Design Rule:** Email 1 establishes credibility and visual authority without sales pressure. PDF audit reports and 2-tier pricing ($25–$300 USD / ₹1,999–₹29,999 INR) are sent strictly in **Email 2** after the lead replies YES.

---

## Part 5: Information Flow Diagrams

### A. Uploading a CSV

```
User  →  Drops CSV file on Leads page
          │
Frontend  →  Sends file to POST /api/leads/upload
          │
Backend   →  Reads each row
          →  **Sanitizes data (v4.3.1)**:
             • Trims website URL to root domain
             • Strips taglines from business name (at - or |)
          →  Checks if email already exists → skips duplicates
          →  Returns: {imported: 47, skipped: 3}
          │
Frontend  →  Shows toast: "Imported 47 leads. Skipped 3 duplicates."
          →  Refreshes table
          →  ⚠️ warning shown on names with | or len > 60
```

### B. Triggering Audit All (Semaphore-Based — v4.1.0)

```
User  →  Clicks "Audit All"
          │
Frontend  →  POST /api/audits/trigger-all
             ← 409 Conflict if batch already running (_BATCH_RUNNING = True)
             ← 202 Accepted + BackgroundTask launched
          │
Backend   →  Selects all leads with status "new" or "failed"
          →  Creates/resets audit records
          →  Sets _BATCH_RUNNING = True
          →  Launches single background task: run_batched()
          │
          run_batched(lead_ids):
            Uses asyncio.Semaphore(3):
            ┌─ guarded(lead_1) ─ acquire semaphore → run_audit → release ─┐
            ├─ guarded(lead_2) ─ acquire semaphore → run_audit → release ─┤
            ├─ guarded(lead_3) ─ acquire semaphore → run_audit → release ─┤  ← max 3 concurrent
            ├─ guarded(lead_4) ─ BLOCKS until slot free ─────────────────┤
            └─ ...up to N leads, always max 3 in flight...───────────────┘
            Each guarded() catches its own exceptions — one crash ≠ all crash
            Sets _BATCH_RUNNING = False when all done

Frontend  →  Polls /api/audits/stats every 10s
          →  {batch_running: true/false, total, done, failed}
          →  "Audit All" button stays disabled while batch_running = true
          →  "Audit Complete" modal only fires AFTER batch_running = false
```

### C. Sending a Campaign

```
User  →  Clicks Send on a campaign
          │
Frontend  →  POST /api/campaigns/{id}/send
          →  Backend immediately responds
          │
Backend (background — run_campaign):
  campaign.status = "sending"
  pending = pending_lead_ids || lead_ids

  For each lead_id in pending:
    [Check: status == paused → save & exit]
    [Check: emailed in last 7 days → skip + log]
    Build correct email (SEO or no-site)
    Send via SMTP (rotating account)
    Log to campaign_email_logs
    lead.last_emailed_at = now
    campaign.sent_count++
    campaign.pending_lead_ids = remaining
    campaign.next_email_at = now + delay
    await sleep(240–600 seconds)

  campaign.status = "done"

Frontend:
  Polls every 8 seconds
  live countdown from next_email_at
  Row expands to show per-email log
```

### D. Pause then Resume

```
User  →  Clicks Pause while campaign is sending
          │
Frontend  →  POST /api/campaigns/{id}/pause
          →  Sets campaign.status = "paused" in DB
          │
Backend   →  Runner checks status before next email
          →  Saves pending_lead_ids, counts
          →  Returns (coroutine exits)
          →  Campaign stays at "paused" with X remaining

User  →  Clicks Resume (maybe next day)
          │
Frontend  →  POST /api/campaigns/{id}/resume
          │
Backend   →  Sets status = "draft"
          →  Launches new run_campaign() task
          →  Uses pending_lead_ids (not full lead_ids)
          →  Continues from where it stopped
```

### E. AI Name Suggestion

```
Audit completes for a lead
          │
audit_engine.extract_business_name(html, audit):
  1. Try og:site_name meta tag → "ADM Engineering"  ← BEST
  2. Try JSON-LD Organization.name → "ADM Engineering"
  3. Try <title> first segment → "ADM Engineering"   ← FALLBACK
          │
  Stored in audits.suggested_name

User  →  Clicks ✏️ Edit on lead "ADM Engineering | Plastic Mfg..."
          │
Frontend  →  GET /api/audits/{lead_id}  (loads suggested_name)
          →  If suggested_name differs from business_name:
             Shows purple banner: "✨ AI-suggested name from website metadata"
             Button: "Use this name" / "Dismiss"
```

---

## Part 6: Database Relationships

```
leads
  │
  ├─── ONE-TO-ONE ──► audits
  │     (cascade delete: deleting lead → deletes audit)
  │     Key new columns:
  │       last_emailed_at  → used for 7-day skip check
  │
  │     audits key new columns:
  │       suggested_name    → AI-extracted clean business name
  │       8 Phase 2 SEO columns → (canonical, page_title, meta_desc, og_tags, lazy_load, contact, whatsapp, trust)
  │       9 UX columns (v4.5.0) → (has_cta, cta_above_fold, has_hero_headline, font_size_ok, contrast_ok, nav_links_count, has_cookie_notice, has_live_chat, ux_score)
  │       47 v5.0.0 columns → Indexability (has_noindex, url_structure_ok, www_nonwww_ok, soft_404_ok)
  │                            Content (word_count, duplicate_meta_ok, keyword_in_title_ok, reading_level_ok)
  │                            Local SEO (has_nap, has_local_business_schema, has_google_maps, city_in_title_ok, has_business_hours)
  │                            Performance (response_time_ms, page_size_bytes, page_size_ok, render_blocking_ok, gzip_enabled, webp_coverage_ok, minification_ok)
  │                            Advanced Schema (has_faq_schema, has_product_schema, has_breadcrumb_schema, has_review_schema, schema_graph_ok)
  │
  └─── ONE-TO-MANY ──► activity_log
        (deleting lead → sets log.lead_id to NULL, keeps log)

campaigns
  ├─── Stores a JSON list of lead IDs (not FK — survives lead deletion)
  │    New columns:
  │      pending_lead_ids  → remaining leads for pause/resume
  │      next_email_at     → countdown timer target
  │      paused_at         → when pause was triggered
  │      skipped_count     → leads skipped (7-day rule)
  │      failed_count      → SMTP failures
  │
  └─── ONE-TO-MANY ──► campaign_email_logs
        (cascade delete: deleting campaign → deletes all logs)
        One row per email attempt:
          status: "sent" | "failed" | "skipped"
          message: reason or subject used
```

---

## Part 7: Dependency Map

```
frontend/src/pages/Leads.jsx
  └── api/client.js
        → GET /leads/, PATCH /leads/{id}, DELETE /leads/{id}
        → DELETE /leads/all, POST /leads/bulk-delete
        → POST /audits/trigger-all, GET /audits/{lead_id}
  └── Edit Modal (AI name banner, field editing)
  └── ⚠️ tagline warnings (name contains | or len > 60)

frontend/src/pages/Campaigns.jsx
  └── api/client.js
        → GET /campaigns/, POST /campaigns/
        → POST /{id}/send, pause, resume, reset
        → DELETE /{id}
        → GET /{id}/logs
  └── CampaignRow: expandable logs, countdown timer, progress bar
  └── useCountdown() hook (1s interval, target = next_email_at)
  └── Global poll (setInterval 8s, persists across navigation)
  └── TestPanel component (floating card, bottom-right)

backend/app/routers/audits.py
  ├── POST /trigger-all → _BATCH_RUNNING guard → run_batched() as BackgroundTask
  │     └── asyncio.Semaphore(3) rolling queue
  │           └── guarded(lead_id) → run_audit()
  │                 ├── site_checker.classify_site()  [13-layer, 4 URL variants]
  │                 ├── extract_business_name() → audits.suggested_name
  │                 └── pdf_engine.generate_pdf()
  ├── GET /stats → {batch_running, total, pending, done, failed}  ← NEW v4.1.0
  └── Route order: /pdf/{id} before /{id} (prevents UUID parse error on "pdf")

backend/app/routers/campaigns.py
  ├── DELETE /{id} → delete campaign + cascade logs
  ├── POST /{id}/pause → status="paused" (runner self-terminates)
  ├── POST /{id}/resume → status="draft" + relaunch from pending_lead_ids
  └── GET /{id}/logs → campaign_email_logs ordered by created_at desc

backend/app/routers/replies.py  ← NEW v4.0
  ├── POST /check-now → reply_engine.process_replies() (sync, returns stats)
  ├── POST /check → background task wrapper
  ├── GET /converted → leads where status=converted
  ├── GET /all-replies → leads where reply_type IS NOT NULL
  └── GET /stats → {converted, soft_bounce, deleted_today}

backend/app/engines/reply_engine.py  ← NEW v4.0
  ├── fetch_unseen_emails() → IMAP4_SSL :993, scans INBOX + INBOX.Spam
  ├── classify_reply(subject, body, from_addr) → positive|stop|bounce|soft_bounce|other
  ├── _extract_original_to() → resolve bounce recipient from headers/body
  ├── _mark_converted() → lead.status=converted + snippet + replied_at
  ├── _delete_lead() → hard delete lead + audit + activity log
  └── process_replies() → main async orchestrator, returns stats dict

backend/app/engines/outreach_engine.py (run_campaign)
  ├── Trust-first Email 1 & Expert-style Email 2 with 8 service tiers
  ├── Keyword-based reply routing
  ├── Multi-layered DNS/MX record validation to prevent spam filtering
  ├── Checks campaign.status == "paused" BEFORE every send
  ├── Checks lead.last_emailed_at > (now - 7 days) → skip
  ├── Delays sending with a randomized interval of 60-90 seconds
  ├── Sets campaign.next_email_at BEFORE sleep (countdown timer source)
  ├── Updates campaign.pending_lead_ids AFTER each send (resume safety)
  └── Logs every attempt to CampaignEmailLog

backend/app/database.py
  └── pool_size=20, max_overflow=40, pool_timeout=30, pool_recycle=1800
      (tuned for bulk audit workloads — 411 leads in batches of 10)
```

---

## Part 8: Key Files and What They Do

| File | In Plain English |
|---|---|
| `backend/run.py` | **v5.1.0** Launcher running Uvicorn on port `8001` with WindowsSelectorEventLoopPolicy |
| `backend/app/main.py` | API server entry point, connects DB, CORS configured for `http://localhost:5174` (7 core routers) |
| `backend/app/config.py` | Reads `.env`, parses SMTP JSON accounts, default `FRONTEND_URL = "http://localhost:5174"` |
| `backend/app/models.py` | 6 tables: leads, audits, campaigns, campaign_email_logs, activity_log, **email_corrections** |
| `backend/app/schemas.py` | Response shapes + **UTCBase** timezone-safe serialization + reply fields |
| `backend/app/routers/leads.py` | Upload CSV, list, PATCH (edit), DELETE, bulk-delete, DELETE /all, **maintenance cleanup endpoints** |
| `backend/app/routers/audits.py` | **v4.1.0** Semaphore(3) rolling queue, `_BATCH_RUNNING` guard, `/stats` endpoint, PDF route |
| `backend/app/routers/campaigns.py` | **v5.1.0** Create, send, pause, resume, reset, delete, per-email logs + `POST /send-test` |
| `backend/app/routers/replies.py` | **v5.1.0** Inbox sync, converted leads, stats, `preview-email2`, `send-email2`, `reclassify` |
| `backend/app/routers/email_review.py` | **NEW v4.3.0** Scan engine + accept/dismiss corrections |
| `backend/app/engines/audit_engine.py` | **v4.1.0** Micro-session pattern — DB released during crawl + PDF; bridge to auditor/ |
| `backend/app/engines/reply_engine.py` | **NEW v4.0** IMAP fetch, classify, convert/delete/flag leads |
| `backend/app/engines/outreach_engine.py` | **v5.1.0** Branded Email 1 card design, portfolio proof, soft closing, Hostinger 1000/day limit & rotation |
| `backend/reset_leads_to_fresh.py` | **NEW v5.1.0** Complete reset utility: clears email metadata, recovers stale running audits, syncs lead status |
| `backend/gen_preview.py` | **NEW v5.1.0** Standalone offline preview script generating `email_preview.html` |
| `send_test_email.py` | **NEW v5.1.0** Standalone test email sender with WindowsSelectorEventLoopPolicy |
| `auditor/auditor/auditor/runner.py` | **v5.0.0** Orchestrates all 55 audit checks (11 axes including Indexability, Content, Local SEO, Performance, Schema Advanced) |
| `auditor/auditor/auditor/indexability.py` | **NEW v5.0.0** Noindex, URL structure, www/non-www consistency, soft-404 detection |
| `auditor/auditor/auditor/content.py` | **NEW v5.0.0** Word count, duplicate meta, keyword-in-title, reading level |
| `auditor/auditor/auditor/local_seo.py` | **NEW v5.0.0** NAP, LocalBusiness schema, Google Maps embed, city-in-title, business hours |
| `auditor/auditor/auditor/performance.py` | **NEW v5.0.0** TTFB, page size, render-blocking, Gzip, WebP coverage, minification |
| `auditor/auditor/auditor/schema_advanced.py` | **NEW v5.0.0** FAQ, Product, Breadcrumb, Review, @graph schema detection |
| `auditor/auditor/auditor/pdf_builder.py` | **v4.5.0** ReportLab multi-section PDF generator (includes UX section) |
| `backend/app/utils/site_checker.py` | **v5** 13-layer + 4-variant URL chain + SPA/JS-framework guard + tightened structural threshold |
| `backend/app/utils/spintax.py` | `{option1\|option2}` random picker |
| `backend/app/utils/csv_parser.py` | CSV upload + email deduplication + **data sanitization (v4.3.1)** |
| `backend/app/database.py` | SQLAlchemy async engine with tuned connection pool |
| `frontend/vite.config.js` | **v5.1.0** Vite configuration: server port `5174`, proxy `/api` → `http://localhost:8001` |
| `frontend/src/api/client.js` | 30+ API functions including email-review scan/accept/dismiss, replies, campaigns |
| `frontend/src/pages/Leads.jsx` | **v4.1.0** `batch_running` modal guard + "Audit All" disable during batch + `.replaceAll()` badge fix |
| `frontend/src/pages/Campaigns.jsx` | Campaign list + pause/resume + countdown + log panel + test email panel |
| `frontend/src/pages/Inbox.jsx` | **v5.1.0** Converted Leads tab + **Email 2 Compose & Preview Modal** with live preview, editor, send action & reclassify |
| `frontend/src/pages/Audits.jsx` | **v5.0.0** Premium Audit Dashboard with 11-axis score rings and 55 PASS/WARN/FAIL checks |
| `frontend/src/pages/EmailReview.jsx` | **NEW v4.3.0** Email mismatch review — stat cards, filter tabs, accept/dismiss |
| `frontend/src/pages/ActivityLog.jsx` | Event stream with parseUTC() timezone fix |
| `frontend/src/components/Layout.jsx` | Sidebar navigation + green Converted badge + orange Email Review pending badge |
| `frontend/src/index.css` | All colours, fonts, layout styles |
| `backend/.env` | Passwords, DB URL, SMTP/IMAP credentials |
| `START.bat` | **v5.1.0** One-click startup script launching backend on :8001, frontend on :5174, auto-opening browser |
| `pyrightconfig.json` | **NEW v4.0** Linter config — tells Pyrefly that backend/ is Python root |

---

## Part 9: What Happens on First Start

```
1. START.bat runs
   ├── Opens Terminal A (green): starts uvicorn (FastAPI) via python run.py
   │     FastAPI starts
   │     Reads .env file → loads settings
   │     Connects to PostgreSQL (pool_size=20)
   │     Creates any missing tables automatically
   │     Ready: "Uvicorn running on http://0.0.0.0:8001"
   │
   ├── Waits 10 seconds
   │
   ├── Opens Terminal B (blue): starts Vite (React)
   │     npm run dev
   │     Compiles React components
   │     Ready: "Local: http://localhost:5174/"
   │
   ├── Waits 6 seconds
   │
   └── Opens browser: http://localhost:5174
         → Login page appears
```

---

## Part 10: Real-Time UI Behaviour

### Campaign Polling & Countdown
```
When you launch a campaign:
  1. Status badge: ● sending (blue)
  2. Every 8 seconds, browser silently polls GET /campaigns/
  3. next_email_at from API feeds countdown:
     "🕐 Next in 6m 42s" → counts down to 0
  4. Progress bar updates: █████░░░ 4/50 · ⟳3 · ✗1
  5. When done: ✓ done (green, polling continues for other campaigns)

Polling persists across navigation — you can go to Leads page
and then back; the countdown is still live.
```

### Edit Modal + AI Name Banner
```
User clicks ✏️ on a lead:
  1. Modal slides in from right
  2. GET /audits/{lead_id} fires in background
  3. If audit.suggested_name differs from lead.business_name:
     → Purple AI banner appears at top of modal
     → Shows suggested name and source
     → "Use this name" button auto-fills the name field
  4. If name contains | or is > 60 chars:
     → Yellow inline warning: "Name appears to contain a tagline"
  5. Save → PATCH /leads/{id}
```

### Leads Table Warnings
```
⚠️ yellow triangle shown on rows where:
  - business_name contains "|"        (scraped tagline separator)
  - business_name.length > 60 chars   (full sentence, not a name)

These are candidates for AI name correction via the Edit Modal.
```

### Timezone Handling
```
Backend (PostgreSQL) → stores datetimes as naive UTC
   ↓
schemas.py UTCBase → serializes with 'Z' suffix: "2026-04-04T14:30:00Z"
   ↓
Frontend parseUTC() → ensures JavaScript treats it as UTC
   ↓
formatDistanceToNow() → "3 minutes ago" (correct, not 5.5 hours off)
```

---

## Part 12: Reply Inbox Flow (v4.0)

### How the IMAP sync works

```
User clicks "Sync Inbox Now" (Inbox page)
          │
Frontend → POST /replies/check-now
          │
Backend (reply_engine.process_replies):
  1. Connect to imap.hostinger.com:993 (SSL)
     Credentials from SMTP_SENDERS[0] in .env
          │
  2. Scan INBOX and INBOX.Spam for UNSEEN messages
     Mark each fetched message as \Seen immediately
          │
  3. For each email, classify_reply(subject, body, from):
     ┌──────────────────────────────────────────────┐
     │ BOUNCE?   mailer-daemon from OR 550 in body   │
     │ SOFT?     out of office / on leave / auto-reply│
     │ STOP?     unsubscribe / remove me / opt out    │
     │ POSITIVE? yes / interested / call me / quote   │
     │ OTHER?    none of the above                   │
     └──────────────────────────────────────────────┘
          │
  4. Find matching lead in DB:
     - Normal reply  → match by from_addr
     - Bounce email  → extract original recipient from
                       X-Original-To or Final-Recipient header
          │
  5. Take action:

  POSITIVE → lead.status = "converted"
              lead.reply_snippet = first 500 chars
              lead.replied_at = now
              ActivityLog: "lead_converted"

  STOP     → DELETE audit WHERE lead_id = lead.id
              DELETE lead WHERE id = lead.id
              ActivityLog: "lead_deleted_reply" (STOP request)

  BOUNCE   → DELETE audit WHERE lead_id = lead.id
              DELETE lead WHERE id = lead.id
              ActivityLog: "lead_deleted_reply" (Hard bounce)

  SOFT     → lead.reply_type = "soft_bounce"
              lead.replied_at = now
              NOT deleted — email may be valid

  OTHER    → no DB action (already marked Seen in IMAP)

Returns stats dict:
  {fetched, positive, deleted, soft_bounce, other, errors}

Frontend:
  Displays stats card → refreshes Converted Leads table → refreshes sidebar badge
```

### What "Converted" Looks Like & The Email 2 Workflow (v5.1.0)

```
Inbox page → Converted Leads tab:
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Business      Email        Reply Preview        Type  Date    Actions  │
  ├────────────────────────────────────────────────────────────────────────┤
  │ Acme Digital  bob@acme.com  "YES send details"  YES✓  12 Apr  [Email 2]│
  │                                                               [Demote] │
  │                                                               [Delete] │
  └────────────────────────────────────────────────────────────────────────┘

Email 2 Compose & Preview Modal:
  ├── Tab 1: Live Render Preview (GET /api/replies/preview-email2/{lead_id})
  │     Renders the full proposal email (build_html_email_full)
  │     Shows pricing tiers, deliverables, and guarantees
  │
  ├── Tab 2: HTML & Subject Editor
  │     Live editable HTML textarea + customizable subject line
  │     Supports custom tailoring before sending
  │
  └── Action: Send Email 2 (POST /api/replies/send-email2/{lead_id})
        ├── Dispatches via primary SMTP sender account
        ├── Automatically attaches PDF audit report (if available)
        ├── Records activity log: "email2_sent"
        └── Reclassify action: PATCH /api/replies/reclassify/{lead_id}
              Demotes false positives to 'emailed' + 'other' without deletion
```

---

## Part 13: Email Mismatch Detection Flow (v4.3.0)

### How the scan works

```
User clicks "Scan Now" (Email Review page)
          │
Frontend → POST /api/email-review/scan
          │
Backend (email_review.scan_all_leads):
  For each lead with a website URL:
    1. Skip if email already matches website domain
    2. Skip if email is from a free provider (gmail, yahoo, etc.)
    3. Fetch homepage + /contact page HTML
    4. Extract all mailto: links + email regex matches
    5. Filter to emails whose domain == lead's website domain
    6. If found email ≠ lead.email:
       → Write EmailCorrection(status=pending, old=lead.email, new=found)
       → Skip if pending correction already exists for this lead

Frontend:
  Shows stat cards: Pending / Accepted / Dismissed
  Lists each correction with side-by-side email comparison
```

### Accept / Dismiss actions

```
Accept:
  lead.email = new_email
  lead.status = 'new'         ← full re-audit + re-email pipeline triggered
  lead.last_emailed_at = None  ← removes 7-day skip protection
  correction.status = 'accepted'
  ActivityLog: email_corrected

Dismiss:
  correction.status = 'dismissed'
  No changes to lead record
```

### Why domain-matched only?

The scan deliberately ignores:
- Free provider emails (gmail, yahoo, outlook, hotmail, live, icloud, etc.)
- Emails from domains OTHER than the lead's own website

Only emails from the SAME domain as the business website are surfaced — these are the most reliable indicator that the DB email is wrong.

---

## Part 11: Terminology Glossary

| Term | Meaning |
|---|---|
| **Lead** | One business contact (name, email, phone, website) |
| **Audit** | The 10-factor SEO check run on a lead's website |
| **Campaign** | A batch of emails to send to a set of leads |
| **PARKED** | Domain is listed for sale or sitting unused |
| **DEMO** | Website shows a placeholder, "coming soon", or server default page |
| **NOT_FOUND** | Website returns 404 or doesn't exist |
| **UNREACHABLE** | Website has SSL error, DNS failure, or connection refused |
| **REAL** | Website is a genuine, working business site |
| **Spintax** | `{hello\|hi\|hey}` → picks one randomly per email |
| **SMTP** | The protocol used to send emails |
| **SMTP_SSL** | Secure email connection on port 465 (direct encryption) |
| **JWT** | Login "ticket" stored in the browser — expires after 24 hours |
| **BackgroundTask** | Work the server does without making you wait |
| **CASCADE** | When a lead is deleted, its audit is automatically deleted too |
| **UTCBase** | Pydantic base model that forces UTC datetime serialization |
| **Soft-404** | Page says "not found" but server says HTTP 200 OK |
| **Structural Analysis** | Checking if page has nav/contact/links — not just keywords |
| **PDF Engine** | FPDF2 library that generates the branded audit report |
| **Auto-Poll** | Frontend automatically re-checks API every 8s during campaigns |
| **Force Re-audit** | Re-run audit on leads that already have results |
| **suggested_name** | AI-extracted clean business name stored in audits table |
| **pending_lead_ids** | Remaining leads to email — saved when campaign is paused |
| **next_email_at** | UTC timestamp of next scheduled email — powers countdown timer |
| **last_emailed_at** | When a lead was last emailed — used for 7-day skip check |
| **campaign_email_logs** | Per-email audit trail: sent/failed/skipped per campaign |
| **7-day skip** | Leads emailed within 7 days are automatically skipped in campaigns |
| **Batched Audit** | Audits run using a Semaphore(3) rolling queue — max 3 in-flight, all N leads submitted at once |
| **Pool Size** | DB connection pool: 20 base + 40 overflow = max 60 simultaneous connections |
| **Semaphore** | asyncio.Semaphore(3) — limits concurrent crawls to 3 so DB pool is never saturated |
| **_BATCH_RUNNING** | Global flag in audits.py — prevents duplicate Audit All calls; returns HTTP 409 if True |
| **Micro-session** | Short-lived DB session pattern — opened for DB ops only, closed before network I/O |
| **SPA Guard** | Layer 11 in site_checker v5 — detects React/Vue/Next.js/Angular shells and returns REAL |
| **4-Variant URL** | https://www, https://bare, http://www, http://bare — tried in order per domain before UNREACHABLE |
| **batch_running** | Field from GET /audits/stats — used by frontend to guard the "Audit Complete" modal |
| **reply_engine** | Module that connects to IMAP, classifies replies, and takes DB actions |
| **converted** | Lead status meaning they replied YES — visible in Inbox → Converted Leads |
| **soft_bounce** | Out-of-office / temp unavailable — flagged but NOT deleted |
| **hard bounce** | Permanent delivery failure (550, invalid address) — lead deleted |
| **STOP** | Unsubscribe request — lead deleted to comply with anti-spam rules |
| **reply_type** | Column on leads: positive / stop / bounce / soft_bounce (v4.0) |
| **replied_at** | UTC timestamp when the lead's reply was processed (v4.0) |
| **reply_snippet** | First 500 chars of the reply body — stored for display (v4.0) |
| **reclassify** | Downgrade a false-positive converted lead back to status=emailed, reply_type=other (v4.0.1) |
| **ReplyModal** | Full-screen overlay in Inbox.jsx — shows 500-char reply snippet + Move to Other action (v4.0.1) |
| **lead_reclassified** | ActivityLog event_type written when a lead is manually reclassified (v4.0.1) |
| **EmailCorrection** | ORM model tracking detected email mismatches: old_email, new_email, domain, status (v4.3.0) |
| **email_corrections** | DB table storing pending/accepted/dismissed email mismatch records (v4.3.0) |
| **domain-matched email** | An email whose domain exactly matches the lead's website domain — only these are flagged (v4.3.0) |
| **free provider** | gmail, yahoo, outlook, hotmail, live, icloud etc. — excluded from mismatch detection (v4.3.0) |
| **pending correction** | An `EmailCorrection` with status=pending — awaiting admin accept or dismiss (v4.3.0) |
| **email_corrected** | ActivityLog event_type written when a correction is accepted (v4.3.0) |

---

*TEB Solutions / Tattavit — https://tebsolutions.in — April 2026 (v4.3.0 — April 20, 2026)*


---

## Data Consistency Invariants (v5.0.2 — 2026-05-19)

### The 3-Layer Audit Chain

All audit data flows through:
```
auditor/*.py  →  _map_to_db_columns()  →  _results_write()  →  audits table
```
All three layers must be present for any column to be persisted. See Guardrail #43.

### Critical Bug Fixed (2026-05-19)

`_results_write()` in `audit_engine.py` was not assigning any of the 30 v5.0 columns
(Groups B-G) computed by `_map_to_db_columns()`. This caused all v5.0 columns to remain
NULL in the DB even after a successful audit. Fixed by adding explicit model attribute
assignments for all 30 columns.

### Re-audit Overwrites

A re-audit for any lead MUST overwrite all relevant `audits` columns. No partial update.
This ensures DB state always matches the latest audit code logic.
