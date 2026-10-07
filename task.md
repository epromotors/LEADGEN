# LeadGen OS Audit Upgrade — Task Tracker
Last updated: 2026-10-07T20:45:00Z
Version target: v5.1.0

### Change Trace Rule — Full Surface Propagation

For every backend audit change, new DB column, new score field, new hook, or new audit function,
you MUST trace where that data should also appear and update all affected surfaces:

1. Backend DB migration / models / schemas
2. audit_engine.py mapping
3. runner.py result collection
4. Frontend audit UI (Audits.jsx, Leads.jsx, Inbox.jsx if relevant)
5. PDF report (pdf_engine.py)
6. Audit summary narrative (build_summary)
7. Email 1 hook selection (_pick_hook in outreachengine.py)
8. Email 2 content / preview / modal if relevant
9. Relevant markdown docs (ARCHITECTURE.md, SYSTEM.md, AGENT_MASTER.md, TASK.md)

Never treat a backend change as complete until every affected frontend, email, PDF,
reporting, and documentation surface has been reviewed and updated if needed.

## GROUP A — Bug Fixes (Do These First)
- [x] A1: Fix sitemap count bug in technical.py — count <url> AND <sitemap> tags
- [x] A2: Fix robots.txt disallow_root logic — add inline comment explaining path!="" guard
- [x] A3: Verify performance.py exists — if missing, create it with speed/webp/minification stubs
- [x] A4: Verify has_lazy_load is populated in runner.py — fix mapping if broken
- [x] A5: Verify has_contact / has_whatsapp mapping — ensure no double-population between ux.py and social.py

## GROUP B — Fix Existing Modules
- [x] B1: onpage.py — add audit_noindex() check for meta robots noindex/nofollow
- [x] B2: onpage.py — add audit_heading_hierarchy() for skipped heading levels
- [x] B3: onpage.py — add audit_internal_links() count internal links, flag orphan pages
- [x] B4: onpage.py — add audit_anchor_text_quality() detect click here / read more anchors
- [x] B5: onpage.py — add audit_image_filenames() flag non-descriptive image filenames
- [x] B6: technical.py — add audit_https_redirect() verify http:// 301 redirects to https://
- [x] B7: technical.py — add audit_redirect_chain() detect chains longer than 2 hops
- [x] B8: technical.py — add audit_mixed_content() scan for http:// assets on https:// pages
- [x] B9: technical.py — add audit_www_canonicalization() www vs non-www duplicate check
- [x] B10: ux.py — expand audit_font_size() to also scan <style> tags, not just inline styles
- [x] B11: ux.py — expand audit_contrast() to also scan <style> tags for color pairs
- [x] B12: ux.py — add audit_phone_number() detect tel: links or phone number patterns
- [x] B13: ux.py — add audit_address_presence() detect physical address in footer/contact

## GROUP C — New Module: indexability.py
- [x] C1: Create auditor/auditor/indexability.py
- [x] C2: audit_noindex() — detect meta robots noindex (moved/shared from B1)
- [x] C3: audit_url_structure() — check URL length, no double slashes, no bare query params
- [x] C4: audit_www_vs_nonwww() — both versions must not 200 independently (duplicate homepage)
- [x] C5: audit_soft_404_content() — deep content-based soft 404 check beyond title

## GROUP D — New Module: content.py
- [x] D1: Create auditor/auditor/content.py
- [x] D2: audit_word_count() — flag pages under 300 words as thin content
- [x] D3: audit_duplicate_meta() — flag if <title> and <meta description> are identical
- [x] D4: audit_keyword_in_title() — flag titles that are purely generic stopwords
- [x] D5: audit_reading_level() — detect if content is machine-generated or near-empty

