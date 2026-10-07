# TEB Solutions — LeadGen OS

> **Internal SaaS** — Lead Generation, Automated SEO Audit & Smart Email Outreach
>
> **Version:** 5.1.0 — October 7, 2026

---

## ⚡ Start Everything — One Click

```
LEADGEN\START.bat   ← Starts backend (port 8001) + frontend (port 5174) + opens browser
LEADGEN\STOP.bat    ← Kills all services
```

---

## What It Does (Plain English)

You paste in a spreadsheet (CSV) of business contacts. The system:
1. Checks every website — is it live? parked? dead?
2. If live → runs a **55-factor deep SEO scan across 11 axes**, extracts the real business name via AI, and generates a multi-section branded ReportLab PDF report
3. If dead/parked → notes it, prepares a different "build you a website" pitch
4. You can edit any lead's details (name, email, phone, website) directly in the UI
5. AI suggests cleaner business names for scraped leads with noisy taglines
6. Sends personalised emails — live sites get the redesigned branded web design proposal, dead sites get a build pitch
7. Waits **60–90 seconds** (random) between emails to look human
8. Supports **Pause / Resume** — safely stop mid-campaign and pick up where you left off
9. Skips leads emailed within 7 days automatically
10. Live countdown timer shows when the next email goes out
11. All email activity logged per campaign — every send, skip, and failure recorded
12. **Reply Inbox** — checks your IMAP inbox, classifies replies, converts hot leads, auto-deletes bounced/STOP addresses
13. **Capacity-aware "Audit All"** — Semaphore(3) rolling queue prevents system overload; blocks duplicate triggers with HTTP 409
14. **Email Mismatch Detection** — scans all leads to find domain-matched emails that differ from the DB; lets you accept or dismiss corrections; accepted corrections reset lead to `new` for fresh outreach
15. **Data Sanitization & Normalization (v4.3.1)** — auto-trims URLs to root domains and strips taglines from business names during CSV import.
16. **Premium Audit Dashboard (v4.4.0)** — Interactive SEO score gauge, 5-category PASS/WARN/FAIL grouping, and Phase 2 database readiness for deep technical checks.
17. **Email 2 Follow-up Workflow (v4.4.0)** — Send direct follow-up emails right from the Converted Leads inbox.
18. **UI/UX Audit Axis (v4.5.0)** — 10 UX checks (CTA, above-fold CTA, hero headline, font, contrast, navigation, cookie banner, live chat, phone number, address), stored in 11 new DB columns, visualised as an 11-axis performance ring in the Audits dashboard, and reported in a dedicated PDF section with actionable fix guidance.
19. **55-Factor / 11-Axis Audit Engine (v5.0.0)** — Five new axes added: **Indexability** (4 checks), **Content Quality** (4 checks), **Local SEO** (5 checks), **Page Performance** (6 checks), **Advanced Schema** (5 checks). 47 new nullable DB columns. PDF report expanded with 5 new sections and 13 new recommendation branches.
20. **Branded Email 1 Design Overhaul (v5.1.0)** — Overhauled outreach email into a 600px responsive card layout featuring official TEB Solutions / Tattavit branding, service pill, domain observations headline, 4 usability pillars, live portfolio proof strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 evaluation grid, low-friction closing note ("Purely helpful context... no need to reply"), curiosity-gap spintax subjects, and Hostinger 1,000 sends/day rotation.
21. **Converted Leads Email 2 Compose & Preview Modal (v5.1.0)** — Full modal interface in `Inbox.jsx` for converted leads featuring live proposal HTML rendering (`GET /api/replies/preview-email2/{id}`), in-place HTML/subject editor, one-click sending with auto-attached PDF audit report (`POST /api/replies/send-email2/{id}`), and false-positive reclassification (`PATCH /api/replies/reclassify/{id}`).
22. **Direct Test Email API & CLI Tools (v5.1.0)** — `POST /api/campaigns/send-test` endpoint to test any lead's template directly against any recipient, backed by `send_test_email.py` CLI utility.
23. **Safe Reset Utility (v5.1.0)** — `backend/reset_leads_to_fresh.py` safely clears email metadata, recovers stale running audits (>30m), synchronizes lead status with audit completion, and resets campaigns to clean draft states.
24. **Port Configuration & Dev Server Migration (v5.1.0)** — FastAPI backend runs on port `8001`, Vite frontend runs on port `5174` (with `/api` dev proxy to `:8001`), and `START.bat` automates end-to-end launching.

