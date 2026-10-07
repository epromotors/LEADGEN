# TEB Solutions LeadGen OS — Development Walkthrough

> **Version:** 5.1.0 — October 7, 2026
> **Purpose:** Summarises every feature built, bug fixed, and decision made across all development sessions. Use this as an onboarding document for any new developer, AI agent, or to resume work after a gap.

---

## What Was Built

**LeadGen OS** is a self-hosted internal SaaS tool for automated B2B lead generation, 55-factor website SEO & UX auditing, intelligent email outreach, automated IMAP reply classification, and follow-up proposal delivery. It:
- Accepts CSV uploads of business contacts with automatic URL root trimming and tagline removal
- Classifies each website (real, parked, dead, placeholder) using a 13-layer pipeline with 4-variant URL exploration & SPA guards
- Runs a 55-factor deep technical, content, performance, and UX audit on real websites across 11 axes
- Generates professional multi-section ReportLab PDF audit reports
- Sends high-converting, trust-first branded HTML cold emails (600px responsive card layout, `#0d1b2a` navy header, live portfolio strip, soft informational closing)
- Enforces Hostinger 1,000 sends/day limit with sender rotation and humanised delays
- Monitors incoming replies via IMAP, automatically classifies intent (converted/stop/bounce/ooo), and provides false-positive reclassification
- Offers an interactive Email 2 follow-up modal in Converted Leads with auto-attached PDF audit reports
- Detects email-domain mismatches to prevent sending to third-party web agencies

---

## System Stack

| Layer | Technology | Port |
|---|---|---|
| Backend | Python 3.14 + FastAPI (async) | 8001 |
| ORM | SQLAlchemy 2.x async (mapped_column style) | — |
| Database | PostgreSQL (`leadgen` DB), driver: `psycopg` v3 | 5432 |
| Frontend | React 18 + Vite + Vanilla CSS + Axios | 5174 |
| Email Send | stdlib `smtplib.SMTP_SSL` port 465 (Hostinger 1000/day cap enforced) | — |
| Email Receive | stdlib `imaplib.IMAP4_SSL` port 993 (imap.hostinger.com) | — |
| Audit Engine | 55-factor auditor/ package (11 axes) | — |
| PDF | ReportLab ≥4.0 (replaced FPDF2) | — |
| Icons | Lucide React | — |

> ⚠️ `asyncpg` does NOT compile on Python 3.14 (binary extension incompatibility). Use `psycopg[asyncio]` instead. The DATABASE_URL uses `postgresql+psycopg://` not `postgresql+asyncpg://`. Backend runs on port **8001** (`backend/run.py`), Frontend runs on port **5174** (`frontend/vite.config.js`).

---

## Session 1 — Foundation & CSV Upload (March 2026)

### What was built
- FastAPI project structure with JWT authentication
- PostgreSQL schema: 4 tables (`leads`, `audits`, `campaigns`, `activity_log`)
- CSV upload with email deduplication
- React frontend: Login, Dashboard, Leads, Audits, Campaigns, Activity pages
- Vite dev proxy: `/api` → `localhost:8000`

### Key bugs fixed
| Bug | Root Cause | Fix |
|---|---|---|
| Tailwind `@apply` blank screen | PostCSS plugin failed silently | Removed Tailwind entirely, rewrote to vanilla CSS |
| Lead deletion FK crash | SQLAlchemy intercepted cascade before DB could | Added `passive_deletes=True` on all Lead relationships |
| PDF Unicode crash | FPDF2 Helvetica = Latin-1 only | Added `_safe(text)` function to strip non-Latin-1 chars before any PDF write |
| Bulk delete orphaned audits | Raw SQL `DELETE` bypasses ORM cascade | Explicit `DELETE FROM audits WHERE lead_id IN (...)` before bulk lead delete |

---

## Session 2 — Email Engine & Site Classifier (March–April 2026)

### What was built
- **12-layer website classifier** (`utils/site_checker.py`): HTTP codes → redirects → content length → parking signals → placeholder signals → soft-404 → structural analysis → REAL
- **Two HTML email templates** in `outreach_engine.py`:
  - **SEO audit email** — for real sites: shows SSL/H1/Mobile/Schema status with ✅/❌, before/after table, three service tiers ($25/$60/$150), blue CTA button
  - **No-site email** — for dead/parked sites: "your domain appears to be [reason]", business loss stats, 11-day build timeline, green CTA button