## GROUP E — New Module: local_seo.py
- [x] E1: Create auditor/auditor/local_seo.py
- [x] E2: audit_nap_consistency() — detect Name, Address, Phone in page text
- [x] E3: audit_local_business_schema() — check LocalBusiness/Organization JSON-LD with address+phone
- [x] E4: audit_google_maps_embed() — detect Google Maps iframe
- [x] E5: audit_city_in_title() — check if city/region keyword appears in title tag
- [x] E6: audit_business_hours() — detect opening hours in schema or visible text

## GROUP F — New Module: performance.py (if missing) / Enhance
- [x] F1: Confirm or create auditor/auditor/performance.py
- [x] F2: audit_response_time() — measure homepage response time in ms
- [x] F3: audit_page_size() — flag HTML over 100KB
- [x] F4: audit_render_blocking() — detect <script> in <head> without defer/async
- [x] F5: audit_gzip_compression() — check Content-Encoding: gzip or br response header
- [x] F6: audit_webp_images() — confirm or fix WebP detection logic
- [x] F7: audit_minification() — confirm or fix CSS/JS minification check

## GROUP G — New Module: schema_advanced.py
- [x] G1: Create auditor/auditor/schema_advanced.py
- [x] G2: audit_faq_schema() — detect FAQPage JSON-LD
- [x] G3: audit_product_schema() — detect Product + Offer + AggregateRating
- [x] G4: audit_breadcrumb_schema() — detect BreadcrumbList
- [x] G5: audit_review_schema() — detect Review or AggregateRating schema
- [x] G6: audit_graph_schema() — properly iterate @graph arrays in JSON-LD (fix existing bug)

## GROUP H — DB + Backend Integration
- [x] H1: Write migration SQL for all new columns (additive only, all NULLABLE)
- [x] H2: Update backend/app/models.py with all new Audit columns
- [x] H3: Update backend/app/schemas.py AuditResponse with new fields
- [x] H4: Update backend/app/engines/audit_engine.py to map all new audit results to DB columns
- [x] H5: Update runner.py (_run_audit_sync) to call all new module functions
- [x] H6: Update score weights — rebalance SCORE_WEIGHTS if new axes added (must sum to 100)
- [x] H7: Update _pick_hook() — outreach_engine uses audit_summary string not individual columns; N/A for this engine architecture

## GROUP I — PDF + UI Updates
- [x] I1: Update pdf_engine.py — added 5 new sections (Indexability, Content, Local SEO, Performance, Schema Advanced) + v5 recommendations
- [x] I2: Update Audits.jsx — added 5 new AUDIT_GROUPS, 37 new check cases in getCheckStatus, 11-axis ring display
- [x] I3: Added 5 new axis rings (Indexability, Content, Local SEO, Performance, Schema+) using checksScore() helper

## GROUP J — Documentation
- [x] J1: Update ARCHITECTURE.md — new factor count, new modules, new DB columns
- [x] J2: Update AGENT_MASTER.md — added Guardrails #34, #35, #36; version bumped to v5.0.0
- [x] J3: Update SYSTEM.md \u2014 version bumped, file tree updated with 5 new modules, DB schema expanded with all 47 new columns
- [x] J4: task.md progress tracking maintained throughout

## GROUP K — Frontend Updates ✅ COMPLETE
- [x] K1: Audits.jsx AUDIT_GROUPS expanded with 5 new v5.0 axis sections
- [x] K2: getCheckStatus() — 37 new v5.0 case branches added
- [x] K3: Performance-by-Axis rings upgraded from 6 → 11 with checksScore() helper
- [x] K4: AXIS_COLORS expanded with 5 new axis colour tokens

## GROUP L — PDF Updates ✅ COMPLETE
- [x] L1: pdf_engine.py — Indexability section added (4 factors)
- [x] L2: pdf_engine.py — Content Quality section added (4 factors)
- [x] L3: pdf_engine.py — Local SEO section added (5 factors)
- [x] L4: pdf_engine.py — Page Performance section added (6 factors, incl. TTFB ms)
- [x] L5: pdf_engine.py — Advanced Schema section added (5 factors)
- [x] L6: _build_recommendations() — 13 new v5.0 recommendation branches added