---

## System Overview

Latest operational rules (v5.0.0):
- Campaign Fresh leads require `audits.status = done`; `leads.status = audited` alone is not enough.
- The Campaigns UI only selects "All Ready" leads with successful audits, and the backend rejects invalid lead IDs during campaign creation.
- PostgreSQL has hot-path indexes plus `pg_trgm` enabled for faster lead search, campaign logs, audit stats, email review, replies, and activity streams.

```
CSV Upload → Site Check → SEO Audit + AI Name → PDF → Email Campaign
                │                                            │
       ┌────────┴────────┐                         Reply Inbox (IMAP)
       │                  │                              │
  REAL site          Dead/Parked/Demo        ┌──────────┼────────────┐
  55-Factor Audit    Skip audit           YES reply  STOP/Bounce  OOO
  AI Name Extract    → "New website" pitch   │          │            │
  + PDF Report              │            Converted  Deleted     Flagged
       │                    │
  SEO findings email
  7-day skip check
  ⏸ Pause / ▶ Resume support
```

---

## Project Structure

```
LEADGEN/
├── START.bat                ← Run this to start everything (backend :8001 + frontend :5174)
├── STOP.bat                 ← Run this to stop everything
├── SYSTEM.md                ← Deep technical reference
├── README.md                ← This file
├── ARCHITECTURE.md          ← Plain-language + visual architecture guide
├── CHANGELOG.md             ← Full development changelog with bug fixes
├── AI_PROMPT.md             ← Copy-paste prompt to onboard any new AI agent
├── pyrightconfig.json       ← Pyrefly/Pyright linter config (excludes root scripts)
├── sample_leads.csv         ← Example data format
├── leads/                   ← Lead spreadsheets (global_leads.xlsx, global_leads.csv)
│
├── backend/                 ← Python API server (FastAPI :8001)
│   ├── .env                 ← Passwords & settings (already configured)
│   ├── requirements.txt
│   ├── run.py               ← Launcher running Uvicorn on port 8001 with Windows event loop
│   ├── send_test_email.py   ← Standalone test email sender with Windows asyncio fix
│   ├── gen_preview.py       ← Standalone offline email preview script
│   ├── email_preview.html   ← Rendered HTML preview of redesigned Email 1
│   ├── reset_leads_to_fresh.py ← Clean reset utility for leads and campaigns
│   ├── reports/             ← PDF reports saved here
│   └── app/
│       ├── main.py          ← API entry point (CORS for :5174, 7 core routers)
│       ├── models.py        ← Database table definitions (6 tables)
│       ├── schemas.py       ← Response schemas + UTCBase timezone fix
│       ├── routers/
│       │   ├── leads.py     ← Upload, list, edit, delete, bulk-delete, delete-all, clean-urls, clean-names
│       │   ├── audits.py    ← Semaphore batch runner, /stats, PDF
│       │   ├── campaigns.py ← Create, send, pause, resume, reset, delete, logs, /send-test
│       │   ├── activity.py  ← Event stream + dashboard metrics
│       │   └── replies.py   ← Inbox sync, converted leads, stats, preview-email2, send-email2, reclassify
│       ├── engines/
│       │   ├── audit_engine.py    ← Micro-session pattern (v4.1.0)
│       │   ├── pdf_engine.py      ← ReportLab PDF engine (11 axes, 55 factors)
│       │   ├── outreach_engine.py ← [v5.1.0] Branded card templates, portfolio strip, Hostinger 1000/day limit
│       │   └── reply_engine.py    ← IMAP reply fetcher + classifier
│       └── utils/
│           ├── site_checker.py   ← 13-layer classifier v5 (4-variant URL, SPA guard)
│           ├── spintax.py        ← {option1|option2} random picker
│           └── csv_parser.py     ← CSV upload + deduplication + data sanitization
│
├── auditor/                 ← 55-factor SEO audit package (11 axes)
│   └── auditor/
│       └── auditor/
│           ├── __init__.py
│           ├── core.py          ← fetch_page, make_session, result_pass/warn/fail
│           ├── technical.py     ← SSL, sitemap, robots, canonical, favicon, mobile
│           ├── onpage.py        ← H1, meta, heading hierarchy, internal links, anchor text
│           ├── performance.py   ← TTFB, page size, render blocking, Gzip, WebP, minification
│           ├── schema.py        ← JSON-LD, OpenGraph
│           ├── social.py        ← social presence, contact links, WhatsApp
│           ├── ux.py            ← 10 UX checks (CTA, headline, font, contrast, nav, address, phone...)
│           ├── indexability.py  ← noindex, URL structure, www/non-www, soft-404
│           ├── content.py       ← word count, duplicate meta, keyword in title, reading level
│           ├── local_seo.py     ← NAP, LocalBusiness schema, Maps, city, hours
│           ├── schema_advanced.py ← FAQ, Product, Breadcrumb, Review, @graph
│           ├── pdf_builder.py   ← ReportLab multi-section PDF generator
│           └── runner.py        ← Orchestrates all 55 checks → final result
│
└── frontend/                ← React web interface (Vite :5174)
    ├── vite.config.js       ← Port 5174 with dev proxy /api → http://localhost:8001
    └── src/
        ├── pages/
        │   ├── Leads.jsx        ← Lead table + Edit Modal + AI name banner
        │   ├── Campaigns.jsx    ← Campaign list + pause/resume + logs + countdown + send-test
        │   ├── Audits.jsx       ← Audit results + 11-axis score rings + filter tabs + PDF download
        │   ├── Dashboard.jsx    ← KPI metrics cards
        │   ├── EmailReview.jsx  ← Email mismatch review page
        │   ├── ActivityLog.jsx  ← Event stream
        │   └── Inbox.jsx        ← Converted Leads + Email 2 Compose & Preview Modal + Reclassify
        ├── components/
        │   └── Layout.jsx       ← Sidebar with Converted badge + Email Review badge
        └── api/client.js        ← All API calls (30+ functions)
```