- **Spintax engine** — `{option1|option2}` random picker with variable substitution
- **PDF engine** — 4-page branded report with audit findings, TEB branding, service tiers

### Key bugs fixed
| Bug | Root Cause | Fix |
|---|---|---|
| Spintax ate `{business_name}` | Regex matched all `{...}` including variables | Changed regex to only match `{word|word}` patterns with the pipe character |
| Subject used `{business_name}` placeholder literally | Variables were substituted before spintax was resolved | Reversed order: resolve spintax first, then inject variables |
| Timezone showed 5.5 hours off | Pydantic serialized naive UTC datetimes without `Z` suffix | Added `UTCBase` model in `schemas.py` + `parseUTC()` in frontend |
| Campaign stuck at "sending" forever | Server restart mid-campaign left DB state as "sending" | Added `POST /{id}/reset` endpoint and `?force=true` on send |

---

## Session 3 — Campaign Send Tuning & Real-Time UI (April 2026)

### What was built
- Email delay reduced from 25–45 min → **4–10 minutes** (humanised, avg 7 min)
- Campaign engine marks `status = "done"` immediately after last email, **no sleep after final send**
- Frontend auto-polls every 15s when any campaign is `"sending"` → live status
- **Test Email panel** — floating card (bottom-right): pick any lead, enter any address, sends `[TEST]` prefixed email using correct template for that lead's site type
- Campaign inline creation drawer (no modal — previous modal had z-index clipping issues)
- Sender rotation: alternates between Hostinger and Gmail accounts per email

---

## Session 4 — Lead Management & AI Names (April 4, 2026)

### What was built

#### AI Business Name Extraction
Scraped leads from tools like Google Maps often have names like:
```
ADM Engineering | Plastic Manufacturing Company in Pune | HDPE Crate | Plastic Crates
```
The `extract_business_name()` function in `audit_engine.py` visits the actual website and extracts the clean name:
1. `og:site_name` meta tag (most accurate)
2. JSON-LD `@type=Organization → name or legalName`
3. `<title>` first segment (splits on `| - – :`)

Stored in `audits.suggested_name` column.

#### Lead Edit Modal
- ✏️ icon on every lead row opens an edit modal
- Fields: business_name, email, phone, website
- After opening, `GET /audits/{lead_id}` fires and loads `suggested_name`
- If it differs from current name → purple AI banner appears:
  - `"✨ AI-suggested name: ADM Engineering"` (source shown)
  - "Use this name" → auto-fills field | "Dismiss" → hides banner
- Yellow inline warning if name contains `|` or is > 60 chars

**Backend:** `PATCH /api/leads/{id}` — partial update, any field optional.

#### Delete All Leads
- Red "Delete All" button in Leads header
- First confirm dialog → then must type `"DELETE"` into text input
- Backend: `DELETE /api/leads/all`
  - Explicitly deletes audits first (raw SQL bypasses ORM cascade)
  - Then deletes all leads

#### Batched Audit All
Previously, "Audit All" launched all audits simultaneously → 400+ concurrent DB connections → pool exhausted → all failed.

**Fix:**
- `POST /audits/trigger-all` now runs a single batched background task
- Processes 10 leads per batch, 2-second delay between batches
- DB pool increased: `pool_size=20, max_overflow=40` in `database.py`
- Result: 411 leads audit cleanly without any pool errors

#### Bug Fixed: Route Shadowing
`GET /api/audits/pdf/{lead_id}` was throwing UUID parse error because `GET /api/audits/{lead_id}` was registered first. FastAPI matched the string "pdf" as a UUID param.

**Fix:** Move `/pdf/{lead_id}` route above `/{lead_id}` in `audits.py`.

---

## Session 5 — Campaign Engine v3 (April 4, 2026)

### What was built

#### Campaign Pause / Resume
Full state-aware campaign runner:

