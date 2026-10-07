> **Latest version note:** LeadGen OS is now v5.1.0 (October 2026). Backend runs on port 8001 (`backend/run.py`), Frontend runs on port 5174 (`frontend/vite.config.js`). Outreach Email 1 has been completely redesigned with a modern 600px card, `#0d1b2a` navy header, live portfolio strip, and soft closing. The Converted Leads Inbox features an interactive Email 2 proposal compose & preview modal with auto-attached PDF audit reports. Hostinger 1,000 sends/day limit is strictly enforced in code.

# AI Agent Onboarding Prompt for LeadGen OS

> **Copy-paste the section below into a new chat to get any AI agent fully up to speed.**

> [!IMPORTANT]
> **Before reading this file, load `AGENT_MASTER.md` first.**
> `AGENT_MASTER.md` is the controlling instruction for skill usage, memory management, guardrails, and doc read order.
> This file (`AI_PROMPT.md`) provides the technical onboarding detail that `AGENT_MASTER.md` refers to.

---

## 🚀 THE PROMPT — Copy Everything Below This Line

---

You are working on **TEB Solutions LeadGen OS v5.1.0** — an internal SaaS platform for automated lead generation, 55-factor technical & UX SEO auditing, trust-first branded email outreach, automated IMAP reply classification, and proposal follow-ups. The codebase is located at `c:\Users\LENOVO\LEADGEN`.

### Step 1 — Read These Files (IN THIS ORDER)

Before doing ANYTHING, read these documentation files to understand the full system:

```
1. c:\Users\LENOVO\LEADGEN\AGENT_MASTER.md   ← Operational instructions & mandatory guardrails #1–#48
2. c:\Users\LENOVO\LEADGEN\CHANGELOG.md      ← Full development history, every bug & fix
3. c:\Users\LENOVO\LEADGEN\SYSTEM.md         ← Deep technical reference (architecture, schemas, APIs)
4. c:\Users\LENOVO\LEADGEN\ARCHITECTURE.md   ← Visual flow diagrams (plain-language)
5. c:\Users\LENOVO\LEADGEN\README.md         ← Quick-start guide & project structure
```

### Step 2 — Understand the Stack

| Layer | Tech | Port |
|---|---|---|
| Backend | Python 3.14 + FastAPI (async) + SQLAlchemy 2.x + PostgreSQL | 8001 |
| Frontend | React 18 + Vite + Vanilla CSS + Axios | 5174 |
| Database | PostgreSQL (database: `leadgen`) | 5432 |
| Email (send) | smtplib SMTP_SSL port 465 — Hostinger 1000/day cap enforced | — |
| Email (receive) | imaplib IMAP4_SSL port 993 — imap.hostinger.com | — |
| Audit Engine | 55-factor auditor/ package (11 axes, ReportLab PDF) | — |
| PDF | ReportLab ≥4.0 multi-section audit generator | — |

### Step 3 — Key Files to Know