---

## Quick Start (Manual)

```sql
-- psql: CREATE DATABASE leadgen;
```

```powershell
# Backend (Port 8001)
cd backend && python run.py
# Alternatively:
cd backend && python -m uvicorn app.main:app --reload --port 8001

# Frontend (Port 5174, in a new terminal)
cd frontend && npm install && npm run dev
```

Login at **http://localhost:5174** — credentials from `backend/.env`

---

## .env Reference

| Variable | What it is |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres:pass@localhost:5432/leadgen` |
| `JWT_SECRET` | Encryption key for login sessions |
| `ADMIN_USERNAME` | Login username |
| `ADMIN_PASSWORD` | Login password |
| `SMTP_SENDERS` | JSON array of email sender accounts (see below) |
| `REPORTS_DIR` | Where to save PDF files |

### SMTP Accounts (JSON array)
```json
[
  {"email":"info@tebsolutions.in","smtp_host":"smtp.hostinger.com",
   "smtp_port":465,"password":"...","daily_limit":1000}
]
```
> Port 465 = direct SSL. IMAP also uses the first account in this array (`imap.hostinger.com:993`).

---

## The Business Loop

| # | Step | Location |
|---|---|---|
| 1 | Upload leads CSV | Leads → drag & drop |
| 2 | Review noisy names | Leads → ⚠️ warning on scraper taglines |
| 3 | Edit lead fields / accept AI name | Leads → ✏️ Edit button |
| 4 | Audit websites | Leads → Audit All (Semaphore(3) rolling queue — no overload) |
| 5 | Review results | SEO Audits page |
| 6 | Download PDFs | SEO Audits → PDF button |
| 7 | Test email first | Campaigns → Test Email panel |
| 8 | Create campaign | Campaigns → New Campaign |
| 9 | Send emails | Campaigns → Send (auto-status + live countdown) |
| 10 | Pause if needed | Campaigns → Pause → Resume later |
| 11 | View email log | Campaigns → click row to expand logs |
| 12 | **Sync Inbox** | **Inbox → Check Replies → Sync Inbox Now** |
| 13 | **View hot leads & send Email 2** | **Inbox → Converted Leads tab → Compose/Preview Modal → Send Email 2** |
| 14 | **Review email mismatches** | **Email Review → Scan Now → Accept / Dismiss** |
| 15 | Monitor all activity | Activity Log |

---

## Smart Email Routing (v5.1.0 Modernized Outreach)

| Website Status | Email Sent | Structure & Focus |
|---|---|---|
| **Working website** | Branded Website Design & Redesign Proposal (`build_html_email`) | 600px card, navy header, TEB logo, service pill, 4 usability pillars, live portfolio strip (Hexaprime, Channelnexus, Sketchlife), 2x2 review grid, soft informational closing |
| **Parked / for sale** | New Website Pitch (`build_no_site_email`) | Context on domain parking status, cost of missing online presence, 11-day development roadmap, "Reply YES" CTA |
| **Coming soon / demo** | Same website build pitch | Identifies demo status, pitches professional custom launch |
| **404 / deleted / unreachable** | Same website build pitch | Identifies offline status, pitches clean domain rebuild |

> **Email #1 = credibility & zero pressure.** No aggressive sales pitch. No pricing table. No attachments.
> Full proposal pricing ($25–$300 USD / ₹1,999–₹29,999 INR) and ReportLab PDF audit reports are delivered in **Email 2** via the Converted Leads Inbox modal after a lead replies.

**Subject line style (curiosity-gap spintax):**
- "a note about {domain}"
- "an idea for {domain}"
- "website observation: {domain}"
- "regarding {domain}"

---

## Reply Inbox — Automatic Classification (v4.0)

When you click **Sync Inbox Now**, the system connects to `imap.hostinger.com:993` and scans INBOX + Spam for unseen replies:

| Reply Type | Detected By | Action |
|---|---|---|
| **Positive** (YES / interested) | Subject & body keywords | Lead status → `converted`, appears in Converted Leads |
| **STOP** (unsubscribe) | Subject & body keywords | Lead **permanently deleted** from database |
| **Hard Bounce** (550, invalid address, no such user) | From address + body patterns | Lead **permanently deleted** from database |
| **Soft Bounce** (Out of Office) | Subject & body keywords | Lead **flagged only** — NOT deleted |
| **Other** | — | Marked as read — no DB action |

---

## Lead Management

| Feature | Description |
|---|---|
| **Edit Modal** | Click ✏️ on any lead — edit name, email, phone, website |
| **AI Name Banner** | Modal auto-loads extracted clean name from audit metadata |
| **Scraped Tagline Warning** | ⚠️ shown on names with `\|` or > 60 chars |
| **AI Name Extraction** | Checks `og:site_name`, JSON-LD Organization, then `<title>` |
| **Delete All** | Red button in header — double-confirm with typing "DELETE" |
| **Delete Selected** | Bulk select checkboxes → Delete Selected |
| **Delete Single** | Trash icon on each row |
| **reply_type column** | Tracks positive / stop / bounce / soft_bounce per lead |

---

## Campaign Features

| Feature | Description |
|---|---|
| **Pause** | Stops after current email finishes; remaining leads saved |
| **Resume** | Restarts from exactly where it left off |
| **Delete Campaign** | Trash icon per row (not allowed while sending) |
| **7-Day Skip** | Leads emailed within the last week are automatically skipped |
| **Live Countdown** | Shows "Next in 6m 42s" — updates every second |
| **Background Persistence** | Polling continues when you navigate to other pages |
| **Per-Email Log** | Click ▶ on any row to see every sent/failed/skipped email |
| **Progress Bar** | Visual bar: `4/50 · ⟳3 skipped · ✗1 failed` |
| **Reset** | Force-reset stuck campaigns to draft |
| **Test Email** | Send any lead's email to your own inbox first |
| **60–90s delays** | Humanised random delays (1–1.5 min) |

---

## Audit Engine — v4.1.0 (19 Factors + Semaphore Runner)

Campaign readiness note (v4.3.2): the Campaigns page receives `audit_status` from the leads API. A lead is Fresh only when it has never been emailed and its audit row is `done`. Failed, running, stale, or missing audits must be re-audited before outreach.

The audit engine checks **55 technical + SEO + UX + Local factors** across **11 axes**. Batch runs use a **Semaphore(3) rolling queue** so the database connection pool never saturates:

| Category | Factors |
|---|---|
| **Technical** | SSL, Sitemap, Robots.txt, Canonical tag, Favicon, Mobile viewport |
| **On-Page** | H1 tag, Meta description, Image alt text, Broken links |
| **Performance Engine** | Page speed estimate, WebP usage, Minification |
| **Structured Data** | JSON-LD schema, Open Graph tags |
| **Social** | Social profile presence (FB/IG/LinkedIn/Twitter/YT) |
| **UI/UX** | CTA button, CTA above fold, Hero headline, Font size, Contrast, Navigation, Cookie notice, Live chat, Phone number, Address |
| **Indexability ← NEW v5.0.0** | No-noindex, Clean URL, www/non-www canonical, No soft-404 |
| **Content Quality ← NEW v5.0.0** | Word count (≥300), Unique meta tags, Keyword in title, Readable content |
| **Local SEO ← NEW v5.0.0** | NAP consistency, LocalBusiness schema, Google Maps embed, City in title, Business hours |
| **Page Performance ← NEW v5.0.0** | TTFB <600ms, Page size, Render-blocking, Gzip, WebP coverage, Minification |
| **Advanced Schema ← NEW v5.0.0** | FAQ schema, Product schema, Breadcrumb schema, Review schema, @graph |

PDF reports include a **UI/UX section** with factor table, recommendations, and deep impact analysis for failing UX checks.

### Site Classifier v5 — 13-Layer Pipeline

Before every audit, the website is classified. **v5 (April 2026)** adds:

| Improvement | Detail |
|---|---|
| **4-Variant URL chain** | Tries `https://www` → `https://` → `http://www` → `http://` + `requests` sync fallback |
| **SPA / JS-framework guard** | React, Vue, Next.js, Angular, Nuxt sites → REAL immediately (no false structural flag) |
| **Structural threshold** | Lowered 8,000 → 2,000 chars (was catching real small-business sites) |
| **Link threshold** | Lowered 5 → 3 links needed to pass structural check |
| **Removed ambiguous signals** | `"under construction"`, `"coming soon"` removed from thin-page checks |