| State | What happens |
|---|---|
| `send` clicked | `pending_lead_ids = []`, counters reset, `run_campaign()` launched |
| Runner starts | Sets `status = "sending"`, iterates `pending_lead_ids or lead_ids` |
| `pause` clicked | Sets `status = "paused"` in DB |
| Runner checks flag | Before EVERY email: `if campaign.status == "paused"` → saves remaining IDs, returns |
| `resume` clicked | Sets `status = "draft"`, launches new `run_campaign()` task |
| Runner on resume | Uses `pending_lead_ids` (not full `lead_ids`) → continues from exact position |

New model fields:
- `Campaign.pending_lead_ids` — JSON list of UUIDs remaining
- `Campaign.paused_at` — datetime
- `Campaign.skipped_count` — total 7-day skips
- `Campaign.failed_count` — total SMTP failures
- `CampaignStatus.paused` — new enum value

#### 7-Day Email Skip
- `Lead.last_emailed_at` tracked after every successful send
- Runner checks before each email:
  ```python
  if lead.last_emailed_at and (now - lead.last_emailed_at).days < 7:
      # log as "skipped", increment campaign.skipped_count, continue
  ```
- Logged to `campaign_email_logs` with `status="skipped"` and reason message

#### Live Countdown Timer
- Before `asyncio.sleep(delay)`, runner sets `campaign.next_email_at = utcnow + timedelta(seconds=delay)`
- Frontend `useCountdown(next_email_at)` hook ticks every 1 second:
  - Shows: `"🕐 Next in 6m 42s"` | `"⏳ Sending now…"` when ≤ 0
- Poll interval: 8 seconds (down from 15s for timer responsiveness)
- Poll survives page navigation (global `setInterval` with `useRef` cleanup)

#### Per-Email Campaign Logs
New table: `campaign_email_logs`

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| campaign_id | UUID FK → campaigns (CASCADE DELETE) | |
| lead_id | UUID FK → leads (SET NULL) | |
| business_name | String | snapshot at send time |
| email | String | snapshot at send time |
| status | String | `"sent"` / `"failed"` / `"skipped"` |
| message | Text | error detail or skip reason |
| created_at | DateTime | |

**Endpoint:** `GET /campaigns/{id}/logs?limit=100`

**UI:** Click ▶ chevron on any campaign row → expands inline log table with color coding (✅ green / ✗ red / ⟳ yellow)

#### Delete Campaign
- `DELETE /campaigns/{id}` — returns 409 if `status == "sending"`
- UI: red trash icon per row, hidden while campaign is sending

#### Progress Bar
Each campaign row shows:
- Animated progress bar (sent/total, green when done, blue when sending)
- Counter: `4/50 · ⟳3 · ✗1` (skipped=yellow, failed=red)

#### Router / API Changes
- `campaigns.py` fully rewritten — static routes (`/send-test`) placed before `/{id}` to prevent shadowing
- New functions in `client.js`: `pauseCampaign`, `resumeCampaign`, `deleteCampaign`, `getCampaignLogs`, `getCampaign`
- Dead duplicate `run_campaign` code body removed from `outreach_engine.py`

---

## Session 6 — Reply Inbox & System Hardening (April 2026 — v4.0 to v4.3.2)

### What was built
- **19-Factor Audit Engine & ReportLab PDF:** Replaced FPDF2 with ReportLab ≥4.0, structured into branded multi-page audit report.
- **Reply Inbox (IMAP) & Auto-Actions:** `reply_engine.py` monitors incoming emails via IMAP, classifies intent (`positive`, `stop`, `bounce`, `ooo`, `other`), and applies automatic database actions:
  - `positive` → sets `status = 'converted'`, records reply snippet
  - `stop` / `bounce` → marks for deletion or suppression
  - `other` / `inquiry` → flags for manual review
- **Converted Leads & Reply Preview Modal:** [Inbox.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Inbox.jsx) displays converted leads, modal views full email text, and allows reclassifying false positives via `PATCH /api/replies/reclassify/{id}` back to `status = 'emailed'`.
- **Batch Audit Semaphore(3) & Micro-Sessions:** Implemented `Semaphore(3)` in `audits.py` to prevent DB pool exhaustion during large "Audit All" jobs, releasing DB connections during remote network crawls.
- **Trust-First Email Outreach:** Replaced heavy brochure emails with lean 120-word plain-text style emails featuring `_pick_hook()` and curiosity-gap subject lines.
- **Email Mismatch Detection System:** `email_review.py` scanner and [EmailReview.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/EmailReview.jsx) UI detects and prompts admin to review cases where scraped email domain differed from website domain.
- **Data Sanitization on CSV Import:** Automatic URL root trimming and business name tagline stripping (`-`, `|`).
- **Campaign Fresh Guard:** Ensures only leads with `audit_status == 'done'` are included in fresh campaigns.

