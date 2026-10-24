# LEADGEN — Email Association and Website Discovery Plan & Verification Report

> **Protocol:** Inspect → Reproduce → Identify root cause → Implement or correct → Review → Test → Fix defects → Retest → Record evidence → Proceed.
> **Safety Discipline:**
> - Work exclusively in `C:\Users\LENOVO\LEADGEN-RELEASE`. Protected original checkout `C:\Users\LENOVO\LEADGEN` is untouched.
> - No git commits, pushes, merges, deployments, or service executions (`START.bat`/`STOP.bat`).
> - Preserve the current `STOP.bat` safety correction.
> - Never expose credentials, API keys, or contact data.
> - No real email sending or live mailbox probing (SMTP disabled by default).
> - DB changes strictly isolated to `leadgen_release_sandbox` with non-superuser role `leadgen_release_app`.

---

## 1. Problem Statement & Root Cause Analysis

### Incident 1: Bihari Brothers Groups
- **Observed Defect:**
  - Business: `Bihari Brothers Groups`
  - Displayed website: `https://biharibrother...`
  - Displayed email: `hi@tynemade.mx`
  - Displayed source: `http_contact_page [http_page_scrape]`
- **Root Cause:**
  - On the target company's website, an external designer footer credit (`Website designed by Tynemade: hi@tynemade.mx`) was scraped via naive regex/mailto extraction without inspecting the surrounding contextual text or evaluating the domain mismatch (`biharibrothers.com` vs `tynemade.mx`).
  - The pipeline accepted the first scraped email regardless of cross-domain source or agency attribution, silently associating an external vendor address with the lead and exposing it to outreach campaigns.
- **Correction Applied:**
  - Context-aware extraction captures surrounding HTML text context (150 chars).
  - Regex detection detects agency/designer/footer attribution (`designed by`, `developed by`, `maintained by`, `web design:`, `theme by`, `site by`, `agency:`, `crafted by`, `made by`, etc.).
  - Cross-domain heuristic classification classifies such emails as `MISMATCHED_SOURCE` and automatically marks them `is_quarantined=True` (`is_sendable=False`).
  - Genuine domain-matching emails on contact pages (`contact@biharibrothers.com`) are prioritized and marked `MATCHED` (`is_sendable=True`).
  - Parent/affiliate domains with shared business name tokens (e.g. `biharigroup.com`) and free mail providers (`gmail.com`) are classified as `EXTERNAL_DOMAIN_REVIEW` for human evaluation, never silently accepted or discarded.

### Incident 2: ECO-EXPORT
- **Observed Defect:**
  - Business: `ECO-EXPORT`
  - Intended website: `https://ecoexport.in/`
  - Known reference email candidates: `marketing.ecoexport@gmail.com`, `info.ecoexport@gmail.com`
  - Conflicting extracted candidate: `contact@ecoexport.com.vn`
  - Observed source: `serper [api_search_snippet]`
  - Observed website value: `No Website`
- **Root Cause:**
  - Initial place search returned no website property. The pipeline immediately declared the lead as `No Website` without querying candidate websites.
  - An unstructured email regex across search snippets picked up an unrelated international domain (`ecoexport.com.vn` in Vietnam) with a ccTLD conflicting with the Indian business location.
  - Reference Gmail contacts were omitted or lacked formal candidate provenance.
- **Correction Applied:**
  - When initial place search lacks a website, the pipeline does NOT immediately declare `No Website`. It triggers `search_candidate_websites` using Serper organic search.
  - Multi-factor candidate scoring (`score_website_candidate`) scores candidates based on business name token ratios, location ccTLD alignment (`.in` boost for India), and penalizes conflicting international ccTLDs (`.vn` penalty for India).
  - High-confidence candidates (score >= 0.5) are tagged `CANDIDATE_MATCH`. Close competing candidates are tagged `CONFLICTING`. Unreached threshold candidates are tagged `UNVERIFIED_SEARCH`. `NO_WEBSITE` is only finalized when search returns zero candidates.
  - Structured search parsing keeps emails tied to specific result URLs and snippets. Conflicting ccTLD search snippets are classified as `MISMATCHED_SOURCE` (`is_sendable=False`).
  - Known reference Gmail addresses are preserved as `EXTERNAL_DOMAIN_REVIEW` with true provenance (`user_supplied`, `manual_reference`, `places_payload`).

---

## 2. Provenance Schema & Database Safety