---

## Service Tiers (in emails & PDFs)

| Tier | Price | Deliverable |
|---|---|---|
| Blueprint | $25 | PDF with exact fix instructions |
| Fix & Report | $60 | PDF + we fix all issues |
| Complete Presence | $150 | Everything + social profiles created |

---

## CSV Format

```csv
business_name,email,phone,website
Acme Digital,contact@acmedigital.com,+91-9876543210,https://acmedigital.com
```

---

## API Endpoints (v4.0 — Complete)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{access_token}` |
| POST | `/api/leads/upload` | multipart file upload |
| GET | `/api/leads/` | `?page&page_size(max 500)&status` |
| PATCH | `/api/leads/{id}` | partial update: name, email, phone, website |
| DELETE | `/api/leads/{id}` | cascades to audit |
| DELETE | `/api/leads/all` | delete ALL leads + audits (irreversible) |
| POST | `/api/leads/bulk-delete` | `{ids:[...]}` |
| POST | `/api/leads/clean-urls` | Bulk-trim existing URLs to root domains (v4.3.1) |
| POST | `/api/leads/clean-names` | Bulk-strip taglines from existing names (v4.3.1) |
| POST | `/api/audits/trigger/{id}` | background audit |
| POST | `/api/audits/trigger-all` | Semaphore(3) rolling queue — 409 if batch already running |
| **GET** | **`/api/audits/stats`** | **`{batch_running, total, pending, done, failed}` ← NEW v4.1.0** |
| GET | `/api/audits/{lead_id}` | audit record (includes `suggested_name`) |
| GET | `/api/audits/pdf/{lead_id}` | streams PDF |
| GET | `/api/campaigns/` | list all |
| POST | `/api/campaigns/` | create |
| GET | `/api/campaigns/{id}` | single campaign |
| DELETE | `/api/campaigns/{id}` | delete (not while sending) |
| POST | `/api/campaigns/{id}/send` | `?force=true` re-launch stuck |
| POST | `/api/campaigns/{id}/pause` | pause running campaign |
| POST | `/api/campaigns/{id}/resume` | resume paused campaign |
| POST | `/api/campaigns/{id}/reset` | force-reset to draft |
| GET | `/api/campaigns/{id}/logs` | per-email log `?limit=100` |
| POST | `/api/campaigns/send-test` | `{lead_id, to_email}` |
| GET | `/api/activity/` | `?limit=50` |
| GET | `/api/activity/metrics` | KPI counts |
| **POST** | **`/api/replies/check-now`** | **Sync IMAP inbox (sync, returns stats)** |
| **POST** | **`/api/replies/check`** | **Sync IMAP inbox (background task)** |
| **GET** | **`/api/replies/converted`** | **List converted (positive reply) leads** |
| **GET** | **`/api/replies/all-replies`** | **List all replied leads** |
| **GET** | **`/api/replies/stats`** | **Inbox statistics: converted, soft_bounce, deleted_today** |
| **POST** | **`/api/email-review/scan`** | **Scan all leads for domain-matched email mismatches ← NEW v4.3.0** |
| **GET** | **`/api/email-review/`** | **List corrections (`?status=pending\|accepted\|dismissed`) ← NEW v4.3.0** |
| **GET** | **`/api/email-review/stats`** | **Pending/accepted/dismissed counts ← NEW v4.3.0** |
| **POST** | **`/api/email-review/{id}/accept`** | **Accept correction: update lead email + reset to new ← NEW v4.3.0** |
| **POST** | **`/api/email-review/{id}/dismiss`** | **Dismiss correction (no lead changes) ← NEW v4.3.0** |