---

## Session 7 — 55-Factor Deep Audit Engine Upgrade (May 2026 — v5.0.0 to v5.0.2)

### What was built
- **Expanded Audit Suite:** Upgraded from 19 factors to **55 comprehensive factors** across 11 distinct performance axes:
  1. *Technical Health* (SSL, sitemap, robots, canonical, favicon, mobile, redirects, mixed content)
  2. *On-Page SEO* (H1, meta title/desc, heading hierarchy, internal links, anchor text, images)
  3. *Indexability* (noindex, URL structure, www vs non-www, soft-404)
  4. *Content Quality* (word count, duplicate meta, keywords in title, readability)
  5. *Local SEO* (NAP consistency, local business schema, Google Maps embed, city in title, business hours)
  6. *Page Performance* (response time TTFB, page size, render blocking, gzip/brotli, WebP, minification)
  7. *Advanced Schema* (FAQ, Product, Breadcrumb, Review, @graph handling)
  8. *UX & Usability* (CTA presence, hero section, font sizing, contrast, cookies, chat widgets)
  9. *Trust & Legal* (Privacy policy, terms, about page)
  10. *Social Integration* (Social profiles, WhatsApp, contact access)
  11. *Image Optimization* (Alt tags, WebP adoption, lazy loading)
- **New Auditor Modules:** Created `indexability.py`, `content.py`, `local_seo.py`, `performance.py`, `schema_advanced.py`.
- **ReportLab PDF Multi-Section Report:** Expanded PDF engine with dedicated tables and recommendation sections for all 11 axes.
- **Frontend 11-Axis Rings:** Updated [Audits.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Audits.jsx) with 11 performance score rings and detailed check status drawers.
- **3-Layer Data Consistency Policy:** Enforced strict pipeline from `auditor/*.py` → `_map_to_db_columns()` → `_results_write()` to guarantee DB matches crawl output without silent NULLs.
- **Stale Audit Remediation:** Added maintenance scripts to fix historic `has_robots` discrepancies and regenerate outdated PDF reports.

---

## Session 8 — Outreach Redesign, Inbox Follow-Up Modal, & Port Migration (Sept–Oct 2026 — v5.1.0)