## ✅ v5.0.0 UPGRADE COMPLETE — All 55 factors live across DB, Backend, Frontend, PDF

## GROUP M — Maintenance & Post-Deploy Tasks (Pending Next Session)
- [ ] M1: Run `python maintenance_reaudit_stale.py --apply` to fix 1,340 stale `has_robots=False` records.
- [ ] M2: Restart the production backend service to ensure the `audit_engine.py` explicit writeback patch takes effect.
- [ ] M3: Perform the 15-day PDF regeneration maintenance (for leads created May 4-19) to purge stale audit reports.

---

## CONTEXT FOR NEXT RUN: Master Prompt

> **MASTER PROMPT — Full Audit Engine Consistency + Security + PDF Regeneration**
> We have discovered a data consistency bug and need a full, safe validation of the audit system end‑to‑end:
> 
> auditor functions → audit_engine / runner → DB columns → API schemas → frontend (dashboard) → PDF → Email 1 → Email 2.
> 
> You must treat this as a systemic validation task, not a one‑off hotfix.
> 
> **0. Context and concrete bug**
> Lead: “Innovature BPO: AI-Driven Outsourcing Partner”
> Website: https://innovatureinc.com
> 
> Current behaviour:
> 
> The SEO Audits dashboard UI (React) shows robots.txt as PASS / OK in the Technical column for this lead.
> 
> The robots.txt for innovatureinc.com is a typical WordPress file: it disallows /wp-admin/, /wp-includes/, some plugin dirs, and search URLs, but does NOT contain Disallow: / at root for User-agent: *.
> 
> However, the PDF report (TEB-SEO-Audit-Innovature_BPO__AI-Driven_Outsourcing_Partner-2.pdf) still shows a CRITICAL error:
> 
> robots.txt is BLOCKING all search engines from crawling the site!
> 
> How to fix: Remove 'Disallow: /' under 'User-agent: *' immediately. This is the #1 reason for disappearing from Google overnight.
> 
> We have already updated auditor/technical.py so that audit_robots() only FAILs when there is literally Disallow: / (or empty Disallow:) under User-agent: * with no Allow: / or Allow: override. The dashboard appears to be using the correct updated data, but the PDF is still rendering the old robots result.
> 
> This reveals:
> 
> Dashboard and DB are mostly correct now.
> 
> Some PDFs (especially older ones) still contain stale or incorrect audit text.
> 
> There may be other audit factors with similar dashboard vs PDF vs email inconsistencies.
> 
> We also want a security pass over these flows so audit data and messages cannot be tampered with or leaked unintentionally.
> 
> **1. Files and components to read first**
> Before writing any code or making changes, open and carefully read:
> 
> Core audit logic
> 
> auditor/auditor/technical.py (SSL, sitemap, robots, canonical, favicon, mobile)
> 
> auditor/auditor/onpage.py
> 
> auditor/auditor/ux.py
> 
> auditor/auditor/performance.py (if present)
> 
> auditor/auditor/schema*.py, indexability.py, content.py, local_seo.py (if present)
> 
> auditor/auditor/runner.py — orchestrator for all checks
> 
> Backend and data layer
> 
> backend/app/engines/audit_engine.py — mapping from auditor result dict → DB
> 
> backend/app/models.py — especially Audit model (audits table) and any related models
> 
> backend/app/schemas.py — Pydantic schemas for audits and related responses
> 
> backend/app/routers/audits.py — audit trigger, get audit, get PDF routes
> 
> PDF and email
> 
> backend/app/engines/pdfbuilder.py or auditor/pdfbuilder.py — PDF generation
> 
> backend/app/engines/outreachengine.py — Email 1 & Email 2 logic, especially _pick_hook and any copy that uses audit fields
> 
> System docs
> 
> SYSTEM.md
> 
> ARCHITECTURE.md
> 
> AGENT_MASTER.md (guardrails, including robots/sitemap rules and new v5 guardrails)
> 
> **2. Fix and verify robots.txt logic (technical.py)**
> Your first job is to ensure that production audit_robots() exactly matches the intended, strict logic:
> 
> Open auditor/auditor/technical.py and inspect audit_robots(base_url, session).
> 
> Confirm the root‑block condition is:
> 
> ```python
> wildcard_rules = blocks.get("*", [])
> 
> disallow_root = any(
>     directive == "disallow" and (path == "/" or path == "")
>     for directive, path in wildcard_rules
> )
> allow_root = any(
>     directive == "allow" and path in ("/", "")
>     for directive, path in wildcard_rules
> )
> 
> if disallow_root and not allow_root:
>     return result_fail(
>         "robots.txt is BLOCKING all search engines from crawling the site!",
>         "Remove 'Disallow: /' under 'User-agent: *' immediately. "
>         "This is the #1 reason for disappearing from Google overnight.",
>     )
> ```
> Confirm that:
> 
> Empty Disallow: (path == "") is treated as allow all, not a block.
> 
> Disallows of subpaths (/wp-admin/, /search/, etc.) do not trigger this branch.
> 
> AI_BOTS (GPTBot, ClaudeBot, Google‑Extended, CCBot, etc.) are ignored for SEO scoring (blocking them is not a FAIL).
> 
> If production code is more aggressive (e.g. path.startswith("/") or any disallow triggers a block), update it to the strict behaviour above and restart the backend so the new logic is live.
> 
> Test manually on https://innovatureinc.com/robots.txt to confirm that:
> 
> The auditor returns PASS or WARN but not this catastrophic FAIL.
> 
> The result matches what you expect from the actual robots.txt.
> 
> **3. Understand PDF data sources**
> You must precisely locate where the PDF gets its content and ensure it reads from the same current data that powers the dashboard.
> 
> In pdfbuilder.py (or equivalent):
> 
> Find how sections like “Technical”, “On‑Page SEO”, “Images”, “UX”, etc. are built:
> 
> Does the PDF builder call auditor functions again?
> 
> Or does it query the audits row and/or auditsummary from the DB?
> 
> Which fields are used for:
> 
> PASS/WARN/FAIL status.
> 
> Headline text.
> 
> Description / “How to fix” text.
> 
> For the robots row in the “Technical” section:
> 
> Identify exactly which field(s) are used (e.g. has_robots, a results["robots"] dict, or a slice of auditsummary).
> 
> Find where the “robots.txt is BLOCKING all search engines…” string is coming from. It might be:
> 
> Hard‑coded in the PDF builder.
> 
> Coming from stale DB text.
> 
> Coming from old logic that hasn’t been updated.
> 
> Compare this with what the dashboard uses:
> 
> How does Audits.jsx decide what to show for robots? Which field(s) from the /api/audits/{lead_id} response does it use?
> 
> Are those fields sourced from the same audits columns that the PDF should use?
> 
> Goal: Dashboard and PDF must read from the same, canonical, current audit data. There should not be a separate, divergent code path for robots or other checks inside the PDF.
> 
> **3.5. Cross‑check audit data → DB → API → frontend → PDF → Email**
> Now perform a systematic mapping and verification for all audit factors, not just robots:
> 
> 3.5.1 Build a factor mapping
> For each audit factor (at least all 27+ core checks, plus any new v5 checks such as indexability, content, local SEO, advanced schema):
> 
> List:
> 
> Auditor function(s): audit_ssl, audit_sitemap, audit_robots, audit_canonical, audit_favicon, audit_mobile, audit_word_count, audit_noindex, audit_nap_consistency, etc.
> 
> DB columns in audits that represent this factor: e.g. sslvalid, hassitemap, hasrobots, has_noindex, word_count, has_thin_content, has_nap, has_local_schema, etc.
> 
> API schema fields that expose them (Pydantic models).
> 
> Frontend consumption:
> 
> Audits.jsx (cards, groups, rings).
> 
> Leads.jsx (badges, noindex warning, etc.).
> 
> Inbox.jsx (Email 2 modal conditions).
> 
> PDF consumption in pdfbuilder.py.
> 
> Email consumption in outreachengine.py:
> 
> _pick_hook() for Email 1.
> 
> Any conditional content or paragraphs in Email 2.
> 
> 3.5.2 Verify write‑back from auditor → DB
> For each factor:
> 
> In audit_engine / runner:
> 
> Confirm the raw audit result dict from the auditor (results["robots"], results["sitemap"], etc.) is mapped into the correct Audit ORM fields.
> 
> Ensure this mapping happens on every audit or re‑audit for that lead, before status is set to done.
> 
> In models.py:
> 
> Confirm each factor has an appropriate column (nullable, additive migration only).
> 
> Confirm new v5 columns exist for indexability, content, local_seo, schema_advanced, etc. and match field names used in code.
> 
> In schemas.py:
> 
> Confirm all relevant columns are exposed in the API responses that the frontend and PDF builder rely on.
> 
> If you find any factor where:
> 
> The auditor function exists but there is no DB column, or
> 
> The DB column exists but is never written, or
> 
> The frontend/PDF/Email reads from a field name that no longer exists,
> 
> then create tasks (e.g. under GROUP H or a new GROUP Z — Data vs Logic consistency) to:
> 
> Add or correct the DB column & migration.
> 
> Wire the mapping in audit_engine / runner.
> 
> Update schemas, frontend, PDF, and outreach so they read the correct field.
> 
> 3.5.3 Verify API → frontend
> Using the live API (or via tests):
> 
> For a sample of leads (including Innovature and a few random others):
> 
> Call GET /api/audits/{lead_id}.
> 
> Verify that all factor fields are present and reflect what the auditor would return if run now.
> 
> Compare this JSON with what you see in Audits.jsx:
> 
> Each card/badge should use fields from the API response, not re‑compute its own logic or use hard‑coded messages.
> 
> Confirm the noindex badge, critical icons, UX rings, etc., all correspond to the same data used by the auditor and DB.
> 
> 3.5.4 Verify frontend → PDF → Email 1 → Email 2
> For PDFs:
> 
> Confirm pdfbuilder.py constructs each section from the same source as the dashboard (i.e., the same fields in the audits data).
> 
> Remove any duplicate audit logic from the PDF builder that could diverge from technical.py or other auditor modules.
> 
> Ensure any narrative text uses structured data (e.g. PASS/WARN/FAIL + standard messages) instead of hard‑coded duplicates.
> 
> For Email 1 (outreachengine.py):
> 
> Check _pick_hook(audit) uses only fields that are guaranteed to exist and be up to date (has_noindex, has_thin_content, has_local_schema, has_phone, has_mixed_content, www_canonical_ok, etc.).
> 
> Ensure hook texts match the latest audit semantics.
> 
> For Email 2 (follow‑up):
> 
> Confirm that any conditional paragraphs based on audit results (e.g., referencing noindex, thin content, local schema, phone presence) are reading from the same fields as the dashboard and PDF.
> 
> Only when all these consumers use the same, fully populated audit data is the system consistent.
> 
> **4. Security & safety checks on audit flows**
> While doing all of the above, perform a security and robustness pass:
> 
> Input safety
> 
> Ensure all URLs used in auditor functions are derived from validated, normalised lead URLs (sitechecker already normalises root domains; confirm this propagation).
> 
> Confirm session.get calls respect TIMEOUT and handle exceptions gracefully (no unhandled exceptions leading to server crashes).
> 
> Data integrity
> 
> Ensure audit results cannot be partially written in a way that misleads the UI or PDF (e.g. status set to done when some fields are missing).
> 
> Consider transactional writebacks: either the full audit is written or the status is failed.
> 
> Access control
> 
> Verify that PDF URLs and audit APIs are only accessible to authenticated users with the correct role (single admin).
> 
> Confirm there is no direct listing of PDFs without auth.
> 
> Email safety
> 
> Confirm Email 1 and Email 2 templates never leak internal debug info.
> 
> Ensure they only use audit data that is safe for external recipients (no stack traces, raw HTML, etc.).
> 
> Logging
> 
> Ensure logs do not store sensitive data from websites being audited beyond what is needed (avoid logging full HTML contents, credentials, etc.).
> 
> If you discover any critical security issue in this process, add tasks and fix them first before bulk regenerating PDFs.
> 
> **5. Regenerate PDFs for all leads created in last 15 days**
> We want to regenerate PDFs for all leads created in the last 15 days from today so that none of their PDFs contain stale or incorrect audit messages.
> 
> Today: 2026‑05‑19.
> 
> Window: 2026‑05‑04 00:00:00 to 2026‑05‑19 23:59:59 (using DB timezone, typically UTC).
> 
> Implementation:
> 
> Write a backend‑only maintenance routine (script, CLI command, or admin task) that:
> 
> Queries the leads table for all leads created_at within this window.
> 
> For each lead:
> 
> Ensure there is an audits row (if none, either skip or trigger a fresh audit depending on design).
> 
> Trigger a re‑audit for this lead OR re‑run the auditor functions and push results into the audits row using the current logic.
> 
> After the audit is done and the audits row is updated, call the PDF builder to generate a new PDF for that lead.
> 
> Update any pdfpath fields on the audits row so the new PDF is used.
> 
> Optionally delete or archive old PDFs.
> 
> Respect system constraints:
> 
> Use the existing semaphore / queue (AUDIT_SEMAPHORE, BATCH_RUNNING) correctly.
> 
> Process in batches to avoid overloading the server.
> 
> Log successes and failures (lead id, website, status).
> 
> After the routine completes:
> 
> Spot‑check at least 10 regenerated PDFs (including Innovature).
> 
> Verify that:
> 
> robots, sitemap, SSL, canonical, UX, etc., match the dashboard.
> 
> There are no obviously stale messages from old logic (e.g., the old robots block warning) unless they are truly applicable.
> 
> **6. Documentation and guardrails**
> After completing all fixes:
> 
> Update SYSTEM.md and ARCHITECTURE.md:
> 
> Describe that all audit outputs are stored in the audits table and used consistently by the dashboard, PDFs, and emails.
> 
> Document the process and recommended steps when audit logic changes (re‑audit + optional PDF regeneration for affected leads).
> 
> Update AGENT_MASTER.md with a new guardrail:
> 
> ```text
> | 41 | **PDF vs Dashboard Consistency** — Whenever audit logic changes (technical.py, onpage.py, etc.), verify that: (a) the audits table is updated via re-audit, (b) the dashboard cards match the new results, and (c) PDFs and email templates are regenerated or updated so they never show stale error messages. Never treat a backend logic change as complete if PDFs or emails still show old findings. |
> ```
> Add a brief note about the 15‑day PDF regeneration maintenance you ran (date, scope).
> 
> **7. Completion criteria**
> You are done when all of the following are true:
> 
> For Innovature BPO:
> 
> Dashboard robots status and description match the latest audit_robots logic.
> 
> A newly generated PDF for this lead shows the same robots result as the dashboard (no incorrect “blocking all search engines” message).
> 
> For a random sample of recent leads (last 15 days):
> 
> Dashboard, API JSON, and PDFs all show consistent results for key factors (robots, sitemap, SSL, canonical, UX, images, etc.).
> 
> Email 1 hooks and Email 2 conditional content align with those same fields.
> 
> There is no factor where the auditor, DB, dashboard, PDF, and email are out of sync.
> 
> A maintenance mechanism exists to regenerate PDFs for a given date range without manual hacking.
> 
> Documentation and guardrails are updated so future logic changes preserve this consistency and security.
> 
> Follow these instructions step by step, treating every inconsistency you find as a bug to be fixed before marking this task complete.