**v5.1.0 Architecture & Workflow additions:**
- `backend/run.py` — Dedicated backend startup script running uvicorn on port 8001.
- `backend/reset_leads_to_fresh.py` — Database cleanup & audit synchronization utility (enforces Guardrail #27).
- `backend/app/engines/outreach_engine.py` — **v5.1.0 REDESIGNED** — Modern 600px email card, `#0d1b2a` navy header, TEB/Tattavit logo banner, 4 usability pillars, live portfolio proof strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 review grid, low-friction closing, Hostinger 1000 sends/day enforcement.
- `backend/app/routers/replies.py` — Converted leads management + `GET /api/replies/preview-email2/{id}` + `POST /api/replies/send-email2/{id}` (auto PDF attachment) + `PATCH /api/replies/reclassify/{id}`.
- `backend/app/routers/campaigns.py` — Direct test email endpoint `POST /api/campaigns/send-test` + Campaign CRUD & execution.
- `frontend/src/pages/Inbox.jsx` — **v5.1.0** Interactive Email 2 Compose & Preview Modal with live HTML editing and one-click dispatch with auto-attached PDF.
- `frontend/vite.config.js` — Vite server configured to port 5174; proxy routes `/api` to `http://localhost:8001`.
- `START.bat` — One-click launcher booting backend (8001), frontend (5174), and opening `http://localhost:5174`.

**Auditor package (55 factors across 11 axes):**
- `auditor/auditor/auditor/runner.py` — Orchestrates all 55+ technical & UX checks.
- `auditor/auditor/auditor/pdf_builder.py` — ReportLab multi-section PDF generator with 6-to-11 score breakdown.

### Step 4 — Critical Gotchas (Read Before Editing!)

1. **Python 3.14** — asyncpg does NOT work. Must use `psycopg` driver.
2. **No Tailwind @apply** — `@apply` caused blank screen. All CSS is vanilla.
3. **passive_deletes=True** — Required on Lead model relationships. Without it, deleting leads crashes.
4. **UTCBase** — ALL response models MUST inherit UTCBase or timestamps show 5.5h off for IST users.
5. **ReportLab PDF** — PDF engine is now ReportLab ≥4.0. FPDF2 backed up as `pdf_engine_old.py`.
6. **Bulk delete** — Must explicitly DELETE audits before DELETE leads (ORM cascade doesn't fire on bulk SQL).
7. **Port 465 = SMTP_SSL** — Do NOT use STARTTLS on port 465 (causes silent hang).
8. **page_size max = 500** — Frontend requests 500 leads for campaign dropdowns.
9. **Campaign delay** — Skip sleep after last email. Status must be set to "done" immediately.
10. **reply_engine IMAP** — Uses first SMTP_SENDERS account's credentials for imap.hostinger.com:993.
11. **Auditor triple-nesting** — `audit_engine.py` manually injects `sys.path` to find `auditor/auditor/auditor`.
12. **LeadStatus.converted** — New enum value added in v4.0 migration. Do not remove.
13. **Pyrefly** — `pyrightconfig.json` in root excludes root-level utility scripts (gen_preview.py etc.).
14. **gen_preview.py** — Run from `LEADGEN/` root, not from `backend/`. It uses `os.chdir('backend')` internally.
15. **Reclassify ≠ delete** — `PATCH /replies/reclassify/{id}` sets `status=emailed`, `reply_type=other`. Lead stays in DB.
16. **Stat card vs sync count** — Stat card `"Converted Leads"` = DB count of `status=converted`. Sync `"Newly Converted"` = emails matched THIS session. They will differ.
17. **Semaphore(3) — NEVER bypass** — `_AUDIT_SEMAPHORE` in `audits.py` limits concurrent crawls to 3. Adding more parallelism WILL exhaust the DB pool (20 base + 40 overflow).
18. **`_BATCH_RUNNING` flag** — Global in `audits.py`. `trigger-all` returns 409 if True. Do NOT add code that bypasses this guard.
19. **Micro-session pattern** — `audit_engine.py` opens DB sessions only for DB ops, closes them before network I/O. Do NOT revert to holding a single session for the full audit lifecycle.
20. **site_checker v5 — 4 URL variants** — `_url_variants(url)` builds 4 forms per domain. All are tested before UNREACHABLE. Do NOT short-circuit this chain.
21. **SPA guard precedes structural check** — Layer 11 (`_has_js_framework()`) must always run before Layer 12 (structural analysis). Swapping order causes React sites to be mis-classified as DEMO.
23. **`_pick_hook(audit)`** — selects the single highest-priority failing audit finding as the email opener. Runs inside `build_html_email()`. Do NOT remove.
24. **Email #1 is trust-only** — no pricing, no service list. Pricing is reserved for Email #2 after lead says YES.
25. **`send_test_email.py`** — run from `backend/` dir as `python send_test_email.py email@example.com`. Uses `WindowsSelectorEventLoopPolicy` for psycopg compat on Windows.
26. **`logs/leadgen.log`** — rotates at IST midnight; 3-day retention; UTF-8 encoding. Created by `backend/app/logger.py`. Do NOT add file handlers anywhere else.
27. **`POST /api/logs/frontend`** — unauthenticated endpoint for batched JS errors. Add no auth to this route (errors happen before login).
28. **`email_corrections` table** — auto-created by SQLAlchemy on startup. Do NOT manually create it or run a migration script.
29. **Email Review scan** — domain-matched only: only flags emails from the EXACT same domain as the lead's website. Never flags gmail/yahoo/outlook/hotmail.
30. **Accept correction** — resets `lead.status` to `new` and clears `last_emailed_at`. This is intentional: lead re-enters the full audit+email pipeline with the corrected address.
31. **Data Sanitization (v4.3.1)** — Website URLs are auto-trimmed to root domains and business names are stripped of taglines (at - or |### Step 5 — How to Start the App

Additional v4.3.2 & v5.1.0 gotchas:
32. **Campaign Fresh lead guard** - Fresh campaign leads MUST have `audit_status == done` / `audits.status = done`. Do not treat `lead.status = audited` alone as campaign-ready.
33. **Campaign creation validation** - `POST /api/campaigns/` rejects selected leads whose audit is missing, failed, pending, or running.
34. **DB performance maintenance** - `pg_trgm` and hot-path indexes exist for lead search/status, audits, campaign logs, activity, replies, and email review. Preserve them when changing schema.
35. **Dev Port Migration (v5.1.0)** - Backend runs on port **8001** (`python run.py`), Frontend runs on port **5174** (`npm run dev`). Dev proxy routes `/api` -> `http://localhost:8001`. Never hardcode port 8000 or 5173.
36. **Email 1 Design Integrity (v5.1.0)** - Must maintain 600px card, `#0d1b2a` header, logo banner, service pill, 4 usability pillars, live portfolio showcase strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 review grid, and low-friction closing.
37. **Email 2 Proposal Modal (v5.1.0)** - Follow-up outreach is dispatched from [Inbox.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Inbox.jsx) Converted Leads table with auto-attached PDF audit report (`reports/{lead_id}.pdf`).
38. **Hostinger Daily Send Cap (v5.1.0)** - 1,000 sends/day limit enforced per account in `outreach_engine.py` with multi-account rotation.
39. **Database Reset & Sync Utility (v5.1.0)** - Run `backend/reset_leads_to_fresh.py` to reset outreach counters, clear stale audits (>30m), and strictly sync `lead.status = 'audited'` only if `audit.status == 'done'`.

```powershell
# Option A: One click
LEADGEN\START.bat

# Option B: Manual
# Terminal 1 — Backend (Port 8001)
cd c:\Users\LENOVO\LEADGEN\backend
python run.py
# (or: python -m uvicorn app.main:app --reload --port 8001)

# Terminal 2 — Frontend (Port 5174)
cd c:\Users\LENOVO\LEADGEN\frontend
npm run dev
```

Login at **http://localhost:5174** — credentials in `backend/.env`.

### Step 6 — Use These Skills for Quality

When making changes, use these installed skills:

- **`systematic-debugging`** — Before proposing any fix, use structured debugging approach
- **`debugger`** — For errors, test failures, and unexpected behavior
- **`code-reviewer`** — Review changes before committing
- **`lint-and-validate`** — Run validation after EVERY code change
- **`react-patterns`** — For any React/frontend changes
- **`api-patterns`** — For API endpoint design
- **`database`** — For any database/schema changes
- **`fastapi-router-py`** — For FastAPI-specific patterns
- **`python-pro`** — For Python best practices
- **`frontend-design`** — For UI/UX improvements
- **`design-spells`** — For micro-interactions and visual polish
- **`powershell-windows`** — For Windows-specific command patterns
- **`testing-qa`** — For writing tests
- **`performance-profiling`** — For optimization work
- **`security-auditor`** — For security review
- **`documentation`** — When updating docs

### Step 7 — Current Status & Priorities (v5.1.0)

**Working features:**
- ✅ CSV upload + deduplication + auto-cleaning
- ✅ 13-layer site classification v5 (REAL/PARKED/DEMO/NOT_FOUND/UNREACHABLE)
- ✅ 55-factor SEO & UX audit engine across 11 axes with ReportLab branded PDF
- ✅ Redesigned modern card Email 1 (600px card, `#0d1b2a` header, portfolio strip, 4 pillars, soft closing)
- ✅ Curiosity-gap spintax subjects + RFC 2369 List-Unsubscribe compliance
- ✅ Converted Leads Follow-Up Modal: live HTML proposal preview & edit + auto-attached PDF audit
- ✅ False-positive reply reclassification (`PATCH /api/replies/reclassify/{id}`)
- ✅ Direct test email endpoint (`POST /api/campaigns/send-test`) + standalone script (`send_test_email.py`)
- ✅ Hostinger 1,000 sends/day cap per account enforcement and rotation
- ✅ Database reset & audit synchronization utility (`reset_leads_to_fresh.py`)
- ✅ Dev port migration: Backend on 8001 (`run.py`), Frontend on 5174 (`vite.config.js`)
- ✅ Semaphore(3) batch audit runner + micro-session DB pattern + `_BATCH_RUNNING` guard
- ✅ Email Mismatch Detection Scan & Review Page with pending badges
- ✅ Data sanitization on CSV import (clean URLs + strip business taglines)

**Known issues / Next priorities:**
- 🟡 Multi-inbox reply support (`reply_engine.py` currently checks first SMTP account)
- 🟡 Campaign scheduling UI not implemented (column exists in DB)
- 🟡 Multi-user auth not implemented (single admin only)
- 🟡 Live WebSocket updates (currently 8s/10s polling)
- 🟡 Docker/production deployment containerization

### Step 8 — When Debugging

Always check these common failure points:
1. **Backend not running?** → Check if port 8001 is responding (`http://localhost:8001/api/activity/metrics`)
2. **Frontend blank or 404 on API?** → Check Vite port is 5174 and proxy targets `http://localhost:8001`
3. **Empty lead lists?** → Check page_size parameter (must be ≤ 500)
4. **Timezone wrong?** → Check if response model inherits UTCBase
5. **Email not sending?** → Check SMTP_SENDERS in .env, check port 465 vs 587, check 1000/day limit
6. **Campaign stuck?** → Use POST /api/campaigns/{id}/reset or ?force=true
7. **Inbox sync failing?** → Check IMAP credentials match first SMTP_SENDERS entry; verify imap.hostinger.com:993 is reachable
8. **Audit skipped?** → Check if lead already has audit (use force=true); also confirm site_checker v5 can reach the domain
9. **Frontend blank?** → Check for @apply in CSS (must not exist)
10. **Auditor import error?** → audit_engine.py does sys.path injection; run from backend/ dir
11. **Reclassify 422 error?** → Ensure `status = emailed` exists in `LeadStatus` enum
12. **Audit All returns 409?** → A batch is already running (`_BATCH_RUNNING = True`). Wait for it to finish or restart backend.
13. **ECONNRESET on Audit All?** → DB pool was exhausted. Confirm `Semaphore(3)` is in place in `audits.py` and micro-session pattern is in `audit_engine.py`.
14. **Badge shows `audit_error` with underscores?** → Change `.replace('_', ' ')` to `.replaceAll('_', ' ')` in `Leads.jsx`.

### Step 9 — Database Schema Additions (v4.0 + v4.3.0 + v5.0)

If setting up against an older schema, ensure the following columns are present:
```sql
-- v4.0 additions to leads table:
ALTER TABLE leads ADD COLUMN replied_at TIMESTAMP;
ALTER TABLE leads ADD COLUMN reply_snippet TEXT;
ALTER TABLE leads ADD COLUMN reply_type VARCHAR(30);
-- Adds 'converted' to leadstatus enum
ALTER TYPE leadstatus ADD VALUE IF NOT EXISTS 'converted';
```

The `email_corrections` table (v4.3.0) is auto-created by SQLAlchemy on backend startup:
```sql
-- Verify it exists:
SELECT * FROM email_corrections LIMIT 1;
-- Columns: id, lead_id, old_email, new_email, domain, status, detected_at, resolved_at
```

---

## END OF PROMPT

---

## 💡 Usage Tips

### For a general continuation session:
Copy the full prompt above and paste it as your first message.

### For a specific bug fix:
Copy the prompt above, then add:
```
Now debug this issue: [describe the bug]
Use the `systematic-debugging` and `debugger` skills.
```

### For a feature addition:
Copy the prompt above, then add:
```
Now implement: [describe the feature]
Read the relevant source files first, then use the `code-reviewer` skill before finalising.
```

### For email template redesign:
Copy the prompt above, then add:
```
The email templates in `backend/app/engines/outreach_engine.py` (build_html_email and
build_no_site_email functions) need a professional redesign. The current design is too
simple. Read the current templates, then redesign them with modern, premium HTML email
design. Use the `frontend-design` and `design-spells` skills for visual excellence.
Test by sending via the Test Email feature.
```

### For production deployment:
Copy the prompt above, then add:
```
Set up Docker deployment for this app. Use the `docker-expert` skill.
Backend: Gunicorn + Uvicorn workers behind Nginx.
Frontend: Build static files, serve via Nginx.
Database: PostgreSQL in a separate container.
```

### For testing the Reply Inbox:
```
Send a test email to info@tebsolutions.in with subject "YES I'm interested"
Then open the Inbox page and click "Sync Inbox Now" — the lead should appear as Converted.
```
