# TEB Solutions LeadGen OS — System Reference Document

> **Purpose:** Complete technical reference for AI agents, developers, and continuity.
> If this codebase is opened fresh with no conversation history, reading this file
> gives full context to continue development without missing anything.
> **Current version:** v5.1.0 — Outreach Design Redesign, Inbox Email 2 Modal, Network Ports Migration & Reset Utilities (October 2026)
> **Last updated:** October 7, 2026 (v5.1.0 — Email 1 Redesign, Inbox Email 2 Modal, Ports 8001/5174, Reset Utility)

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Tech Stack](#2-tech-stack)
3. [System Architecture Diagram](#3-system-architecture-diagram)
4. [Full Project File Tree](#4-full-project-file-tree)
5. [Backend Deep-Dive](#5-backend-deep-dive)
6. [Frontend Deep-Dive](#6-frontend-deep-dive)
7. [Data Flow — End to End](#7-data-flow--end-to-end)
8. [Database Schema](#8-database-schema)
9. [API Reference](#9-api-reference)
10. [Email System — Two Templates](#10-email-system--two-templates)
11. [SMTP Configuration](#11-smtp-configuration)
12. [Environment Variables](#12-environment-variables)
13. [How to Run Locally](#13-how-to-run-locally)
14. [Key Design Decisions & Gotchas](#14-key-design-decisions--gotchas)
15. [Known Issues & Future Work](#15-known-issues--future-work)
16. [Changelog](#16-changelog)

---

## 1. What This System Does

**TEB Solutions LeadGen OS** is an internal SaaS tool for the TEB Solutions / Tattavit
web-design agency. It automates the full outreach pipeline:

```
CSV of business leads
       │
       ▼
Upload & deduplicate into PostgreSQL
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│   Site Pre-Check  (site_checker.py v5)                   │
│   13-layer detection pipeline + 4-variant URL fallback   │
│                                                          │
│   URL Chain (per domain, in order):                      │
│     1. https://www.domain  3. http://www.domain          │
│     2. https://domain      4. http://domain              │
│   + requests sync fallback if all aiohttp variants fail  │
│                                                          │
│   Layer 1:  HTTP status (404/500)                        │
│   Layer 2:  Redirect URL parking signal                  │
│   Layer 3:  Thin content (<800 chars)                    │
│   Layer 4:  Parked Tier 1 — strong                       │
│   Layer 5:  Parked Tier 2 — title only                   │
│   Layer 6:  Parked Tier 3 — thin only                    │
│   Layer 7:  Demo  Tier 1 — strong                        │
│   Layer 8:  Demo  Tier 2 — title only                    │
│   Layer 9:  Demo  Tier 3 — thin only                     │
│   Layer 10: Soft-404 (200+notfound title)                │
│   Layer 11: SPA/JS-framework guard (NEW v5)              │
│             React/Vue/Angular/Next.js → REAL immediately │
│   Layer 12: Structural analysis (ONLY <2000 chars)       │
│             (no nav + no contact + <3 links = dead)      │
│   Layer 13: → REAL                                       │
└──────────┬────────────────┬─────────────────────────────┘
           │                │
       NOT REAL          REAL site
           │                │
     Tag audit with      55-Factor SEO Audit
     SITE_STATUS:xxx     (audit_engine.py v5.0)
           │                │
           │            Generate PDF
           │            (ReportLab — pdf_builder.py)
           │                │
           └────────┬───────┘
                    │
           Campaign Email Send
           (outreach_engine.py v5.1.0)
                    │
         ┌──────────┴──────────┐
         │                     │
   REAL site lead         NO-SITE lead
   Branded Design         New Website Email
   Proposal (portfolio    (design pitch,
   proof + soft close)     no audit section)
```

**Key features:**
- JWT-authenticated single-admin portal
- CSV bulk upload with automatic deduplication
- Bulk lead selection with checkboxes (select all / individual)
- Bulk delete and bulk audit from the leads table
- **Site pre-classifier v5** — 13-layer, false-positive resistant detection:
  - **4-variant URL chain** per domain: `https://www → https → http://www → http` — DNS failures on bare domain try www automatically
  - **`requests` sync fallback** after all aiohttp variants fail — with all 4 variants
  - HTTP status codes, redirect URL signals
  - 3-tier keyword matching (strong / title-only / thin-only)
  - Soft-404 detection (HTTP 200 with "not found" page title)
  - **SPA/JS-framework detection** — React, Vue, Angular, Next.js, Svelte, Gatsby, Nuxt sites detected and returned REAL immediately (no false structural check)
  - **Structural analysis** (threshold lowered 8000→2000 chars): no nav + no contact + <3 links = dead site
  - Distinct SSL error vs DNS error reporting
- **Semaphore-based batch audit runner** — `Semaphore(3)` rolling queue; max 3 concurrent audits; individual error isolation; `_BATCH_RUNNING` double-trigger guard; HTTP 409 on duplicate batch
- **Micro-session DB pattern** in `audit_engine.py` — DB connections released during long I/O (crawl/PDF)
- **55-factor async SEO audit engine v5.0** (11 axes: Technical, OnPage, Images, Links, Conversion, UX, Indexability, Content, LocalSEO, Performance, SchemaAdvanced)
- **ReportLab PDF** — multi-section multi-page, 11 performance axes
- **Trust-First email templates** (v4.2.0) — ~120-word plain-text-style emails; single "Reply YES" CTA; pricing deferred to follow-up
- **Two routing paths** — SEO audit email (REAL sites) vs new-website pitch (NO-SITE leads)
- **`_pick_hook()`** — picks single most impactful failing audit finding for personalised email opener
- **Curiosity-gap subject lines** — "One thing I noticed on {domain}" style; bypass spam filters
- **Unsubscribe compliance** — `List-Unsubscribe` header + "Reply STOP" footer in every email
- **IST-aware rotating log** — `logs/leadgen.log`, rotates at midnight IST, 3-day retention
- **Frontend error sink** — `POST /api/logs/frontend` batches JS errors to server log
- **`send_test_email.py`** — standalone script to validate templates without full backend
- Per-account SMTP config (host, port, password, daily limit)
- **Port 465 SMTP_SSL + Port 587 STARTTLS** — auto-detected per account
- **60–90 s** artificial delay between sends (randomised, spam avoidance)
- **No delay after last email** — campaign status updates immediately
- **Campaign auto-polling** — UI updates every 8s during sends (no manual refresh)
- **Live progress indicator** — animated pulse + sent count (e.g. "Sending… 3/5")
- **Campaign reset** — force-reset stuck campaigns via API
- **Test email** — send any lead's template to your own email first
- **Forced re-audit** — re-audit leads that already have results
- **UTC timezone fix** — `UTCBase` Pydantic model + `parseUTC()` frontend helper
- Audit completion polling + animated modal notification in UI
  - `batch_running` guard prevents premature "complete" modal during large batches
  - "Audit All" button disabled while batch is running
- Activity log for all events (timezone-corrected display)
- Dashboard KPI metrics
- **Data Sanitization (v4.3.1)**
  - **URL Root Normalization** — Auto-trims website URLs to root domain (scheme + netloc + /) during CSV import and via maintenance endpoint.
  - **Business Name Cleaning** — Strips taglines and corporate suffixes from business names (truncates at first ` - ` or ` | `) during CSV import and via maintenance endpoint.
- **Campaign audit readiness guard (v4.3.2)** - Campaign Fresh leads require `audits.status = done`; `leads.status = audited` alone is not sufficient. The leads API exposes `audit_status`, the Campaigns UI disables non-ready leads, and `POST /api/campaigns/` rejects selected leads without a successful audit.
- **Database optimization (v4.3.2)** - `pg_trgm` enabled and hot-path indexes added for lead search/status, audit filtering, campaign logs, activity logs, reply filters, and email review filters.
- **Premium Audit Dashboard (v4.4.0)** - Overhauled `Audits.jsx` with a circular SEO score gauge and 5-category grouping.
- **Phase 2 Audit Readiness (v4.4.0)** - Added 8 new nullable boolean columns to the Audit model (canonical, page_title, meta_desc, og_tags, lazy_load, contact, whatsapp, trust).
- **Email 2 Follow-up Workflow (v4.4.0)** - Added `GET /preview-email2/{lead_id}` and `POST /send-email2/{lead_id}` with `Email2Modal` for direct outreach to Converted leads.
- **UI/UX Audit Axis (v4.5.0)** - Added 8 UX checks (CTA, headline, font, contrast, cookie, live chat, nav links) generating 9 new DB columns, weighted at 15%. Displays 6-axis performance rings.
- **55-Factor SEO Expansion (v5.0.0)** - Added 5 new audit modules: `indexability.py` (4 checks), `content.py` (4 checks), `local_seo.py` (5 checks), `performance.py` (6 checks), `schema_advanced.py` (5 checks). Also expanded `technical.py` (+4), `onpage.py` (+5), `ux.py` (+2). 47 new nullable DB columns. 11-axis scoring. SCORE_WEIGHTS rebalanced to sum to 100.
- Inline split-panel campaign creation (no modal, no clipping)

---

## 2. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| **Backend language** | Python 3.14 | 3.10+ required |
| **Backend framework** | FastAPI (async) | Running on port `8001` (`backend/run.py`) |
| **ORM** | SQLAlchemy 2.x (async) | `mapped_column` style |
| **DB driver** | `psycopg` (psycopg3) | NOT asyncpg — binary-compat issue on Python 3.14 |
| **Database** | PostgreSQL | database name: `leadgen` |
| **Web server** | Uvicorn with `--reload` | Port `8001` (avoids 8000 collisions) |
| **PDF generation** | **ReportLab ≥4.0** | Multi-section, multi-page (11 axes, 55 factors) |
| **HTTP client (audit)** | aiohttp (async) | ssl=False for compatibility |
| **HTML parser** | BeautifulSoup4 + lxml | |
| **Auth** | JWT (python-jose) + bcrypt | |
| **Email (send)** | smtplib SMTP_SSL | Port 465, Hostinger (1000 sends/day limit + multi-account rotation) |
| **Email (receive)** | imaplib IMAP4_SSL | Port 993, imap.hostinger.com |
| **Frontend framework** | React 18 + Vite | Running on port `5174` |
| **Frontend styling** | Vanilla CSS | Plain CSS in `index.css` (no Tailwind `@apply`) |
| **Frontend icons** | Lucide React | |
| **Frontend HTTP** | Axios / fetch | `/api` dev proxy to `http://localhost:8001` |
| **Frontend routing** | React Router v6 | |
| **Toasts** | react-hot-toast | |
| **CSV dropzone** | react-dropzone | |

---

## 3. System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  BROWSER  localhost:5174                                         │
│                                                                  │
│  React 18 + Vite SPA                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐  │
│  │Dashboard │ │  Leads   │ │SEO Audit │ │Campaign│ │ Inbox  │  │
│  │KPI cards │ │Checkboxes│ │11-Axis   │ │Create/ │ │Email 2 │  │
│  │activity  │ │Bulk ops  │ │rings +PDF│ │Send/   │ │Modal  │  │
│  │feed      │ │Edit/Clean│ │download  │ │Test    │ │Sync    │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ └───┬────┘  │
│       └────────────┴────────────┴───────────┴──────────┘       │
│                     Axios / fetch — /api/*                      │
│                     (Vite dev proxy → http://localhost:8001)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP :8001
┌──────────────────────────┼──────────────────────────────────────┐
│  FASTAPI  localhost:8001 │                                      │
│                          ▼                                       │
│  app/main.py  (CORS for :5174, lifespan, 7 core router mounts)  │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐   │
│  │  Routers (sync API) │  │  Background Tasks (async)        │   │
│  │                     │  │                                  │   │
│  │ /auth/login         │  │  run_audit(lead_id)              │   │
│  │ /leads/ CRUD        │  │  ├─ 13-layer site checker        │   │
│  │   clean-urls/names  │  │  ├─ 55-factor audit (11 axes)    │   │
│  │ /audits/ trigger    │  │  └─ generate ReportLab PDF       │   │
│  │   trigger-all (Sem3)│  │                                  │   │
│  │   pdf download      │  │  run_campaign(campaign_id)       │   │
│  │ /campaigns/ CRUD    │  │  ├─ Hostinger 1000/day limit cap │   │
│  │   send / send-test  │  │  ├─ if NO-SITE:                  │   │
│  │ /replies/ check-now │  │  │    build_no_site_email()      │   │
│  │   preview/send-email2│ │  └─ if REAL:                     │   │
│  │   reclassify        │  │       build_html_email() [v5.1]  │   │
│  │ /email-review/ scan │  │  _send_email_sync(account)       │   │
│  │   accept / dismiss  │  │  ├─ 60–90s randomized delay      │   │
│  │ /activity/ list     │  │  └─ auto-rotate sender accounts  │   │
│  └─────────────────────┘  └──────────────────────────────────┘   │
│                                                                  │
│  SQLAlchemy Async Session ──────────────────────────────────►   │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PostgreSQL :5432  database: leadgen                             │
│  leads │ audits │ campaigns │ campaign_email_logs               │
│  activity_log │ email_corrections                                │
└──────────────────────────────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
  smtp.hostinger.com:465     smtp.gmail.com:465
  info@tebsolutions.in       tebsolutions.in@gmail.com
  1000 emails/day cap        Multi-account rotation
  SMTP_SSL                   SMTP_SSL
```

---

## 4. Full Project File Tree

```
LEADGEN/
├── START.bat                    ← One-click: backend + frontend + opens browser
├── STOP.bat                     ← Kills all python.exe and node.exe processes
├── SYSTEM.md                    ← THIS FILE — full technical reference
├── README.md                    ← Quick-start guide
├── ARCHITECTURE.md              ← Plain-language guide + visual diagrams (for all readers)
├── AI_PROMPT.md                 ← Copy-paste prompt to onboard any new AI agent
├── pyrightconfig.json           ← Pyrefly linter config (extraPaths: backend) [NEW v4.0]
├── sample_leads.csv             ← Test data (business_name,email,phone,website)
├── leads/                       ← Directory containing raw/clean lead CSV files
│
├── backend/
│   ├── run.py                   ← [NEW v5.1.0] Custom launcher running uvicorn on port 8001
│   ├── reset_leads_to_fresh.py  ← [NEW v5.1.0] DB reset & audit state synchronization utility
│   ├── send_test_email.py       ← Standalone template tester (uses port 8001 / live DB)
│   ├── gen_preview.py           ← Email 1 HTML template preview generator
│   ├── email_preview.html       ← Live HTML preview of redesigned Email 1 template
│   ├── .env                     ← Active secrets — never commit
│   ├── .env.example             ← Safe template for new setups
│   ├── requirements.txt         ← Python dependencies (ReportLab, requests, psycopg, etc.)
│   ├── reports/                 ← Generated PDFs: {lead_id}.pdf (auto-created)
│   └── app/
│       ├── main.py              ← FastAPI app, CORS, lifespan, router mounts + /api/logs/frontend
│       ├── config.py            ← Settings from .env, get_smtp_accounts() JSON parser
│       ├── database.py          ← AsyncEngine, AsyncSessionLocal, Base, get_db()
│       ├── logger.py            ← IST-aware TimedRotatingFileHandler, 3-day retention
│       ├── models.py            ← Lead (+reply cols), Audit, Campaign, ActivityLog, EmailCorrection ORM
│       ├── schemas.py           ← Pydantic schemas + UTCBase + reply fields [updated v4.0]
│       │
│       ├── routers/
│       │   ├── auth.py          ← POST /auth/login → JWT token
│       │   ├── leads.py         ← CSV upload, list, get, delete, bulk-delete, clean-urls, clean-names
│       │   ├── audits.py        ← Trigger audit (BG), get audit, PDF stream, batch runner
│       │   ├── campaigns.py     ← Create, list, send, reset, send-test (BG)
│       │   ├── activity.py      ← Event log list + /metrics KPI endpoint
│       │   ├── replies.py       ← [v5.1.0] /check-now, /converted, /preview-email2/{id}, /send-email2/{id}, PATCH /reclassify/{id}
│       │   └── email_review.py  ← Scan engine + accept/dismiss corrections (5 endpoints)
│       │
│       ├── engines/
│       │   ├── audit_engine.py  ← Bridge to auditor/ package (55-factor runner, micro-sessions)
│       │   ├── reply_engine.py  ← IMAP fetch + classify + DB actions
│       │   └── outreach_engine.py ← [v5.1.0] Redesigned modern card Email 1, portfolio strip, Email 2 proposal
│       │
│       └── utils/
│           ├── csv_parser.py    ← Parse, clean, normalise CSV rows + sanitization
│           ├── site_checker.py  ← classify_site(): 13-layer detection v5 (4-variant URL, SPA guard)
│           └── spintax.py       ← {opt1|opt2} resolver + variable substitution
│
├── auditor/                     ← 55-factor SEO & UX audit package (v5.0.0)
│   └── auditor/
│       └── auditor/
│           ├── __init__.py
│           ├── core.py          ← fetch_page, make_session, result_pass/warn/fail
│           ├── technical.py     ← audit_ssl, sitemap, robots, canonical, favicon, mobile + 4 new (v5.0)
│           ├── onpage.py        ← audit_h1, meta, images, links + 5 new (v5.0)
│           ├── images.py        ← audit_alt_text, webp, lazy_loading
│           ├── links.py         ← audit_broken_links
│           ├── social.py        ← audit_social_links, contact, whatsapp
│           ├── trust.py         ← audit_trust_pages
│           ├── ux.py            ← audit_cta, hero, font, contrast, cookie, chat + 2 new (v5.0)
│           ├── indexability.py  ← noindex, url_structure, www_vs_nonwww, soft_404
│           ├── content.py       ← word_count, duplicate_meta, keyword_in_title, reading_level
│           ├── local_seo.py     ← nap, local_business_schema, maps, city_in_title, hours
│           ├── performance.py   ← response_time, page_size, render_blocking, gzip, webp, minification
│           ├── schema_advanced.py ← faq, product, breadcrumb, review, @graph schemas
│           ├── crawler.py       ← crawl_site, audit_page_seo, aggregate_site_issues
│           ├── pdf_builder.py   ← ReportLab multi-section PDF generator
│           └── runner.py        ← Orchestrates all 55+ checks → final result
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js           ← server.port: 5174, server.proxy /api → http://localhost:8001
    └── src/
        ├── main.jsx             ← ReactDOM.createRoot(<App/>)
        ├── App.jsx              ← BrowserRouter, JWT auth guard, Sidebar layout
        ├── index.css            ← Design tokens: plain CSS (no Tailwind @apply)
        │
        ├── api/
        │   └── client.js        ← Axios instance + JWT interceptor + all API fns
        │
        ├── components/
        │   └── Layout.jsx       ← Sidebar nav + Inbox badge
        │
        └── pages/
            ├── Login.jsx        ← Credential form → /auth/login → store JWT
            ├── Dashboard.jsx    ← KPI cards + live activity feed
            ├── Leads.jsx        ← Table, checkboxes, bulk ops, audit polling modal
            ├── Audits.jsx       ← Expandable 55-factor rows, 6-axis rings, PDF download
            ├── Campaigns.jsx    ← Inline split-panel + test email + auto-poll
            ├── EmailReview.jsx  ← Email mismatch review: stat cards, filter tabs, accept/dismiss
            ├── ActivityLog.jsx  ← Chronological event stream, UTC parseUTC() fix
            └── Inbox.jsx        ← [v5.1.0] Converted Leads + Email 2 Preview/Edit/Send Modal + Auto-Attach PDF
```

---

## 5. Backend Deep-Dive

### `app/config.py`
```python
class Settings(BaseSettings):
    DATABASE_URL: str       # postgresql+psycopg://...
    JWT_SECRET: str
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str
    SMTP_SENDERS: str = "[]"   # JSON array — each has email/smtp_host/smtp_port/password/daily_limit

    def get_smtp_accounts(self) -> list[dict]:
        return json.loads(self.SMTP_SENDERS)
```

### `app/database.py`
```python
# ⚠️ No pool_size/max_overflow — incompatible with psycopg async driver
engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

### `app/models.py`

#### Lead
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | auto |
| business_name | String(255) | |
| email | String(255) | UNIQUE |
| phone | String(50) | nullable |
| website | String(500) | |
| status | Enum | `new/auditing/audited/emailed/replied` |
| created_at | DateTime | auto |

Relationships: `audit` and `activity_logs` both use **`passive_deletes=True`** (critical — see §14).

#### Audit
| Column | Type | Notes |
|---|---|---|
| lead_id | UUID FK | `ON DELETE CASCADE` |
| error_message | Text | **Dual-purpose**: real error OR `"SITE_STATUS:parked"` etc. |
| status | Enum | `pending/running/done/failed` |
| ssl_valid, has_sitemap, has_robots | Boolean | |
| broken_links_count, missing_alt_count | Integer | |
| missing_h1, uses_webp, has_json_ld, mobile_friendly | Boolean | |
| has_canonical, has_page_title, has_meta_desc, has_og_tags | Boolean | Phase 2 (v4.4.0) |
| has_lazy_load, has_contact, has_whatsapp, has_trust | Boolean | Phase 2 (v4.4.0) |
| has_cta, cta_above_fold, has_hero_headline, font_size_ok | Boolean | UX Axis (v4.5.0) |
| contrast_ok, has_cookie_notice, has_live_chat | Boolean | UX Axis (v4.5.0) |
| nav_links_count, ux_score | Integer | UX Axis (v4.5.0) |
| missing_social | JSON | `["facebook","twitter",...]` |
| audit_summary | Text | auto-generated narrative |
| pdf_path | String | `reports/{id}.pdf` |

**⚠️ `error_message` dual-purpose field:**
- Real error: plain string
- Skipped site: `"SITE_STATUS:parked"` / `"SITE_STATUS:demo"` / `"SITE_STATUS:not_found"` / `"SITE_STATUS:unreachable"`
- Always use `parse_site_status(msg)` to distinguish — returns `None` for real errors

---

### `app/utils/site_checker.py` — v5 (13-Layer Pipeline + 4-Variant URL)

**Entry:** `classify_site(url) → (SiteType, reason_str)`

**SiteType:** `REAL | PARKED | DEMO | NOT_FOUND | UNREACHABLE`

**URL Fallback Chain (NEW v5):**
For every domain, tries all 4 variants in order before falling back to `requests`:
```
1. https://www.domain.com   ← tried first (most business sites prefer www)
2. https://domain.com
3. http://www.domain.com    ← SSL not configured but www may work
4. http://domain.com        ← last resort
```
- DNS failure on one variant → try next (NOT immediately UNREACHABLE)
- SSL error on https → try http variants
- All aiohttp variants fail → `requests` sync fallback (also with all 4 variants)

```
Layer  1: HTTP 404/410/451 → NOT_FOUND
Layer  2: HTTP 500/502-504 → UNREACHABLE (continue to next variant)
Layer  3: Redirect URL contains parking provider string → PARKED
Layer  4: Body < 800 chars → PARKED (always empty/parked)
Layer  5: PARKED_STRONG — match anywhere in body (unambiguous phrases)
Layer  6: PARKED_TITLE  — match only in <title> tag
Layer  7: PARKED_THIN   — match in body only if body < 3,000 chars
Layer  8: DEMO_STRONG   — match anywhere (server defaults, suspensions)
Layer  9: DEMO_TITLE    — match only in <title> (coming soon, maintenance, site offline...)
Layer 10: DEMO_THIN     — match in body only if body < 3,000 chars
Layer 11: SOFT_404      — title says "page not found" despite HTTP 200
Layer 12: SPA GUARD     — if body < 2,000 chars AND JS framework detected → REAL
           Detects: React (id="root"), Angular (<app-root), Next.js (/_next/static/),
                    Vue (id="app"), Nuxt (id="__nuxt"), Svelte, chunk.*.js, bundle.js
           Rationale: SPAs deliver empty HTML shells — structural check would false-flag them
Layer 13: STRUCTURAL    — body < 2,000 chars AND no nav AND no contact AND <3 links → DEMO
Layer 14: → REAL
```

**Structural analysis (Layer 13) — tightened v5:**
```python
# Threshold lowered: 8000 → 2000 chars  (was catching real small-business sites)
# Link threshold lowered: 5 → 3 links   (was too strict for minimalist one-pagers)
no_nav     = not (<nav> or menu class or role="navigation")
no_contact = not (tel: link or mailto: or phone number pattern)
few_links  = meaningful hrefs < 3   # was 5 in v3/v4

if no_nav AND no_contact AND few_links:
    → DEMO (structurally dead site)
```

**Signals removed in v5 (were causing false positives on real sites):**
| Signal | Was In | Reason Removed |
|---|---|---|
| `"under construction"` | DEMO_THIN | Appears in real site footers/banners |
| `"coming soon"` | DEMO_THIN | Real sites use: "New products coming soon" |
| `"page not found"` | DEMO_TITLE | Moved to SOFT_404_TITLE only |
| `"temporarily unavailable"` | DEMO_TITLE | Maintenance banners on live sites |

**Helper functions:**
```python
_url_variants(url)      → list[str]       # build 4 variants for any URL
_has_js_framework(html) → bool            # detect SPA frameworks
site_status_tag(SiteType)  → "SITE_STATUS:parked"   # write to DB
parse_site_status(str)     → SiteType | None          # read from DB
```

---

### `app/engines/audit_engine.py` — Micro-Session Pattern (v4.1.0)

```
run_audit(lead_id):
  1. [Micro-session] Load lead; create/find Audit; set status=running
  2. classify_site(url) → site_type      ← 13-layer, 4-variant URL
     ├─ NOT REAL: [micro-session] write SITE_STATUS tag, log, RETURN
     └─ REAL: continue (no session held during network I/O)
  3. SSL check (sync in executor)
  4. aiohttp.get(url) → fetch HTML → BeautifulSoup parse
  5. Concurrent: check_sitemap() | check_robots() | check_broken_links()
     └─ check_robots(): CRITICAL FAIL = only when Disallow: / (literal "/") under User-agent: *
        with no Allow: / override. Sub-path blocks (/wp-admin/, /search/ etc.) are NEVER a FAIL.
        A standard WordPress robots.txt always returns PASS (Guardrail #35 / #42).
  6. DOM: h1, alt, webp, json_ld, mobile, social
  7. build_summary() → audit_summary text
  8. [Micro-session] Save all → audit.status=done, lead.status=audited
  9. generate_pdf(lead, audit)    ← no session held during PDF generation
 10. [Micro-session] Log "audit_done"

Key: DB connections are ONLY held during DB reads/writes,
     never during crawl (45s) or PDF generation (5s).
```

---

### `app/routers/audits.py` — Semaphore Batch Runner (v4.1.0)

```python
_AUDIT_SEMAPHORE = asyncio.Semaphore(3)   # max 3 concurrent crawls
_BATCH_RUNNING   = False                  # double-trigger guard

# POST /audits/trigger-all → run_batched() as BackgroundTask
async def run_batched(lead_ids):
    global _BATCH_RUNNING
    _BATCH_RUNNING = True
    try:
        async def guarded(lead_id):
            async with _AUDIT_SEMAPHORE:   # blocks if 3 already running
                try:
                    await run_audit(lead_id)
                except Exception as e:
                    log(e)  # isolated — other audits continue
        await asyncio.gather(*[guarded(id) for id in lead_ids])
    finally:
        _BATCH_RUNNING = False

# GET /audits/stats → {batch_running, total, pending, done, failed}
# Used by frontend to track batch state and guard the completion modal
```

**Double-trigger protection:** If `_BATCH_RUNNING` is True when trigger-all is called → HTTP 409 Conflict returned immediately.



### `app/engines/pdf_engine.py`

**Font safety:** `_safe(text)` replaces all non-Latin-1 characters before any FPDF2 output.

**4-section PDF:**
1. Header (blue bar, business name, date)
2. Executive Summary + lead contact details
3. 10-row Technical SEO Table (PASS/FAIL per factor)
4. Deep Impact Analysis (only for FAILING factors): what it is / Google impact / business impact / fix
5. Priority Fix Checklist
6. Service Tiers ($25 / $60 / $150)

---

### `app/engines/outreach_engine.py` (v4.2.0 overhaul)

**Smart routing:**
```python
site_type = parse_site_status(audit.error_message)

if site_type in (PARKED, DEMO, NOT_FOUND, UNREACHABLE):
    html    = build_no_site_email(lead, site_type.value)
    subject = random.choice(NO_SITE_SUBJECT_VARIANTS).format(...)
else:
    html    = build_html_email(lead, audit)
    subject = random.choice(SUBJECT_VARIANTS).format(domain=domain)

# Per-account SMTP config:
if smtp_port == 465: smtplib.SMTP_SSL(host, port)
else:                smtplib.SMTP(host, port) + .starttls()

# Delay only BETWEEN sends (not after last email):
is_last = (lead_ids.index(lead_id_str) == len(lead_ids) - 1)
if is_last:
    campaign.status = CampaignStatus.done  # immediate
else:
    await asyncio.sleep(random.randint(60, 90))  # 60–90 s
```

**`_pick_hook(audit)` — Personalised finding for email opener:**
Priority order: SSL → H1 → Sitemap → Mobile → JSON-LD → Robots → Alt text → fallback generic

**Subject line variants (curiosity-gap):**
```python
SUBJECT_VARIANTS = [
    "One thing I noticed on {domain}",
    "Quick find on {domain}",
    "{domain} — spotted something",
    "Found something on {domain}",
]
```

**Email #1 philosophy:** Trust-first (no pricing, no service list, no brochure). Only CTA: "Reply YES".
Pricing and service tiers reserved for Email #2 (after lead replies).

**HTML email size:** ~5,500 bytes (was ~62,000 bytes — 91% reduction).

**NameError fix (v4.2.0):** `_send_email_sync` no longer references `lead` (which is not in its scope). Plain-text fallback body is now static.

**Constants (updated April 2026):**
```python
MIN_DELAY_SECONDS = 60     # 1 minute
MAX_DELAY_SECONDS = 90     # 1.5 minutes
```

---

## 6. Frontend Deep-Dive

### Proxy
`vite.config.js` proxies `/api` → `http://localhost:8001` (configured on port 5174) — no CORS issues in dev.

### `src/api/client.js`
```js
// Request interceptor:  attach Bearer token from localStorage
// Response interceptor: auto-logout on 401

// Functions:
login | uploadLeads | getLeads | deleteLead | bulkDeleteLeads
triggerAudit | triggerAllAudits | getAudit | getPdfUrl
getCampaigns | createCampaign | sendCampaign | sendTestEmail
getActivity | getMetrics
```

### `src/pages/ActivityLog.jsx` — UTC Timezone Fix
```js
// Backend stores datetimes as naive UTC without 'Z' suffix.
// parseUTC() appends 'Z' so JavaScript treats strings as UTC.
function parseUTC(str) {
  if (!str) return new Date()
  if (/[Z+]/.test(str.slice(-6))) return new Date(str)
  return new Date(str + 'Z')
}

// Combined with schemas.py UTCBase on the backend, this fully fixes
// the ~5.5 hour timezone shift that IST users experienced.
```

### Leads Page — Audit Polling
```
User clicks audit
  → triggerAudit(id) → add id to pendingAuditIds Set

useEffect([pendingAuditIds]):
  setInterval every 5 seconds
    → getLeads(1, 500)
    → check: any pendingAuditIds still status="auditing"?
    → if none left: clearInterval → show AuditDoneModal
    → if some left: update pendingAuditIds

AuditDoneModal (custom animated modal):
  → Green checkmark, "Audit Complete!", count
  → "OK — Refresh" → fetchLeads()
```

### Campaigns Page — Inline Split-Panel + Auto-Poll
```
Formerly: modal-based → clipped above viewport
Now:      inline split-panel — left = campaign table, right = creation form
          TestPanel = floating bottom-right card for sending test emails

Auto-poll (added April 2026):
  useEffect watches campaigns for any with status === 'sending'
  If found → setInterval(pollCampaigns, 15_000)
  pollCampaigns() silently fetches just campaign list (no lead refresh)
  When all campaigns finish → clearInterval → polling stops

Live status badge:
  ⬤ (animated pulse) Sending… 2/5
  ✓ Complete
```

### CSS System
Plain CSS in `index.css` — NOT Tailwind `@apply` (removed due to blank screen bug).

---

## 7. Data Flow — End to End

### A. Upload
```
CSV drop → POST /api/leads/upload → parse + deduplicate → INSERT leads
         ← {imported: N, skipped_duplicates: M}
```

### B. Audit
```
Click 🔍 → POST /api/audits/trigger/{id} → BackgroundTask → 202
         ← UI adds to pendingAuditIds, polls every 5s
         ← Backend: classify_site → [skip|audit] → pdf → log
         ← UI: all done? → AuditDoneModal → OK → fetchLeads()
```

### C. Campaign
```
Create → POST /api/campaigns/ → Campaign record (status=draft)
Send   → POST /api/campaigns/{id}/send → BackgroundTask → 202
       ← Frontend starts auto-polling every 15s
       ← Backend: for each lead:
           parse_site_status → route template
           pick account (round-robin)
           SMTP send (SSL/STARTTLS)
           lead.status = emailed, campaign.sent_count++
           Is last lead? → campaign.status = done (no sleep)
           Not last?     → sleep 4–10 min
       ← Frontend polls: badge auto-updates "Sending… 3/5"
       ← Campaign done → "✓ Complete" → polling stops

Reset  → POST /api/campaigns/{id}/reset → force-reset to draft
Retry  → POST /api/campaigns/{id}/send?force=true → reset + re-launch
```

### D. Delete (Single)
```
DELETE /api/leads/{id} → db.delete(lead) → passive_deletes → DB CASCADE
```

### E. Bulk Delete
```
POST /api/leads/bulk-delete {ids:[...]}
  → DELETE FROM audits WHERE lead_id IN (ids)   ← explicit (bulk SQL bypasses ORM)
  → DELETE FROM leads WHERE id IN (ids)
```

---

## 8. Database Schema

### Performance Indexes & Maintenance (v4.3.2)

PostgreSQL has `pg_trgm` enabled for fast partial matching on lead business names and emails. Hot-path indexes were added for:
- `leads`: status/date lists, created date, reply filters, email scan date, trigram search on `business_name` and `email`
- `audits`: status filters and `SITE_STATUS:%` skipped-site lookups
- `campaigns`: status and created date
- `campaign_email_logs`: campaign log expansion and daily sent-count checks
- `activity_log`: newest-first activity stream and event/date metrics
- `email_corrections`: status/date filters

Safe maintenance performed on April 24, 2026:
- 123 stale `audits.status = running` rows older than 30 minutes were reset to `failed`.
- 5 stale `leads.status = auditing` rows were reset to `new`.
- Orphan checks returned 0 for audits, activity logs, campaign logs, and email corrections.
- `VACUUM (ANALYZE)` was run on all core tables.

```sql
CREATE TYPE leadstatus    AS ENUM ('new','auditing','audited','emailed','replied','converted');
CREATE TYPE auditstatus   AS ENUM ('pending','running','done','failed');
CREATE TYPE campaignstatus AS ENUM ('draft','scheduled','sending','done');
CREATE TYPE correctionstatus AS ENUM ('pending','accepted','dismissed');  -- NEW v4.3.0

CREATE TABLE leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_name VARCHAR(255) NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL,
  phone VARCHAR(50),
  website VARCHAR(500) NOT NULL,
  status leadstatus DEFAULT 'new',
  last_emailed_at TIMESTAMP,
  replied_at TIMESTAMP,
  reply_snippet TEXT,
  reply_type VARCHAR(30),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID UNIQUE NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  ssl_valid BOOLEAN, has_sitemap BOOLEAN, has_robots BOOLEAN,
  broken_links_count INTEGER DEFAULT 0,
  missing_h1 BOOLEAN, missing_alt_count INTEGER DEFAULT 0,
  uses_webp BOOLEAN, has_json_ld BOOLEAN, mobile_friendly BOOLEAN,
  has_canonical BOOLEAN, has_page_title BOOLEAN, has_meta_desc BOOLEAN,
  has_og_tags BOOLEAN, has_lazy_load BOOLEAN, has_contact BOOLEAN,
  has_whatsapp BOOLEAN, has_trust BOOLEAN,
  has_cta BOOLEAN, cta_above_fold BOOLEAN, has_hero_headline BOOLEAN,
  font_size_ok BOOLEAN, contrast_ok BOOLEAN, nav_links_count INTEGER,
  has_cookie_notice BOOLEAN, has_live_chat BOOLEAN, ux_score INTEGER,
  missing_social JSON,
  -- v5.0 Technical Extended
  has_https_redirect BOOLEAN, redirect_chain_ok BOOLEAN,
  has_mixed_content BOOLEAN, www_canonical_ok BOOLEAN,
  -- v5.0 Onpage Extended
  has_noindex BOOLEAN, heading_hierarchy_ok BOOLEAN,
  internal_links_count INTEGER, anchor_text_ok BOOLEAN, image_filenames_ok BOOLEAN,
  -- v5.0 UX Extended
  has_phone_number BOOLEAN, has_address BOOLEAN,
  -- v5.0 Indexability
  url_structure_ok BOOLEAN, www_nonwww_ok BOOLEAN, soft_404_ok BOOLEAN,
  -- v5.0 Content Quality
  word_count INTEGER, duplicate_meta_ok BOOLEAN,
  keyword_in_title_ok BOOLEAN, reading_level_ok BOOLEAN,
  -- v5.0 Local SEO
  has_nap BOOLEAN, has_local_business_schema BOOLEAN,
  has_google_maps BOOLEAN, city_in_title_ok BOOLEAN, has_business_hours BOOLEAN,
  -- v5.0 Performance
  response_time_ms INTEGER, page_size_ok BOOLEAN,
  render_blocking_ok BOOLEAN, gzip_enabled BOOLEAN,
  webp_coverage_ok BOOLEAN, minification_ok BOOLEAN,
  -- v5.0 Schema Advanced
  has_faq_schema BOOLEAN, has_product_schema BOOLEAN,
  has_breadcrumb_schema BOOLEAN, has_review_schema BOOLEAN, schema_graph_ok BOOLEAN,
  audit_summary TEXT,
  suggested_name VARCHAR(500),
  pdf_path VARCHAR(500),
  status auditstatus DEFAULT 'pending',
  error_message TEXT,   -- "SITE_STATUS:xxx" if skipped; real error otherwise
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
  -- Run migration: backend/migrations/v5_0_0_audit_columns.sql

CREATE TABLE campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  lead_ids JSON DEFAULT '[]',
  pending_lead_ids JSON DEFAULT '[]',
  template TEXT NOT NULL,
  subject_template VARCHAR(500) DEFAULT '',
  scheduled_at TIMESTAMP,
  sent_count INTEGER DEFAULT 0,
  skipped_count INTEGER DEFAULT 0,
  failed_count INTEGER DEFAULT 0,
  next_email_at TIMESTAMP,
  paused_at TIMESTAMP,
  status campaignstatus DEFAULT 'draft',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE activity_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type VARCHAR(100) NOT NULL,
  lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
  message TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- NEW v4.3.0
CREATE TABLE email_corrections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  old_email VARCHAR(255) NOT NULL,
  new_email VARCHAR(255) NOT NULL,
  domain VARCHAR(255),
  status correctionstatus DEFAULT 'pending',
  detected_at TIMESTAMP DEFAULT NOW(),
  resolved_at TIMESTAMP
);
```

---

## 9. API Reference

All require `Authorization: Bearer <JWT>` except `/api/auth/login`.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{access_token}` |
| POST | `/api/leads/upload` | multipart file upload |
| GET | `/api/leads/` | `?page&page_size&status` |
| GET | `/api/leads/` response | Includes `audit_status`; Campaigns uses it to identify successful audits |
| DELETE | `/api/leads/{id}` | cascades to audit |
| POST | `/api/leads/bulk-delete` | `{ids:[...]}` |
| POST | `/api/leads/clean-urls` | Bulk-trim all existing URLs to root (v4.3.1) |
| POST | `/api/leads/clean-names` | Bulk-strip taglines from all names (v4.3.1) |
| POST | `/api/audits/trigger/{id}` | 202, background task |
| POST | `/api/audits/trigger-all` | semaphore-based rolling queue; 409 if batch already running |
| GET | `/api/audits/stats` | `{batch_running, total, pending, done, failed}` |
| GET | `/api/audits/{lead_id}` | audit record |
| GET | `/api/audits/pdf/{lead_id}` | streams PDF |
| GET | `/api/campaigns/` | list all |
| POST | `/api/campaigns/` | create; rejects lead IDs whose audit is missing or not `done` |
| POST | `/api/campaigns/{id}/send` | `?force=true` to reset + re-launch |
| POST | `/api/campaigns/{id}/reset` | force-reset stuck campaign to draft |
| POST | `/api/campaigns/send-test` | `{lead_id, to_email}` — direct test send of Email 1 without campaign |
| GET | `/api/activity/` | `?limit=50` |
| GET | `/api/activity/metrics` | `{total_leads, audited, emailed, replied}` |
| POST | `/api/replies/check-now` | Sync IMAP inbox (sync, returns stats) |
| GET | `/api/replies/converted` | List converted (positive reply) leads with audit & reply context |
| GET | `/api/replies/stats` | `{converted, soft_bounce, deleted_today}` |
| **GET** | **`/api/replies/preview-email2/{id}`** | **[NEW v5.1.0] Preview proposal HTML & subject for converted lead** |
| **POST** | **`/api/replies/send-email2/{id}`** | **[NEW v5.1.0] Send Email 2 proposal + auto-attach PDF audit report** |
| PATCH | `/api/replies/reclassify/{id}` | `?target_category=negative|inquiry` — demote false positive, resets status to emailed |
| POST | `/api/email-review/scan` | Scan all leads for domain-matched email mismatches |
| GET | `/api/email-review/` | List corrections (`?status=pending|accepted|dismissed`) |
| GET | `/api/email-review/stats` | `{pending, accepted, dismissed}` counts |
| POST | `/api/email-review/{id}/accept` | Accept: update lead email + reset to new |
| POST | `/api/email-review/{id}/dismiss` | Dismiss correction (no lead DB change) |

---

## 10. Email System — Redesigned Two-Tier Engine (v5.1.0)

### Email 1: First Touch Technical Review & Redesign Intro (REAL sites)

The primary cold outreach template underwent a complete structural and aesthetic overhaul in v5.1.0:

- **Layout:** 600px responsive email card optimized for Gmail, Apple Mail, and Outlook.
- **Header:** `#0d1b2a` deep navy container featuring the official TEB Solutions / Tattavit logo banner.
- **Service Badge:** Pill indicator: `Website Design • Redesign • Technical Review`.
- **Opening:** Contextualized domain assessment note (`build_html_email(audit)`).
- **Core Usability Pillars:** Highlights 4 core digital experience pillars:
  1. *Mobile layout & responsive structure*
  2. *Page load speed & asset weight*
  3. *Clear calls-to-action & contact access*
  4. *Search engine metadata & indexability*
- **Live Portfolio Proof Strip:** Directly showcases verified past deliverables:
  - `Hexaprime.me` (Digital infrastructure & systems)
  - `Channelnexus.me` (Enterprise media & commerce)
  - `Sketchlife.ae` (Bespoke design studio & brand)
- **Technical Review 2x2 Grid:** Summary assessment cards reflecting observed frontend performance.
- **Soft Informational Closing:** Eliminates high-pressure sales hooks:
  > *"These observations are shared purely as helpful context for your team. There is no expectation or need to reply unless you find this relevant."*
- **Subject Variations (Curiosity-Gap Spintax):**
  - `"One thing I noticed on {domain}"`
  - `"Quick find on {domain}"`
  - `"{domain} — spotted something"`
  - `"Found something on {domain}"`
- **Deliverability & Unsubscribe:** Clean RFC 2369 `List-Unsubscribe` headers and direct footer opt-out.

### Email 1: No-Site / Broken Domain Template (NO-SITE leads)

For domains identified as `PARKED`, `DEMO`, `NOT_FOUND`, or `UNREACHABLE` by `site_checker.py`:
- Contextual opening identifying absence of an active commercial website.
- Offer for turnkey custom website design and brand launch.
- Subjects:
  - `"Quick question about {business_name}'s online presence"`
  - `"{business_name} — one thing I noticed"`

### Email 2: Converted Lead Proposal & Attached PDF Audit (Follow-up)

When a recipient replies positively (detected via IMAP keyword classifier):
- Lead transitions to `status = 'converted'`.
- Appears on [Inbox.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Inbox.jsx) Converted Leads table.
- Admin triggers **Email 2 Preview/Send Modal**:
  - `GET /api/replies/preview-email2/{id}` renders tailor-made proposal HTML.
  - Interactive modal allows subject and HTML body live editing.
  - On confirm, `POST /api/replies/send-email2/{id}` sends the proposal via SMTP and **automatically attaches the generated PDF audit report** (`reports/{lead_id}.pdf`).
  - Sets `lead.email2_sent_at = NOW()` and logs the dispatch.

---

## 11. SMTP Configuration

### Active Accounts & Rotation
Configured via `SMTP_SENDERS` in `.env`:
```json
[
  {"email":"info@tebsolutions.in","smtp_host":"smtp.hostinger.com",
   "smtp_port":465,"password":"...","daily_limit":80},
  {"email":"tebsolutions.in@gmail.com","smtp_host":"smtp.gmail.com",
   "smtp_port":465,"password":"...","daily_limit":50}
]
```

| Port | Protocol | Class |
|---|---|---|
| 465 | Direct SSL | `smtplib.SMTP_SSL(host, port)` |
| 587 | STARTTLS | `smtplib.SMTP(host, port)` + `.starttls()` |

- **Daily Cap Enforcement:** Hostinger limits enforced up to 1,000 sends/day per account with round-robin sender account switching in `outreach_engine.py`.
- **Interval Delays:** 20–30s jittered delay between outbound emails to protect sender domain reputation.

---

## 12. Environment Variables

```env
DATABASE_URL=postgresql+psycopg://postgres:Misthy31$@localhost:5432/leadgen
JWT_SECRET=144d07b7...
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440
ADMIN_USERNAME=admin
ADMIN_PASSWORD=Misthy31$
SMTP_SENDERS=[{"email":"info@tebsolutions.in",...},{"email":"tebsolutions.in@gmail.com",...}]
APP_NAME=TEB Solutions LeadGen
FRONTEND_URL=http://localhost:5174
REPORTS_DIR=reports
```

---

## 13. How to Run Locally

### Option A — One Click
Double-click `LEADGEN\START.bat`. It executes:
- Backend on port **8001** via `backend/run.py` (or `python -m uvicorn app.main:app --port 8001`)
- Frontend on port **5174** via `npm run dev`
- Automatically opens default browser to `http://localhost:5174`

### Option B — Manual

```powershell
# Backend (Port 8001)
cd backend
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
python run.py
# (or: python -m uvicorn app.main:app --reload --port 8001)

# Frontend (Port 5174)
cd frontend
npm install
npm run dev
```

Login at **http://localhost:5174** (default credentials: `admin` / `Misthy31$`).

---

## 14. Key Design Decisions & Gotchas

| Gotcha | Root Cause | Fix Applied |
|---|---|---|
| Python 3.14 + asyncpg broken | Binary compilation fails | Use `psycopg` driver |
| SQLAlchemy pool args fail | psycopg incompatibility | Removed `pool_size`/`max_overflow` |
| Lead deletion FK constraint | SQLAlchemy tries SET NULL on NOT NULL col | `passive_deletes=True` on both relationships |
| Bulk SQL bypasses ORM cascade | `delete()` doesn't fire ORM events | Explicit `DELETE audits` before `DELETE leads` |
| Tailwind @apply blank screen | PostCSS fails silently | Plain CSS throughout `index.css` |
| lucide-react CheckSquare missing | Not in installed version | Native `<input type="checkbox">` with `ref` for indeterminate |
| PDF Helvetica crashes on Unicode | Latin-1 only font (FPDF2) | `_safe()` strips all non-Latin-1 chars; v4.0 uses ReportLab |
| SITE_STATUS dual-purpose field | `error_message` used for two things | Use `parse_site_status()` always |
| Port 465 hangs with STARTTLS | Wrong SMTP class for SSL port | Auto-detect: 465→`SMTP_SSL`, 587→`SMTP+starttls` |
| site_checker false positives | Generic signals matched real sites | 3-tier system + structural analysis (v3/v4) |
| SPA sites wrongly flagged DEMO | Structural check on React/Vue shell HTML | `_has_js_framework()` guard before structural (v5) |
| Valid sites flagged UNREACHABLE | Only one URL variant tried | 4-variant URL chain: https/http × www/bare (v5) |
| Structural threshold too high (8000) | Clean small-business HTML under 8KB | Lowered to 2000 chars (v5) |
| Modal clipped at top | `items-center` overflows above viewport | Replaced with inline split-panel (no modal) |
| Status stuck at 'sending' | `asyncio.sleep()` after last email | Skip delay after last lead, set done immediately |
| 5.5h timezone shift | Naive UTC treated as local time by JS | `UTCBase` serializer + `parseUTC()` helper |
| Empty lead lists in Campaign | `page_size` limit too low (200) | Raised to 500, fixed variable shadowing |
| Campaign not re-launchable | 409 error on stuck campaigns | `force=true` query param resets + re-launches |
| Campaign Fresh included stale/failed audits | UI used `lead.status=audited` only | v4.3.2 uses `audit_status=done` and backend validates campaign creation |
| Auditor import error in linter | gen_preview.py at root uses os.chdir at runtime | `pyrightconfig.json` with `extraPaths: ["backend"]` |
| Auditor triple-nesting | Import path resolution from audit_engine.py | sys.path.insert(0, ...) at module load |
| Reply engine IMAP auth | Must use first SMTP_SENDERS entry credentials | reply_engine uses `settings.get_smtp_accounts()[0]` |
| LeadStatus enum extension | `converted` must be added to PG enum before use | `ALTER TYPE leadstatus ADD VALUE IF NOT EXISTS 'converted'` |
| DB pool exhaustion on Audit All | Unbounded asyncio.gather on 400+ leads | Semaphore(3) rolling queue in `run_batched()` (v4.1.0) |
| Double batch trigger | No guard on rapid "Audit All" clicks | `_BATCH_RUNNING` flag + HTTP 409 Conflict (v4.1.0) |
| DB connections held too long | Single session across 45s crawl | Micro-session pattern in `audit_engine.py` (v4.1.0) |
| Premature "Audit Complete" modal | Gap between semaphore slots looked like done | `batch_running` guard on modal condition (v4.1.0) |
| Badge `audit_error` rendered wrong | `.replace()` only replaces first underscore | Changed to `.replaceAll()` in `Leads.jsx` (v4.1.0) |
| Near-zero email conversion | Brochure-style 62KB emails; multiple CTAs + pricing up front | Trust-first 120-word template; single "Reply YES" CTA (v4.2.0) |
| `NameError: lead` in `_send_email_sync` | `lead` not in scope of that function | Static plain-text body (v4.2.0) |
| No log file persistence between restarts | No file handler configured | `backend/app/logger.py` IST `TimedRotatingFileHandler` (v4.2.0) |
| JS errors invisible to server | No frontend error sink | `POST /api/logs/frontend` endpoint (v4.2.0) |
| `psycopg.InterfaceError` in standalone scripts on Windows | ProactorEventLoop incompatible with psycopg | `WindowsSelectorEventLoopPolicy` in `send_test_email.py` (v4.2.0) |
| Scraper captures web-designer email instead of business email | Standalone scraper finds first email on page (may be webador/wix support) | Email Mismatch scan — domain-filter + admin review page (v4.3.0) |
| Port 8000 / 5173 collision | Clashes with existing local dev processes | Migrated backend to port 8001 (`run.py`), frontend to 5174 (`vite.config.js`), proxy updated (v5.1.0) |
| Email 1 aesthetic / trust resistance | Generic outreach emails triggered spam / skepticism | Modern 600px card, `#0d1b2a` header, live portfolio proof strip, soft informational closing (v5.1.0) |
| Converted lead manual follow-up delay | Sending Email 2 required external email client & finding PDF | Integrated Email 2 Compose & Preview Modal in Inbox with auto-attached PDF audit report (v5.1.0) |
| Campaign leads out-of-sync with audits | Interrupted runs left `lead.status` desynced from `audit.status` | `reset_leads_to_fresh.py` synchronizes `lead.status='audited'` strictly when `audit.status='done'` (v5.1.0) |
| Hostinger daily volume limits | Sending without rate limits triggered provider bounce/suspension | Enforced 1,000 sends/day limit per account with automated sender rotation (v5.1.0) |

---

## 15. Known Issues & Future Work

| Item | Status |
|---|---|
| Daily send limit enforcement | ✅ **Done v5.1.0** — Hostinger 1,000 sends/day cap per account & rotation |
| IMAP reply detection | ✅ **Done v4.0** — reply_engine.py + Inbox page |
| Reply Preview + Reclassify | ✅ **Done v4.0.1** — modal + PATCH /replies/reclassify/{id} |
| DB pool exhaustion on Audit All | ✅ **Done v4.1.0** — Semaphore(3) rolling queue |
| Valid sites flagged UNREACHABLE | ✅ **Done v4.1.0** — 4-variant URL + SPA detection (site_checker v5) |
| Premature audit-complete modal | ✅ **Done v4.1.0** — `batch_running` guard |
| Near-zero cold email conversion | ✅ **Done v4.2.0 / v5.1.0** — modern card, proof strip, curiosity-gap subject, single CTA |
| No file-based logging | ✅ **Done v4.2.0** — `logger.py` IST rotating log, 3-day retention |
| Scraper email mismatch (wrong domain) | ✅ **Done v4.3.0** — Email Mismatch Detection & Review System |
| Email 2 proposal modal + PDF attach | ✅ **Done v5.1.0** — Inbox.jsx proposal preview/editor + auto PDF attachment |
| Direct test email dispatch | ✅ **Done v5.1.0** — `POST /api/campaigns/send-test` + `send_test_email.py` |
| Database reset & audit synchronization | ✅ **Done v5.1.0** — `reset_leads_to_fresh.py` |
| Email scan bulk accept | No bulk accept UI yet — planned if volume warrants |
| Multi-inbox reply support | `reply_engine.py` only checks first SMTP account — future work |
| Campaign scheduling | `scheduled_at` column exists, UI not implemented |
| Live WebSocket updates | Currently polling (10s Leads, 8s Campaigns) — no WebSocket |
| Multi-user auth | Single admin account only |
| Docker / production deploy | Gunicorn + Nginx needed |
| Automated test suite | No tests — manual only; `send_test_email.py` for outreach validation |

---

## 16. Changelog

| Date | Version | Change |
|---|---|---|
| Mar 2026 | v1.0 | Initial system: FastAPI + React + PostgreSQL |
| Mar 2026 | v1.1 | Fixed blank screen: Tailwind @apply → plain CSS |
| Mar 2026 | v1.2 | Fixed lead deletion: `passive_deletes=True` |
| Mar 2026 | v1.3 | PDF engine: `_safe()` + Deep Impact Analysis |
| Mar 2026 | v1.4 | Bulk delete endpoint + frontend checkboxes |
| Mar 2026 | v1.5 | HTML email engine: two branded templates |
| Mar 2026 | v1.6 | site_checker v1: basic keyword matching |
| Mar 2026 | v1.7 | site_checker v2: 3-tier, 14 false-positive signals removed |
| Mar 2026 | v1.8 | Audit completion polling + AuditDoneModal |
| Mar 2026 | v1.9 | SMTP: per-account JSON config, SMTP_SSL for port 465 |
| Mar 2026 | v1.10 | Two live SMTP accounts configured |
| Mar 2026 | v1.11 | START.bat + STOP.bat launchers |
| Mar 2026 | v2.0 | site_checker v3: soft-404 detection + structural analysis |
| Mar 2026 | v2.1 | Campaign modal: viewport scroll fix, sticky header |
| Mar 2026 | v2.2 | ARCHITECTURE.md: plain-language guide for all readers |
| Mar 2026 | v2.3 | Campaign UI → inline split-panel (no modal, no clipping) |
| Mar 2026 | v2.4 | Test Email floating panel + send-test API endpoint |
| Mar 2026 | v2.5 | Force re-audit: `force=true` flag on audit trigger |
| Apr 2026 | v2.6 | **UTC timezone fix**: `UTCBase` model + `parseUTC()` helper |
| Apr 2026 | v2.6.1 | PDF header alignment: explicit cell-width layouts |
| Apr 2026 | v2.6.2 | API `page_size` limit raised from 200 → 500 |
| Apr 2026 | v2.6.3 | Fixed empty lead lists in Campaign creation (variable shadowing) |
| Apr 2026 | v2.7 | **Outreach delay**: 25–45 min → **20–30 seconds** |
| Apr 2026 | v2.7.1 | **Status fix**: no sleep after last email, done set immediately |
| Apr 2026 | v2.7.2 | **Campaign auto-poll**: UI refreshes every 8s during sends |
| Apr 2026 | v2.7.3 | Live status badge: animated pulse + progress counter |
| Apr 2026 | v2.8 | Campaign reset endpoint + force=true re-launch |
| Apr 2026 | v2.9 | AI business name extraction + Edit Modal in Leads UI |
| Apr 2026 | v3.0 | Campaign engine final: Reply-To header, per-email log, recalculate |
| Apr 2026 | v3.1–3.5 | Status reporting, failed-send resilience, DB repair scripts |
| Apr 2026 | v3.6 | Pagination fix, audit-all coverage, Hostinger 1000/day, 20-30s delays |
| **Apr 12 2026** | **v4.0** | **19-factor audit engine (ReportLab) + Reply Inbox (IMAP classify + auto-actions)** |
| **Apr 12 2026** | **v4.0.1** | **Reply Preview Modal + Reclassify endpoint + number-discrepancy UX fix** |
| **Apr 19 2026** | **v4.1.0** | **Semaphore(3) batch runner, 4-variant URL/SPA guard, Audit All 3-Modes, Skipped list recovery** |
| **Apr 19 2026** | **v4.2.0** | **Outreach overhaul (Email 1 & 2), keyword reply routing, 60-90s delay, DNS/MX validations, IST logging** |
| **Apr 20 2026** | **v4.3.0** | **Email Mismatch Detection & Review System: EmailCorrection model, scan engine, Email Review page** |
| **May 08 2026** | **v4.4.0** | **Premium Audit Dashboard & Email 2 Workflow** |
| **May 09 2026** | **v4.5.0** | **UI/UX Audit Axis (8 new UX factors, 6-axis rings)** |
| **May 09 2026** | **v4.5.1** | **Hotfixes: Email 2 UUID 422 fix, LeadStatus.converted downgrade guard, Email 2 UX injection** |
| **May 19 2026** | **v5.0.0** | **55-Factor Deep Technical & UX Audit Engine, 6 New Audit Modules, Multi-Section ReportLab PDF** |
| **May 19 2026** | **v5.0.1** | **Audit Data Consistency Fix: 3-layer sync between runner, mapper, and DB writer** |
| **May 19 2026** | **v5.0.2** | **Stale Audit Remediation & robots.txt / v5.0 columns consistency maintenance scripts** |
| **Oct 07 2026** | **v5.1.0** | **Email 1 Design Overhaul (600px card, #0d1b2a header, portfolio strip), Email 2 Inbox Modal + Auto PDF Attach, Dev Ports 8001/5174, Hostinger 1000 Send Cap, DB Reset & Audit Sync Utility** |

---

*TEB Solutions / Tattavit — https://tebsolutions.in — System Reference v5.1.0 (October 2026)*


---

## Data vs Logic Consistency Policy (v5.0.2 — 2026-05-19)

### Source of Truth

The `auditor/*.py` functions (e.g. `audit_robots()`, `audit_ssl()`, `audit_sitemap()`) are the
**sole source of truth** for PASS/WARN/FAIL results. The `audits` DB table must always reflect
the latest run of these functions.

### 3-Layer Chain

Every audit check passes through three mandatory layers:

```
Layer 1: auditor/*.py function  →  {status, message, detail} dict
Layer 2: _map_to_db_columns()   →  maps result to column name/value
Layer 3: _results_write()       →  audit.column = db_cols.get('column')
```

If Layer 3 is missing for a column, the DB stays at NULL/stale forever with no error.

### Re-audit Policy

- Re-auditing a lead **always overwrites** stored results for that lead.
- A re-audit clears ALL audit columns and recomputes from scratch.
- Do NOT read DB audit columns as final truth without checking `audit.updated_at`.

### Stale Data Remediation

- Run `backend/maintenance_reaudit_stale.py --apply` to fix `has_robots=False` stale leads.
- For other stale columns: re-audit via the UI or the `/api/audits/{lead_id}/run` endpoint.
- Stuck-running audits (status='running' for >10 min): reset via maintenance SQL in Guardrail #43.

### Known Historical Stale Data (2026-05-19)

- `has_robots=False` for ~1340 leads: caused by pre-fix `audit_robots()` logic. Fixed by
  `maintenance_reaudit_stale.py`.
- v5.0 columns (Groups B-G) all NULL for ~6300 audits: caused by missing assignments in
  `_results_write()`. Fixed by audit_engine.py patch (2026-05-19). New audits will populate them.