### Schema & Model Implementation
- Columns added to `Lead` model in `backend/app/models.py` and `backend/app/schemas.py`:
  - `email_source_url` (VARCHAR 500)
  - `email_source_type` (VARCHAR 50)
  - `email_extraction_method` (VARCHAR 50)
  - `email_domain` (VARCHAR 100)
  - `website_domain` (VARCHAR 100)
  - `email_domain_match` (BOOLEAN)
  - `email_business_association_status` (VARCHAR 50, default `'unverified_association'`)
  - `email_association_reason` (TEXT)
  - `website_association_status` (VARCHAR 50, default `'unverified'`)
  - `website_candidates` (JSONB)
  - `email_candidates` (JSONB)
  - `is_quarantined` (BOOLEAN, default `FALSE`)
  - `quarantine_reason` (TEXT)
  - `email_verification_status` (VARCHAR 50, default `'unverified'`)
  - `email_verification_details` (JSONB)
  - `email_verified_at` (TIMESTAMP)

### Database Safety Gate
- Additive migrations applied exclusively to `leadgen_release_sandbox`:
  - `backend/migrations/v6_2_0_email_verification.sql`
  - `backend/migrations/v6_2_1_email_association_provenance.sql`
- Connected with non-superuser role `leadgen_release_app` (`is_superuser=False`).
- Protected databases (`leadgen`, `leadgen_test`, `leads_db`, etc.) were never touched.

---

## 3. Campaign Gatekeeper & Quarantine Enforcement

### Enforcement Layers
1. **Campaign Creation Gatekeeper (`backend/app/routers/campaigns.py`):**
   - Blocks any lead where `is_quarantined=True`, `email_verification_status != 'valid'`, or `email_business_association_status` is not in `('matched', 'approved')` (fail-closed policy: null, empty, unknown, and unapproved associations are strictly blocked).
   - Prevents unverified, missing association, or mismatched leads from entering `pending_lead_ids`.
   - Safe retry endpoint excludes quarantined, unverified, and non-matched/non-approved leads from resend queues.
2. **Pre-Send Engine Gatekeeper (`backend/app/engines/outreach_engine.py`):**
   - Immediate check before provider invocation: re-verifies `is_quarantined`, association status, verification status, and RFC syntax.
   - If blocked, logs skip to `CampaignEmailLog` with specific reason (e.g. `email_business_association_mismatched_source (non-sendable quarantine)`).
   - Provider quota is protected: `_send_email_sync` is never called, `sent_count` does not increment, and no SMTP connection is opened.
   - SMTP and catch-all mailbox probing remain permanently disabled by default.
3. **Export Filtering (`backend/app/services/lead_discovery_service.py` & `backend/app/routers/leads.py`):**
   - `export_leads_csv` supports `sendable_only=True` parameter to exclude quarantined leads from sendable exports while allowing full audit exports.

---

## 4. Frontend Provenance & Display

1. **`BulkImportDiscovery.jsx`:**
   - Displays email association status badges: `Matched Domain`, `Provider Review`, `Mismatched Source`, `Unverified`.
   - Displays candidate website indicators: `Candidate` for discovered sites, `Conflicting` for ambiguous matches, and distinguishes `Unverified Search` from `No Website`.
   - Shows quarantine warning icons with tooltip explanations.
   - Dual export buttons: `Full CSV` and `Sendable CSV` (with `sendable_only=true`).
2. **`Leads.jsx`:**
   - Defensive null checks for `lead.website` to prevent rendering crashes.
   - Shows candidate website indicators and quarantine badges.
   - Preserves SEO audit triggers, editing modal, and batch controls.
3. **`EmailVerificationAudit.jsx` & `Audits.jsx`:**
   - Sub-navigation switch between Website SEO Audits and Email Deliverability Hub.
   - Deliverability KPI metrics, Active vs Quarantined tabs, bulk verification with cancel, and detailed 6-layer diagnostic modal.

---

## 5. Verification Evidence & Test Summary

### Final Verification Results (Fail-Closed Safety Pass & Full-Suite Verification)

| Suite / Check | Command | Result | Duration |
|---|---|---|---|
| Fail-Closed Association Gate (Regression Suite) | `py -m pytest tests/test_fail_closed_association_gate.py -v` | **23 passed** | 2.99s |
| Focused Association & Discovery | `py -m pytest tests/test_email_association_and_website_discovery.py -v` | **24 passed** | 1.85s |
| Email Constants | `py -m pytest tests/test_email_constants.py -v` | **5 passed** | 0.08s |
| Email Verifier Service | `py -m pytest tests/test_email_verifier_service.py -v` | **15 passed** | 0.31s |
| Database Schema & Migration | `py -m pytest tests/test_email_verification_schema.py -v` | **3 passed** | 0.98s |
| Email Verification REST API | `py -m pytest tests/test_email_verification_api.py -v` | **9 passed** | 2.85s |
| Outreach Gatekeeper Safety | `py -m pytest tests/test_outreach_verification_gatekeeper.py -v` | **4 passed** | 2.50s |
| **All Focused Suites (Combined)** | `py -m pytest tests/test_fail_closed_association_gate.py tests/test_email_*.py tests/test_outreach_*.py` | **84 passed, 59 warnings** | 3.72s |
| **Full Backend Test Suite** | `py -m pytest tests/ --tb=short -q` | **554 passed, 1 skipped, 61 warnings, 27 subtests** | 201.01s (3m 21s) |
| **Canonical 62 Factors & Observability** | `py -m pytest tests/test_factor_registry.py tests/test_audit_observability.py -v` | **23 passed, 1 warning, 27 subtests** | 8.83s |
| **Frontend Production Build** | `npm run build` in `frontend/` | **Built cleanly (built in 5.32s)** | 5.32s |
| **Database Safety Gate** | Direct connection check | **leadgen_release_sandbox, non-superuser role** | Verified |

