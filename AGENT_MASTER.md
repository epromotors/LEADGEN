# AGENT MASTER PROMPT – LeadGen OS

You are the persistent AI operator for TEB Solutions LeadGen OS.

Your job is to:
- auto‑use any installed skill that is clearly useful
- minimise token usage with compact memory
- never break critical safety rules of this codebase

---

## Core identity

Project: TEB Solutions LeadGen OS v5.1.0
Type: Internal SaaS for lead generation, website classification, premium SEO audits (55+ factors across 11 axes: Technical, OnPage, Images, Links, Conversion, UX, Indexability, Content, LocalSEO, Performance, SchemaAdvanced), ReportLab PDF reports, branded Email 1 cold outreach with live portfolio showcase & soft closing, converted leads Inbox with interactive Email 2 compose & preview modal, reply classification, email mismatch detection, data sanitization, database optimization, campaign readiness enforcement, dedicated test email endpoints, and safe lead reset utilities.
Ports: Backend FastAPI on port 8001, Frontend Vite on port 5174.

Canonical docs (do not ignore):
- `AI_PROMPT.md`     → onboarding & quick map of stack and gotchas
- `SYSTEM.md`        → full technical reference & architecture
- `ARCHITECTURE.md`  → flows and dependencies
- `README.md`        → quick start and high‑level overview

If context is missing or uncertain, consult these docs in that order, reading only the smallest necessary parts.

---

## Skill usage policy

Default rule: **If a skill can improve correctness, safety, or quality, you must use it automatically. Do not wait for the user to name the skill.**

### Always-on core skills
| Skill | Always active |
|---|---|
| `systematic-debugging` | any bug, error, unexpected result |
| `code-reviewer` | any code change |
| `lint-and-validate` | after every change |
| `documentation` | after any meaningfully new behaviour |

### Load by domain
| Domain trigger | Skills to load |
|---|---|
| React / frontend pages or components | `react-patterns` |
| API routes or backend endpoints | `api-patterns` + `fastapi-router-py` |
| Schema, models, migrations, queries | `database` |
| Python logic or refactors | `python-pro` |
| UI / UX / visual changes | `frontend-design` + `design-spells` |
| Behaviour change, bug fix, new feature | `testing-qa` |
| Batch jobs, crawling, DB usage, polling | `performance-profiling` |
| Auth, SMTP, IMAP, secrets, user input | `security-auditor` |

### Business / domain skills (auto‑load when relevant)
| Skill | Trigger |
|---|---|
| `cold-email-optimizer` | outreach templates, subject lines, follow-ups, conversion strategy |
| `seo-audit-analyst` | audit logic, findings, explanations, PDFs |
| `website-classifier` | `site_checker.py`, REAL/PARKED/DEMO/NOT_FOUND/UNREACHABLE |
| `reply-inbox-manager` | `reply_engine.py`, replies router, Inbox UI |
| `campaign-runner-guardian` | `outreach_engine.py`, campaigns router, Campaigns UI |
| `agent-memory-manager` | context size, long sessions, task switches |

If multiple skills are relevant, combine them.

---

## Memory & token policy (agent-memory-manager)

Maintain a compact "brain" instead of replaying full history.

### Brain fields
| Field | Purpose |
|---|---|
| `project_core` | short summary of what LeadGen OS is |
| `critical_rules` | never‑break constraints |
| `active_goal` | current task |
| `working_set` | key files / modules in play |
| `recent_decisions` | last important choices and why |
| `open_issues` | known bugs / TODOs related to this task |
| `user_preferences` | any stated preferences from Ashish |
| `next_action` | what you plan to do next |

### Compression rules
- Max ~12 bullets, 1 line each
- Include exact file paths where useful
- Prefer references to docs (e.g. "see SYSTEM.md § gotchas") over copying large text
- Update the brain after any major step, before ending a session, and when switching subsystems
- When unsure or memory feels stale, re-open only the smallest relevant doc section

**Goal: minimise re-reading while staying safe and accurate.**

---

## Critical LeadGen OS guardrails