### What was built
- **Email 1 Visual & Structural Redesign:**
  - Complete overhaul of `build_html_email` in [outreach_engine.py](file:///c:/Users/LENOVO/LEADGEN/backend/app/engines/outreach_engine.py).
  - 600px responsive card layout with deep navy `#0d1b2a` branded header.
  - Official TEB Solutions / Tattavit logo banner + `Website Design • Redesign • Technical Review` badge.
  - 4 core usability pillars card (Mobile layout, Page speed, CTAs & contact, SEO metadata).
  - Live portfolio showcase strip with direct links to real delivered client sites (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`).
  - 2x2 technical review grid with clear status indicators.
  - Low-pressure informational closing note ("These observations are shared purely as helpful context for your team... No need to reply or follow up unless you find this helpful").
  - Spintax curiosity-gap subject lines to maximize inbox placement.
- **Converted Leads Email 2 Compose & Preview Modal:**
  - Added interactive modal in [Inbox.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Inbox.jsx) for following up with leads who replied positively.
  - `GET /api/replies/preview-email2/{lead_id}` renders tailor-made proposal HTML preview.
  - Admin can review, modify subject, and edit HTML body directly in the modal.
  - `POST /api/replies/send-email2/{lead_id}` dispatches email and **automatically attaches the generated PDF audit report** (`reports/{lead_id}.pdf`).
  - Sets `lead.email2_sent_at` timestamp and creates an event in `activity_log`.
- **False-Positive Reply Reclassification:**
  - Enhanced `PATCH /api/replies/reclassify/{lead_id}` with `?target_category=negative|inquiry` query support, safely demoting misclassified leads back to `status = 'emailed'`.
- **Dev Port Migration & Proxy Configuration:**
  - Backend migrated from port `8000` to port **8001** via [backend/run.py](file:///c:/Users/LENOVO/LEADGEN/backend/run.py).
  - Frontend Vite migrated from port `5173` to port **5174** via [frontend/vite.config.js](file:///c:/Users/LENOVO/LEADGEN/frontend/vite.config.js).
  - Vite proxy routes `/api` directly to `http://localhost:8001`.
  - [START.bat](file:///c:/Users/LENOVO/LEADGEN/START.bat) and CORS configuration in `main.py` updated.
- **Direct Test Email Endpoints & Scripts:**
  - Added `POST /api/campaigns/send-test` endpoint in [campaigns.py](file:///c:/Users/LENOVO/LEADGEN/backend/app/routers/campaigns.py) for direct test dispatch of Email 1 without creating a campaign.
  - Created standalone [send_test_email.py](file:///c:/Users/LENOVO/LEADGEN/send_test_email.py) at root for testing against live DB leads.
- **Database Reset & Audit State Synchronization Utility:**
  - Created [backend/reset_leads_to_fresh.py](file:///c:/Users/LENOVO/LEADGEN/backend/reset_leads_to_fresh.py) to reset reply/email counters, sweep stale audits (>30m), synchronize `lead.status = 'audited'` strictly when `audit.status == 'done'` (Guardrail #27), and reset campaigns to draft.
- **Hostinger Daily Send Cap Enforcement:**
  - Strictly enforced 1,000 sends/day limit per account with automated sender rotation in [outreach_engine.py](file:///c:/Users/LENOVO/LEADGEN/backend/app/engines/outreach_engine.py).

---

## Database Schema (v5.1.0 Final)

### `leads`
```
id               UUID PK
business_name    String(255)
email            String(255) UNIQUE
phone            String(50) nullable
website          String(500)
status           Enum: new|auditing|audited|emailed|replied|converted
last_emailed_at  DateTime nullable
replied_at       DateTime nullable     ← added v4.0
reply_snippet    Text nullable         ← added v4.0
reply_type       String(30) nullable   ← added v4.0
email2_sent_at   DateTime nullable     ← added v5.1.0
created_at       DateTime
```

### `audits` (55 Factors across 11 Axes)
```
id                  UUID PK
lead_id             UUID FK→leads CASCADE
ssl_valid           Boolean
has_sitemap         Boolean
has_robots          Boolean
broken_links_count  Integer
missing_h1          Boolean
missing_alt_count   Integer
uses_webp           Boolean
has_json_ld         Boolean
mobile_friendly     Boolean
missing_social      JSON[]
audit_summary       Text
suggested_name      String(500) nullable
pdf_path            String(500)
status              Enum: pending|running|done|failed
error_message       Text
-- v4.5 UX Factors:
has_cta, has_hero, font_size_ok, contrast_ok, has_cookie_banner, has_chat_widget
-- v5.0 Indexability Factors:
has_noindex, url_structure_ok, www_canonical_ok, soft_404_ok
-- v5.0 Content Factors:
word_count, duplicate_meta, keyword_in_title, reading_level_ok
-- v5.0 Local SEO Factors:
has_nap, has_local_schema, has_maps_embed, city_in_title, has_business_hours
-- v5.0 Performance Factors:
response_time_ms, page_size_kb, render_blocking_ok, gzip_enabled, minification_ok
-- v5.0 Advanced Schema Factors:
has_faq_schema, has_product_schema, has_breadcrumb, has_review_schema
created_at          DateTime
updated_at          DateTime
```

### `campaigns`
```
id                UUID PK
name              String(255)
lead_ids          JSON[]
template          Text
subject_template  String(500)
scheduled_at      DateTime nullable
sent_count        Integer default 0
status            Enum: draft|scheduled|sending|paused|done
pending_lead_ids  JSON[] default []
skipped_count     Integer default 0
failed_count      Integer default 0
next_email_at     DateTime nullable
paused_at         DateTime nullable
created_at        DateTime
```

### `email_corrections` (NEW in v4.3.0)
```
id            UUID PK
lead_id       UUID FK→leads CASCADE
old_email     String(255)
new_email     String(255)
domain        String(255)
status        Enum: pending|accepted|dismissed
detected_at   DateTime
resolved_at   DateTime nullable
```

### `campaign_email_logs`
```
id            UUID PK
campaign_id   UUID FK→campaigns CASCADE DELETE
lead_id       UUID FK→leads SET NULL
business_name String(255)
email         String(255)
status        String(30)  "sent"|"failed"|"skipped"
message       Text nullable
created_at    DateTime
```

### `activity_log`
```
id          UUID PK
event_type  String(100)
lead_id     UUID FK→leads SET NULL
message     Text
created_at  DateTime
```

---

## Key Files Changed (All Sessions)

| File | Change Summary |
|---|---|
| `backend/run.py` | [v5.1.0] Dedicated launcher running uvicorn on port 8001 |
| `backend/reset_leads_to_fresh.py` | [v5.1.0] Clean DB state reset & audit sync script |
| `backend/app/engines/outreach_engine.py` | [v5.1.0] Redesigned modern card Email 1, portfolio strip, Email 2 proposal generator, Hostinger 1000/day limit |
| `backend/app/routers/replies.py` | [v5.1.0] Preview proposal HTML, send Email 2 + auto PDF attachment, reclassify false positives |
| `frontend/src/pages/Inbox.jsx` | [v5.1.0] Converted Leads table with Email 2 Preview/Edit/Send modal |
| `frontend/vite.config.js` | [v5.1.0] Port 5174, dev proxy `/api` → `http://localhost:8001` |
| `START.bat` | [v5.1.0] Launch backend on 8001, frontend on 5174, open browser at 5174 |
| `auditor/auditor/auditor/runner.py` | [v5.0.0] Full 55-factor runner across 11 axes |
| `auditor/auditor/auditor/pdf_builder.py` | [v5.0.0] Multi-section ReportLab PDF generator |
| `frontend/src/pages/Audits.jsx` | [v5.0.0] 11-axis ring display + detailed check drawers |
| `backend/app/routers/email_review.py` | [v4.3.0] Domain-matched email mismatch scanner & review API |
| `frontend/src/pages/EmailReview.jsx` | [v4.3.0] Review UI with filter tabs, pending counters, and accept/dismiss actions |
| `backend/app/engines/reply_engine.py` | [v4.0.0] IMAP reply fetcher, intent classifier, and auto-actions |

---

## What's NOT Yet Done (Backlog)

| Priority | Feature | Notes |
|---|---|---|
| 🟡 MED | Multi-inbox reply sync | `reply_engine.py` currently checks the primary Hostinger account |
| 🟡 MED | Campaign future scheduling | `scheduled_at` column exists; timer runner UI not implemented |
| 🟡 MED | Live WebSocket updates | Currently polling (8s Campaigns, 10s Leads) — no WebSocket |
| 🟢 LOW | Multi-user authentication | Single admin credential only |
| 🟢 LOW | Docker deployment | Containerise backend + frontend + Postgres behind Nginx |

---

## How to Resume Work (for AI or Developer)

1. **Read the docs in this order:**
   ```
   AGENT_MASTER.md → controlling instructions, guardrails #1–#48
   CHANGELOG.md    → full history of every bug and fix
   SYSTEM.md       → complete technical reference
   ARCHITECTURE.md → visual flow diagrams
   README.md       → quick-start and API reference
   ```

2. **Environment context:**
   - Python 3.14 — use `psycopg`, NOT `asyncpg`
   - Backend starts with: `python run.py` (Port **8001**)
   - Frontend starts with: `npm run dev` (inside `frontend/`, Port **5174**)
   - Or just run `START.bat` from project root (opens `http://localhost:5174`)

3. **Most dangerous files to edit:**
   - `outreach_engine.py` — card design, email template HTML, spintax, daily limits, and delays are tightly coupled
   - `schemas.py` — every response model must inherit `UTCBase` for correct timezone serialization
   - `audits.py` — route order matters (`/pdf/{id}` and `/stats` must come before `/{id}`)
   - `leads.py` — bulk SQL operations must explicitly delete audits before leads

---

*TEB Solutions / Tattavit — https://tebsolutions.in — October 7, 2026 (v5.1.0)*