---

## 6. Fail-Closed Association Gate Review & Enforcement

### Identified Vulnerability & Root Cause
Prior campaign creation and pre-send logic allowed associations in `('matched', None)` to be selected for outreach, or evaluated pre-send blocking using an exclusion list (`in ('unverified_association', 'mismatched_source', ...)`) which evaluated to `False` when `email_business_association_status` was `None`, empty string, or unknown. Additionally, reverification could clear quarantine for an email with an unresolved association if its DNS/SMTP syntax checked out.

### Full-Suite Test Flakiness Resolution (`provider.py`)
During full-suite execution under load, `test_timeout_fixture_isolated_outcome` in `tests/test_phase2_verification.py` intermittently failed with `AssertionError: assert 'FAILED' == 'TIMEOUT'`. Investigation confirmed that `BrowserConfig(nav_timeout_ms=1000)` passed its 1000ms navigation timeout to `playwright.chromium.launch(timeout=cfg.nav_timeout_ms)`. Under system load, Chromium process startup took >1.0s, causing Playwright to raise a launch timeout and return `FAILED` before page navigation began. Decoupled process startup timeout in `launch_kwargs` to `max(30_000, cfg.op_timeout_ms)` while preserving the 1000ms navigation timeout in `page.goto()`. Following this fix, the entire backend suite passed with 0 failures (`554 passed, 1 skipped`).

### Applied Mitigations Across All Pathways
1. **Explicit Positive Allowlist:**
   All campaign creation, pre-send gating, retry/resend queuing, and sendable-only export logic strictly enforces `email_business_association_status in ("matched", "approved")` and `not is_quarantined` and `email_verification_status == "valid"`. Any `None`, empty string, missing field, unknown status, legacy record, or unapproved status is fail-closed blocked.
2. **Pre-Send Engine Gatekeeper (`outreach_engine.py`):**
   Prior to dispatching any email, `process_campaign_recipient_batch` executes a fail-closed pre-send gatekeeper:
   `is_assoc_sendable = (assoc_status in ("matched", "approved")) and (not is_quarantined)`
   If false, the lead is immediately quarantined, logged as skipped in `CampaignEmailLog` with reason `email_business_association_<status> (fail-closed association policy)`, provider submission is aborted, quota is untouched, and `sent_count` is not incremented.
3. **Authenticated & Authorized Approval Endpoint (`POST /leads/{lead_id}/approve-association`):**
   - Strictly requires authentication via `Authorization: Bearer <JWT>` validated against `settings.JWT_SECRET`.
   - Requires authorized role (`admin` or `operator`); unauthorized roles (e.g. `viewer`) receive `403 Forbidden`.
   - Authoritative reviewer identity is established server-side from `current_operator["sub"]`.
   - Spoofed or forged reviewer identities in the request body differing from the authenticated principal are rejected with `403 Forbidden`.
   - Rejects unverified justifications (reason min length 5) and refuses `invalid_format` records (`400 Bad Request`).
   - Audit trail logged in `ActivityLog` without leaking credentials or secrets.
   - Clears quarantine only if `lead.email_verification_status == "valid"`. Unverified emails remain quarantined.
4. **Quarantine & Re-verification Protection (`leads.py` & `email_verification.py`):**
   Lead update endpoint prevents setting `is_quarantined=False` if association status is not `matched` or `approved`. Re-verification and bulk verification pipelines do not unquarantine leads that have unresolved or mismatched associations, even when email syntax and domain MX resolve to `valid`.
5. **Direct Reply Gatekeeper (`replies.py`):**
   `send_email_2` enforces the identical fail-closed check (`not lead.is_quarantined` and `lead.email_business_association_status in ("matched", "approved")`).

### Safety Guarantee Summary
- No email was sent.
- No external SMTP mailbox was probed. SMTP remains permanently disabled by default.
- No application services launched (`START.bat`/`STOP.bat` were not run).
- The `STOP.bat` safety correction (port-specific process termination) is preserved.
- The protected original checkout `C:\Users\LENOVO\LEADGEN` was untouched.
- No commit, push, merge, or deployment occurred.