Never violate these unless docs explicitly say they changed:

| # | Rule |
|---|---|
| 1 | Use `psycopg` for Python 3.14; do NOT switch to `asyncpg` |
| 2 | No Tailwind `@apply` anywhere; CSS is vanilla in `frontend/src/index.css` |
| 3 | Lead relationships require `passive_deletes=True` |
| 4 | Response models that surface timestamps must respect the UTC / UTCBase pattern |
| 5 | Bulk delete: explicitly delete audits BEFORE deleting leads |
| 6 | SMTP on port 465 → use `SMTP_SSL`; no STARTTLS on 465 |
| 7 | `page_size` max 500 relied on by frontend code |
| 8 | `LeadStatus.converted` must stay valid, in sync with DB enum, and NEVER be downgraded by audit re-runs. |
| 9 | Preserve `AUDIT_SEMAPHORE = Semaphore(3)` and `_BATCH_RUNNING` 409 guard |
| 10 | Preserve micro-session DB pattern in `audit_engine.py` (no long-lived sessions during crawl/PDF) |
| 11 | Preserve 4-variant URL chain and SPA guard ordering in `site_checker.py` |
| 12 | Preserve audit completion modal logic tied to `batch_running` status, not just counts |
| 13 | Reply engine must use first `SMTP_SENDERS` account for IMAP auth |
| 14 | Campaign engine: set `done` immediately after last email; sleep only between sends; keep per-email logging, randomized 60-90s delays, and pause/resume intact |
| 14.1 | **Email Outbound Validation** — never remove the multi-layered DNS/MX record validation in `outreach_engine.py` |
| 15 | **Trust-first email** — Email #1 must NEVER include pricing or service lists; those go in Email #2 after lead replies YES |
| 16 | **`_pick_hook(audit)`** — never remove this function; it is the engine of email personalisation |
| 17 | **Subject lines must remain curiosity-gap style** — no "Quick question" or other trained-spam triggers |
| 18 | **Logging ONLY via `backend/app/logger.py`** — do NOT add `logging.basicConfig()` or extra file handlers elsewhere |
| 19 | **`send_test_email.py` requires `WindowsSelectorEventLoopPolicy`** on Windows — never remove that line |
| 20 | **`_send_email_sync` must NOT reference `lead`** — that variable is out of scope; use static fallback text |

| 21 | **2-tier pricing in `get_pricing()`** — Only USD and INR tiers. INR used for Indian leads (`currency_code='INR'`), USD for all others. Never re-add per-country currencies without explicit approval. |
| 22 | **`build_html_email_full()` (Email 2)** — navy #0d1b2a header, max 1 img, plain-text services list (no pricing table), single CTA, under 25KB HTML. Do not reintroduce gradient banners or multi-button CTA sections. |
| 23 | **Reply engine tier tags** — `classify_reply_with_tag()` returns `(classification, tier_tag)`. Tag stored in `ActivityLog.message` and passed to `_mark_converted()`. Do not break this flow. |
| 24 | **Email Review domain-filter guardrail** — `email_review.py` scan must ONLY flag emails from the lead's own website domain. Never flag free providers (gmail, yahoo, outlook, hotmail, live, icloud). Never remove this filter. |
| 25 | **Accept correction → status=new** — accepting an email correction MUST reset `lead.status` to `new` and clear `last_emailed_at`. This re-enters the lead in the full pipeline. Do not change this behaviour. |
| 26 | **Data Sanitization (v4.3.1)** — URLs must be trimmed to root and business names stripped of taglines (at - or |) during CSV import. Preserve maintenance cleanup endpoints in `leads.py`. |

| 27 | **Campaign Fresh lead guard (v4.3.2)** - Fresh campaign leads require `audit_status == done` / `audits.status = done`. Do NOT treat `lead.status = audited` alone as campaign-ready. |
| 28 | **Campaign creation validation (v4.3.2)** - `POST /api/campaigns/` must reject selected leads whose audit is missing, failed, pending, or running. Preserve `LeadResponse.audit_status`. |
| 29 | **DB performance indexes (v4.3.2)** - Preserve `pg_trgm` and hot-path indexes for lead search/status, audits, campaign logs, activity, replies, and email review unless replacing with an explicitly safer migration. |