---

## GROUP N — v5.1.0 System, Outreach Redesign & Port Migration (Completed October 2026)
- [x] N1: Email 1 Redesign & Visual Modernization — 600px responsive card layout, `#0d1b2a` navy header, TEB/Tattavit logo banner, `Website Design • Redesign • Technical Review` pill, 4 core usability pillars, live portfolio showcase strip (`Hexaprime.me`, `Channelnexus.me`, `Sketchlife.ae`), 2x2 review grid, low-friction informational closing, and curiosity-gap spintax subjects in [outreach_engine.py](file:///c:/Users/LENOVO/LEADGEN/backend/app/engines/outreach_engine.py).
- [x] N2: Converted Leads Follow-Up Modal — Interactive Email 2 Compose & Preview modal in [Inbox.jsx](file:///c:/Users/LENOVO/LEADGEN/frontend/src/pages/Inbox.jsx) with HTML/subject preview (`GET /api/replies/preview-email2/{id}`), live editing, and one-click dispatch (`POST /api/replies/send-email2/{id}`).
- [x] N3: Automated PDF Audit Attachment — Auto-attach generated ReportLab audit report (`reports/{lead_id}.pdf`) when sending Email 2 to converted leads, setting `email2_sent_at` and recording activity log.
- [x] N4: False-Positive Reply Reclassification — Implemented `PATCH /api/replies/reclassify/{id}` to allow reclassifying mistaken positive replies to negative/inquiry, clearing converted state and resetting `lead.status = 'emailed'`.
- [x] N5: Dev Port Migration & Proxy Configuration — Backend moved to port `8001` via [backend/run.py](file:///c:/Users/LENOVO/LEADGEN/backend/run.py), Frontend moved to port `5174` via [frontend/vite.config.js](file:///c:/Users/LENOVO/LEADGEN/frontend/vite.config.js), Vite dev proxy updated (`/api` -> `http://localhost:8001`), [START.bat](file:///c:/Users/LENOVO/LEADGEN/START.bat) launcher and CORS settings synchronized.
- [x] N6: Direct Test Email Endpoint & Standalone Tool — Implemented `POST /api/campaigns/send-test` for one-off Email 1 dispatches and root [send_test_email.py](file:///c:/Users/LENOVO/LEADGEN/send_test_email.py) for testing against live DB records.
- [x] N7: Hostinger Send Cap & Multi-Account Rotation — Enforced 1,000 sends/day limit per account with automated sender rotation in [outreach_engine.py](file:///c:/Users/LENOVO/LEADGEN/backend/app/engines/outreach_engine.py) to protect domain deliverability.
- [x] N8: Database Reset & Audit Synchronization Utility — Built [backend/reset_leads_to_fresh.py](file:///c:/Users/LENOVO/LEADGEN/backend/reset_leads_to_fresh.py) to purge reply/email tracking, clear stale running audits (>30m), synchronize `lead.status = 'audited'` strictly when `audit.status = 'done'`, and reset campaigns to draft.
- [x] N9: Comprehensive Documentation Synchronization — Updated [AGENT_MASTER.md](file:///c:/Users/LENOVO/LEADGEN/AGENT_MASTER.md), [ARCHITECTURE.md](file:///c:/Users/LENOVO/LEADGEN/ARCHITECTURE.md), [CHANGELOG.md](file:///c:/Users/LENOVO/LEADGEN/CHANGELOG.md), [README.md](file:///c:/Users/LENOVO/LEADGEN/README.md), [SYSTEM.md](file:///c:/Users/LENOVO/LEADGEN/SYSTEM.md), [task.md](file:///c:/Users/LENOVO/LEADGEN/task.md), [AI_PROMPT.md](file:///c:/Users/LENOVO/LEADGEN/AI_PROMPT.md), and [WALKTHROUGH.md](file:///c:/Users/LENOVO/LEADGEN/WALKTHROUGH.md).