---

## Database Tables (v4.0)

Database performance note (v4.3.2):
- `pg_trgm` is enabled for faster `ILIKE` search on lead business names and emails.
- Hot-path indexes exist for lead status/date lists, audit status/site-status checks, campaign logs, campaign status, activity streams, reply filters, and email review filters.
- Recent maintenance reset 123 stale `running` audits to `failed`, reset 5 stale `auditing` leads to `new`, verified 0 orphan rows, and ran `VACUUM (ANALYZE)` on core tables.

| Table | Key Columns |
|---|---|
| `leads` | id, business_name, email, phone, website, status, last_emailed_at, **replied_at, reply_snippet, reply_type**, created_at |
| `audits` | id, lead_id, 19 factor columns + **8 new Phase 2 boolean columns**, audit_summary, suggested_name, pdf_path, status |
| `campaigns` | id, name, lead_ids, template, sent_count, skipped_count, failed_count, pending_lead_ids, next_email_at, paused_at, status |
| `campaign_email_logs` | id, campaign_id, lead_id, business_name, email, status (sent/failed/skipped), message, created_at |
| `activity_log` | id, event_type, lead_id, message, created_at |
| **`email_corrections`** | id, lead_id, old_email, new_email, domain, status (pending/accepted/dismissed), detected_at, resolved_at ← NEW v4.3.0 |