| 30 | **UX column nullability (v4.5.0)** — All 9 UX columns (`has_cta`, `cta_above_fold`, `has_hero_headline`, `font_size_ok`, `contrast_ok`, `nav_links_count`, `has_cookie_notice`, `has_live_chat`, `ux_score`) are NULLABLE. Never add `NOT NULL` constraints to these columns. Old audit records will have NULL and must still render correctly. |
| 31 | **UX score weight (v4.5.0)** — `SCORE_WEIGHTS["ux"]` must stay at 15. Total weights across all 6 groups must sum to 100. Never change weights without updating ALL group weights to re-balance. |
| 32 | **UX check isolation (v4.5.0)** — All UX analysis logic lives in `auditor/auditor/auditor/ux.py`. Do NOT add UX scraping logic to `audit_engine.py` directly. Engine only calls the module and maps results. |
| 33 | **PDF UX section position (v4.5.0)** — The UI/UX section in `pdf_engine.py` must appear BETWEEN the Technical SEO audit results and the Deep Impact Analysis. Do NOT move it after the checklist. |
| 44 | **Service Ports & Proxy (v5.1.0)** — Backend FastAPI MUST run on port `8001`, Frontend Vite dev server MUST run on port `5174`. Vite dev proxy routes `/api` to `http://localhost:8001`. `START.bat`, `config.py` (`FRONTEND_URL`), and `main.py` CORS must remain configured for `:8001` and `:5174`. |
| 45 | **Email 1 Design Architecture (v5.1.0)** — `build_html_email()` must retain the branded card layout: navy `#0d1b2a` header, logo, `#eff4ff` canvas, service pill, 4 usability pillars, live portfolio proof strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 dashed check grid, low-friction informational closing, and curiosity-gap spintax subjects. Never reintroduce salesy pressure or unsolicited attachments. |
| 46 | **Email 2 Compose & Preview Modal Workflow (v5.1.0)** — Follow-up proposals for converted leads must use `/api/replies/preview-email2/{id}` for preview and `/api/replies/send-email2/{id}` for dispatch. Supports custom HTML and subject overrides. PDF audit report must be attached if available. Reclassifying false-positive replies must use `PATCH /api/replies/reclassify/{id}` to preserve the lead. |
| 47 | **Hostinger Send Cap & Account Rotation (v5.1.0)** — `outreach_engine.py` enforces Hostinger's 1,000 sends/day limit per sender account using `CampaignEmailLog`. Rotates through configured accounts; if all accounts reach capacity, campaign status pauses cleanly. |
| 48 | **Safe System Reset Protocol (v5.1.0)** — To reset leads, use `backend/reset_leads_to_fresh.py`. It clears tracking timestamps (`last_emailed_at`, `replied_at`), sweeps stale audits stuck in `running` (>30m) to `failed`, syncs `lead.status = 'audited'` strictly when `audit.status == 'done'` (and `'new'` otherwise per Guardrail #27), and resets active campaigns to clean drafts. |

If a change risks any guardrail, **call out the risk explicitly and propose a safer design**.

---

## How to work on any task

For every request, follow this sequence:

```
1. Identify task type
   (frontend | backend | DB | audit | campaigns | inbox | outreach | docs | …)

2. Auto-load relevant skills based on type

3. Check + update memory brain

4. Open docs only at minimum required scope
   (AI_PROMPT.md → SYSTEM.md → ARCHITECTURE.md → README.md)

5. State assumptions briefly

6. Implement step-by-step, guardrails intact

7. Lint / test / reason with appropriate skills

8. Update memory brain: what changed, what's next
```

---

## Obedience hierarchy

Treat this file (`AGENT_MASTER.md`) as the **controlling instruction** for:
- which skills to use
- when to consult which docs
- how to manage memory and tokens
- which guardrails must never be broken

When in doubt, follow this file first, then use `SYSTEM.md` and `AI_PROMPT.md` to fill in technical details.

---

*Last updated: 2026-10-07 (v5.1.0 — Email 1 Redesign, Inbox Email 2 Modal, Dev Ports 8001/5174, Reset Utility, Guardrails #44–#48)*

---

## v5.0.0 Audit System Guardrails

### Guardrail #34 — Sitemap Tag Counting
- Always count **both** `<url>` AND `<sitemap>` child tags when parsing XML sitemap files.
- A sitemap index file contains `<sitemap>` child entries pointing to sub-sitemaps, not `<url>` entries.
- Failure to count `<sitemap>` tags causes the audit to report "0 URLs" on valid sitemap index files.
- The correct logic: `count_urls + count_sitemaps = total_entries`

### Guardrail #35 — Robots.txt Disallow Root Logic (UPDATED v5.0.1)
- We ONLY flag robots.txt as CRITICAL ("blocking all search engines") when the robots.txt contains **exactly** `Disallow: /` (path equals the string `"/"`) under `User-agent: *` with no `Allow: /` override.
- `Disallow:` (empty path) means "allow everything" per RFC 9309 — it must NEVER trigger a FAIL.
- `Disallow: /wp-admin/`, `Disallow: /search/`, etc. are specific sub-path blocks — they are NORMAL and must NEVER trigger a FAIL.
- The correct condition in code is:
  ```python
  disallow_root = any(
      directive == "disallow" and path == "/"
      for directive, path in wildcard_rules
  )
  ```
- **Do NOT use** `path.startswith("/")`, `path != ""`, or any looser match. Only a literal `"/"` is catastrophic.
- A standard WordPress robots.txt (blocking /wp-admin/, /wp-login.php, /xmlrpc.php, AI bots, etc.) must always return PASS from `audit_robots()`.

### Guardrail #36 — v5.0 New Module Safety
- Never import from `auditor.indexability`, `auditor.content`, `auditor.local_seo`, `auditor.performance`, or `auditor.schema_advanced` outside of the try/except block in `audit_engine.py`.
- All 5 new modules are optional enhancements — audit must degrade gracefully if they fail to import.
- All new DB columns added in v5.0.0 are NULLABLE — never set `nullable=False` on any v5.0 column.

### Guardrail #37 — v5.0 Indexability Column Nullability
- All 4 Indexability columns (`has_noindex`, `url_structure_ok`, `www_nonwww_ok`, `soft_404_ok`) are NULLABLE.
- `has_noindex` is a BOOLEAN where `True` = noindex IS present (bad). Frontend inverts this with `invert: true`.
- Never add `NOT NULL` constraints to any v5.0 Indexability column.

### Guardrail #38 — v5.0 Content Quality Column Nullability
- `word_count` (INTEGER, nullable) stores raw word count. Frontend checks `>= 300` for PASS.
- `duplicate_meta_ok`, `keyword_in_title_ok`, `reading_level_ok` are all NULLABLE BOOLEAN.
- Never conflate `word_count = 0` with `word_count = NULL`. Zero means the page was reached but empty.

### Guardrail #39 — v5.0 Local SEO Column Nullability
- All 5 Local SEO columns (`has_nap`, `has_local_business_schema`, `has_google_maps`, `city_in_title_ok`, `has_business_hours`) are NULLABLE.
- `has_nap` is CRITICAL priority — a FAIL on this column should surface prominently in PDF recommendations.
- Never auto-generate NAP data; only detect what is actually present on the crawled page.

### Guardrail #40 — v5.0 Performance Column Safety
- `response_time_ms` (INTEGER, nullable) stores actual measured milliseconds. PASS threshold = <600ms.
- `page_size_bytes` (INTEGER, nullable) stores raw byte count. `page_size_ok` (BOOLEAN) is the derived flag.
- `gzip_enabled`, `render_blocking_ok`, `webp_coverage_ok`, `minification_ok` are all NULLABLE BOOLEAN.
- Never confuse the Performance axis (v5.0) with the legacy Performance ENGINE checks (speed/WebP/minification in the original runner). They are separate.

### Guardrail #41 — v5.0 Advanced Schema Column Nullability
- All 5 Advanced Schema columns (`has_faq_schema`, `has_product_schema`, `has_breadcrumb_schema`, `has_review_schema`, `schema_graph_ok`) are NULLABLE.
- Schema detection parses ALL `<script type="application/ld+json">` blocks including @graph arrays.
- Do NOT flag a schema type as missing if the @graph array was not fully iterated. Use Guardrail #34 (sitemap counting) as the model for safe array traversal.

### Guardrail #42 — Robots.txt False-Positive Prevention (CRITICAL)
- Verified bug: the old `disallow_root` condition used `(path == "/" or path == "")` combined with `if path != ""` as a generator filter. This was contradictory and confusing, and in edge cases (multi-block WordPress files) could mis-parse path state and produce false FAILs.
- The authoritative fix (May 2026): `disallow_root = any(directive == "disallow" and path == "/" for directive, path in wildcard_rules)` — no filter clause, no ambiguity.
- Test case: `https://innovatureinc.com/robots.txt` — 3 User-agent: * blocks, Disallow: /wp-admin/ etc., GPTBot/ClaudeBot blocked. Correct result = **PASS** (multiple blocks note).
- Before modifying `audit_robots()` in any future session, re-read this guardrail and run the innovatureinc.com test case first.

### Guardrail #43 — Data vs Logic Consistency (CRITICAL — 2026-05-19)

**Root cause discovered (2026-05-19):**

1. `_results_write()` in `audit_engine.py` was writing Phase 1–3 columns (lines ~882–909)
   but ALL 30 v5.0 columns computed by `_map_to_db_columns()` were NEVER assigned to the
   `audit` model object. Fix: added explicit `audit.xxx = db_cols.get('xxx')` for every v5.0
   column (Technical B, Onpage B, UX B, Indexability C, Content D, Local SEO E, Performance F,
   Schema G).

2. 1340 leads had stale `has_robots=False` from pre-fix audits. The live `audit_robots()` now
   returns PASS for most of these. Fix: `maintenance_reaudit_stale.py` corrects these with a
   targeted UPDATE.

**3-Layer Chain Verification Rule:**
When changing audit logic OR adding DB columns, ALWAYS verify ALL THREE layers:
  1. `auditor/*.py` function returns correct PASS/WARN/FAIL in memory
  2. `_map_to_db_columns()` maps the result to correct DB column name with correct value
  3. `_results_write()` assigns `audit.column_name = db_cols.get('column_name')` for that column

If ANY layer is missing, the DB silently stays stale while UI shows wrong data. No error is thrown.

**Spot-check rule:** After any audit logic change, run a live-vs-DB comparison on 5+ REAL-site
leads using `backend/live_vs_db.py` (or similar) before closing the task.

**Stuck-running audits:** Run this maintenance query if audits get stuck in `running`:
```sql
UPDATE audits SET status='failed', error_message='stuck-reset'
WHERE status='running' AND updated_at < NOW() - INTERVAL '10 minutes';
```

---

## v5.1.0 Operational & Architecture Guardrails

### Guardrail #44 — Service Ports & Proxy Configuration (CRITICAL)
- **FastAPI backend** runs strictly on port `8001` (`backend/run.py` uvicorn call: `port=8001`).
- **React frontend** Vite development server runs on port `5174` (`frontend/vite.config.js`: `server.port = 5174`).
- **Vite Proxy:** All `/api/*` frontend calls are proxied to `http://localhost:8001` (`rewrite: (path) => path.replace(/^\/api/, '')`).
- **CORS Allow Origins:** `backend/app/main.py` MUST include `"http://localhost:5174"` in CORS `allow_origins`.
- **Settings:** `backend/app/config.py` default `FRONTEND_URL` is `"http://localhost:5174"`.
- **Launcher:** `START.bat` starts FastAPI on `:8001` and Vite on `:5174`, then launches `http://localhost:5174` in the browser. Do NOT revert ports back to 8000/5173 without coordinated full-stack configuration.

### Guardrail #45 — Email 1 Design Architecture & Trust Strategy
- `build_html_email(lead, audit)` in `backend/app/engines/outreach_engine.py` generates the initial outreach email for leads with a website.
- **Design Structure:**
  - Responsive card container (width: 600px, 14px rounded corners, `#ffffff` card on `#eef2f7` outer canvas).
  - Navy `#0d1b2a` header featuring the official TEB Solutions / Tattavit logo banner (`LOGO_URL`) with "Web Design & Digital" subtitle.
  - Service pill token: `Website Design • Redesign • Technical Review`.
  - Dynamic observation headline: *"Observations on {domain}'s website structure & experience"*.
  - 4 key usability pillars card: Modern First Impression, Mobile Responsiveness, Direct Contact Pathways, Technical Foundations.
  - **Live Portfolio Proof Strip:** Showcase real projects:
    - `Hexaprime.me` (Branding & Web)
    - `Channelnexus.me` (SaaS Landing)
    - `Sketchlife.ae` (UAE Lifestyle)
    - Credibility note: *"+ many more white-label solutions across UAE, India & the UK."*
  - 2x2 dashed evaluation grid: First impression, Mobile experience, Visitor contact flow, Google basics.
  - **Low-Friction Closing:** *"These observations are shared purely as helpful context for your team's website planning. There is no need to reply or follow up."* (No aggressive sales pitch or immediate pricing in Email 1).
  - Branded navy footer with official contacts (`tebsolutions.in`, `info@tebsolutions.in`).
- **Subject lines:** Keep spintax curiosity-gap format: `{a note about {domain}|an idea for {domain}|website observation: {domain}|regarding {domain}}`.
- Never attach audit reports or PDFs to Email 1 (PDFs remain strictly reserved for Email 2 follow-ups).

### Guardrail #46 — Email 2 Compose & Preview Modal Workflow
- Converted leads (positive replies) are managed via `frontend/src/pages/Inbox.jsx`.
- **Preview:** `GET /api/replies/preview-email2/{lead_id}` renders proposal HTML without sending.
- **Send:** `POST /api/replies/send-email2/{lead_id}` transmits Email 2 with optional `custom_html` and `custom_subject` overrides.
- **Safety checks:**
  - Lead must exist and have `status = LeadStatus.converted`.
  - Generated PDF report (if available in `audit.pdf_path`) must be attached to Email 2.
  - Activity log entry `email2_sent` must record the lead ID, recipient address, and sender account.
- **Demotion guard:** Reclassifying false-positive auto-replies must call `PATCH /api/replies/reclassify/{lead_id}` to reset status to `emailed` and `reply_type = 'other'` without deleting the lead from PostgreSQL.

### Guardrail #47 — Hostinger Send Cap & Multi-Account Rotation
- In `outreach_engine.py`, Hostinger daily send limits (1,000 sends/day per account) are enforced using `CampaignEmailLog` query count.
- Engine dynamically checks sender accounts. If an account has hit 1,000 sends today, it rotates to the next configured SMTP sender.
- If all accounts have reached their daily limit, the campaign status is set to `paused`, remaining pending leads are preserved, and an alert is logged to resume tomorrow.

### Guardrail #48 — Safe System Reset Protocol
- When resetting campaign or lead progress across the database, NEVER run manual uncoordinated SQL queries.
- Use `python backend/reset_leads_to_fresh.py`.
- **Reset Sequence:**
  1. Clears `last_emailed_at`, `replied_at`, `reply_snippet`, and `reply_type` on all leads.
  2. Sweeps stale audits stuck in `running` state (>30 minutes old) to `failed`.
  3. Sets `lead.status = 'audited'` strictly for leads where `audit.status == 'done'` (satisfying Guardrail #27).
  4. Sets `lead.status = 'new'` for all remaining leads without a completed audit.
  5. Resets active and paused campaigns back to `draft` state with zeroed sent/skipped/failed counters.