### Lead Status Values
`new` → `auditing` → `audited` → `emailed` → **`converted`** (replied YES)

---

## SMTP / IMAP Configuration (v4.0 — Current)

| Field | Value |
|---|---|
| **Account** | `info@tebsolutions.in` |
| **Provider** | Hostinger Business Email |
| **Daily limit** | **1000 emails/day** |
| **SMTP host** | `smtp.hostinger.com:465` (SSL) |
| **IMAP host** | `imap.hostinger.com:993` (SSL) — **NEW v4.0** |
| **IMAP folders scanned** | `INBOX`, `INBOX.Spam` |
| **Delay between sends** | **60–90 seconds** (randomised, 1–1.5 min) |
| **Log file** | `logs/leadgen.log` — IST-aware, 3-day retention (**NEW v4.2.0**) |

---

## Version History

| Version | Date | Summary |
|---|---|---|
| v1.0 | Mar 2026 | Foundation — FastAPI, PostgreSQL, React frontend, CSV upload |
| v1.1–v1.4 | Mar 2026 | Tailwind blank-screen fix, FK cascade, JWT auth |
| v1.5–v1.11 | Mar 2026 | SMTP engine, HTML emails, PDF generation |
| v2.0 | Apr 2026 | Site checker v3 — parked/demo/unreachable classification |
| v2.1–v2.5 | Apr 2026 | Campaign UI, pause/resume, live countdown, retry |
| v2.6–v2.8 | Apr 2026 | Spintax templates, skipped-lead logic, dedup logs |
| v2.9 | Apr 2026 | AI business name extraction, lead editing in UI |
| v3.0 | Apr 4 2026 | Full campaign engine, recalculate endpoint, Reply-To header |
| v3.1–v3.5 | Apr 4–5 2026 | Status reporting, failed-send resilience, DB repair |
| v3.6 | Apr 6 2026 | Pagination fix, audit-all coverage, Hostinger 1000/day, 20-30s delay |
| **v4.0** | **Apr 12 2026** | **19-factor audit engine (ReportLab), Reply Inbox (IMAP classify + auto-delete)** |
| **v4.1.0** | **Apr 19 2026** | **Semaphore(3) batch runner, site_checker v5 (4-variant URL + SPA guard), micro-session DB, batch modal guard** |
| **v4.2.0** | **Apr 19 2026** | **Trust-first outreach overhaul, `_pick_hook()`, IST logging, `send_test_email.py`, NameError fix** |
| **v4.3.0** | **Apr 20 2026** | **Email Mismatch Detection & Review System, EmailCorrection model, scan engine, Email Review page** |
| **v4.3.1** | **Apr 22 2026** | **Data Sanitization: URL root normalization, business name tagline stripping, maintenance cleanup endpoints** |
| **v4.3.2** | **Apr 24 2026** | **Database optimization, stale audit cleanup, `audit_status` lead responses, and campaign Fresh leads restricted to successful audits** |
| **v4.4.0** | **May 8 2026**  | **Premium Audit Dashboard (interactive gauge, PASS/WARN/FAIL), Email 2 Follow-up workflow, and Phase 2 database mappings** |
| **v4.5.0** | **May 9 2026**  | **UI/UX Audit Axis — 8 UX checks, 9 new DB columns, 6-axis dashboard rings, dedicated PDF section with impact analysis** |
| **v4.5.1** | **May 9 2026**  | **Hotfixes: Email 2 UUID type validation, LeadStatus.converted downgrade prevention, Email 2 UI/UX finding injection** |
| **v5.0.0** | **May 19 2026** | **55-Factor / 11-Axis Audit Engine — 5 new modules (Indexability, Content, Local SEO, Performance, Advanced Schema), 47 new nullable DB columns, 11-ring frontend dashboard, 5 new PDF report sections, 13 new recommendations** |

---

> 📖 **Developers / AI:** See [SYSTEM.md](./SYSTEM.md) for full technical reference
> 🗺️ **Architecture:** See [ARCHITECTURE.md](./ARCHITECTURE.md) for visual flow diagrams
> 📝 **Changelog:** See [CHANGELOG.md](./CHANGELOG.md) for complete development history
> 🤖 **New AI agent?** See [AI_PROMPT.md](./AI_PROMPT.md) — copy-paste prompt for instant onboarding
