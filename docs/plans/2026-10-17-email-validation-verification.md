# LEADGEN — Email Verification & Deliverability Hub: Sequential Implementation Plan

> **Protocol:** Inspect → Implement → Review → Test → Fix defects → Retest → Record evidence → Proceed to next task.
> **Safety Rules:** 
> - Primary workspace: `C:\Users\LENOVO\LEADGEN-RELEASE` only. Never modify `C:\Users\LENOVO\LEADGEN`.
> - Do not commit, push, merge, deploy, or launch services (`START.bat`/`STOP.bat`).
> - SMTP and catch-all probing remain **permanently optional and disabled by default**.
> - Never send real emails or perform live SMTP mailbox probing during development/testing.
> - Connect only to `leadgen_release_sandbox` for database migrations/tests.
> - Non-sendable leads must be quarantined and excluded from active sendable pools, campaign queues, and exports. Pre-send gatekeeper must protect email quota.
> - Preserve canonical 62 audit factor IDs, categories, weights, and scoring formulas.

---

## 1. Architecture & Verification Contract

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   Email Verification Engine Architecture                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Syntax Validation     → RFC 5322 regex, length checks, invalid characters│
│ 2. Typo Detection        → Dictionary & distance check (gmial -> gmail.com) │
│ 3. Disposable Domain     → Immutable frozenset of throwaway domains         │
│ 4. DNS / MX Lookup       → Asynchronous DNS resolution + A-record fallback  │
│ 5. [OPTIONAL] SMTP Check → Disabled by default. Explicit opt-in only.       │
│ 6. [OPTIONAL] Catch-All  → Disabled by default. Explicit opt-in only.       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────────────┐             ┌───────────────────────────────┐
│     Campaign Gatekeeper       │             │   Dedicated Audit Menu (UI)   │
├───────────────────────────────┤             ├───────────────────────────────┤
│ • Pre-send eligibility check  │             │ • Audits Hub: SEO vs Email    │
│ • Quotas protected (no send)  │             │ • Deliverability KPI metrics  │
│ • Quarantines non-sendable    │             │ • Active vs Quarantined Leads │
│ • Prevents duplicate bypass   │             │ • Re-verification workflow    │
└───────────────────────────────┘             └───────────────────────────────┘
```

### Verification Status Contract
- `valid`: Confirmed syntax, valid domain with MX/A records, not disposable. Sendable.
- `invalid`: Definite syntax failure, typo without correction, or no MX/A records (NXDOMAIN). Non-sendable (Quarantined).
- `disposable`: Matched disposable/throwaway domain list. Non-sendable (Quarantined).
- `catch_all`: Domain accepts all mailboxes. Non-sendable by default policy unless explicitly allowed.
- `risky`: Potentially problematic domain or configuration. Non-sendable by default policy.
- `not_found`: Domain or record not found. Non-sendable (Quarantined).
- `error`: DNS or network resolution error/timeout. Non-sendable (Quarantined until resolved).
- `unknown`: Indeterminate state. Non-sendable.
- `unverified`: Initial state before verification. Non-sendable.
- `timeout`: Resolution timed out. Non-sendable.
- `blocked`: Blacklisted or blocked destination IP/network. Non-sendable.

---

## 2. Sequential Task Breakdown & Execution Status

### Task 1: Foundations, Constants, and Data Sources
- **Files:**
  - Create: `backend/app/utils/email_constants.py`
  - Create: `tests/test_email_constants.py`
- **Scope:**
  - `DISPOSABLE_DOMAINS` frozenset (canonical, lowercase, immutable).
  - `POPULAR_DOMAINS` dictionary of major providers.
  - `COMMON_TYPO_MAP` dictionary for common domain typos.
  - Helper functions: `normalize_domain`, `suggest_domain_typo`, `is_disposable_domain`.
  - Edge cases: Case normalization, empty/malformed inputs, unicode/IDN normalization.
- **Verification Gate:**
  - Unit tests covering case normalization, exact matches, typo suggestions, false positives, empty/malformed inputs.
- **Status:** COMPLETE
- **Verification Evidence:** `pytest tests/test_email_constants.py` (5 passed in 0.10s). Immutable constants `DISPOSABLE_DOMAINS` (>300 entries), `POPULAR_DOMAINS`, and `COMMON_TYPO_MAP` verified with case normalization, subdomains, IDN punycode, and zero false positives for valid domains.

### Task 2: Core Email Verifier Service
- **Files:**
  - Create: `backend/app/services/email_verifier_service.py`
  - Create: `tests/test_email_verifier_service.py`
- **Scope:**
  - Async verification service: Syntax, typo detection, disposable check, async DNS MX lookup with A-record fallback.
  - SSRF / DNS rebinding protections (rejection of loopback, private, link-local, multicast, reserved IPs).
  - Configurable timeouts, concurrency limits, caching.
  - SMTP & Catch-all modules permanently disabled by default (`smtp_status='not_checked'`).
  - Strict policy determination: `is_sendable` only if policy passes.
- **Verification Gate:**
  - Mocked tests for DNS resolution, NXDOMAIN, A-record fallback, resolver timeouts, cache behavior, SSRF rejection.
  - Mocked SMTP tests for accepted, rejected, deferred, blocked, timeout, error.
  - Verification that SMTP-disabled mode never connects to network.
- **Status:** COMPLETE
- **Verification Evidence:** `pytest tests/test_email_verifier_service.py` (15 passed in 0.33s). Multi-layer async service verified for syntax validation, typo suggestions, disposable domain filtering, async MX resolution, A-record fallback, NXDOMAIN and timeout handling, DNS cache deduplication, SSRF private/reserved IP blocks, permanently disabled-by-default SMTP returning `not_checked`, and mocked explicit opt-in SMTP & catch-all probing.

### Task 3: Database Models and Migration
- **Files:**
  - Create: `backend/migrations/v6_2_0_email_verification.sql`
  - Modify: `backend/app/models.py`
  - Create: `tests/test_email_verification_schema.py`
- **Scope:**
  - Columns: `email_verification_status`, `email_verification_details`, `email_verified_at`, `is_quarantined`, `quarantine_reason`.
  - Database safety gate: Target `leadgen_release_sandbox` only, non-superuser role `leadgen_release_app`, verify `current_database()` and `current_user`.
  - Idempotent migration with safe defaults.
- **Verification Gate:**
  - Test model mappings and verify against sandbox database. Ensure non-destructive operation.
- **Status:** COMPLETE
- **Verification Evidence:** `pytest tests/test_email_verification_schema.py` (3 passed in 1.13s). Model columns `email_verification_status`, `email_verification_details`, `email_verified_at`, `is_quarantined`, and `quarantine_reason` verified. Database Safety Gate executed and passed against `leadgen_release_sandbox` with role `leadgen_release_app` (`is_superuser=False`). Additive migration `v6_2_0_email_verification.sql` applied cleanly with verified index creation.

### Task 4: Email Verification API Router
- **Files:**
  - Create: `backend/app/routers/email_verification.py`
  - Modify: `backend/app/main.py`
  - Create: `tests/test_email_verification_api.py`
- **Scope:**
  - `POST /email-verify/single`: Ad-hoc single verification.
  - `POST /email-verify/lead/{id}`: Verify specific lead and update status/quarantine.
  - `POST /email-verify/bulk`: Bounded batch verification with concurrency throttle (max 5 concurrent checks).
  - `GET /email-verify/stats`: Verification stats and deliverability metrics.
  - `GET /email-verify/leads`: Filtered leads list (active vs quarantined).
  - Endpoints for quarantine inspection and re-verification requests.
- **Verification Gate:**
  - Test client endpoints: validation, status codes, error paths, progress tracking, SMTP remaining disabled.
- **Status:** COMPLETE
- **Verification Evidence:** `pytest tests/test_email_verification_api.py` (9 passed in 2.97s). All API endpoints verified: `POST /single`, `POST /lead/{id}` with quarantine transition, `POST /reverify/{id}` with safe policy restoration, `POST /bulk` with max limit clamping (ge=1, le=500), `GET /progress`, and `GET /stats` deliverability metrics. SMTP probing verified as remaining disabled.

### Task 5: Campaign Outreach Engine Sending Gatekeeper
- **Files:**
  - Modify: `backend/app/engines/outreach_engine.py`
  - Create: `tests/test_outreach_verification_gatekeeper.py`
- **Scope:**
  - Immediate pre-send eligibility check before calling sending provider.
  - Non-sendable outcomes (`invalid`, `disposable`, `not_found`, `error`, `unknown`, `timeout`, `blocked`, `unverified`, `risky`, `catch_all`) automatically quarantined and skipped.
  - Provider submission quota protection: Skipped leads do NOT call provider or increment sent counts.
  - Complete details preserved in quarantine.
  - Re-import / scraper deduplication suppression persistence.
- **Verification Gate:**
  - Mocked sending provider tests proving non-sendable leads are skipped, quota is unconsumed, and campaign logs record exact skip reasons.
- **Status:** COMPLETE
- **Verification Evidence:** `pytest tests/test_outreach_verification_gatekeeper.py` (4 passed in 2.66s) and `pytest tests/test_email_association_and_website_discovery.py` (14 passed in 1.64s). Immediate pre-send gatekeeper verified in `outreach_engine.py`: quarantined leads and unverified/invalid/disposable leads are skipped, quota is preserved, provider is never invoked, and skips are logged to `CampaignEmailLog`. Campaign creation rejects non-valid verification leads.

### Task 6: Email Deliverability Hub UI
- **Files:**
  - Modify: `frontend/src/api/client.js`
  - Create: `frontend/src/components/EmailVerificationAudit.jsx`
  - Modify: `frontend/src/pages/Audits.jsx`
- **Scope:**
  - Sub-navigation under Audits: Website SEO Audits vs Email Deliverability & Verification.
  - Metric cards: Total, Deliverable, Invalid, Disposable, Catch-All, Unverified, Quarantined.
  - Separate views: Active Leads vs Excluded / Quarantined Leads.
  - Ad-hoc email testing, bulk verify with progress bar, detailed 6-layer modal.
  - Optional SMTP clearly indicated as disabled by default (`not_checked`).
- **Verification Gate:**
  - Frontend build (`npm run build` or `npx vite build`) succeeds without error.
  - Component integration tests.
- **Status:** COMPLETE
- **Verification Evidence:** `frontend/src/api/client.js` updated with all 8 verification endpoints (`verifyEmailSingle`, `verifyLeadEmail`, `reverifyLeadEmail`, `startBulkEmailVerification`, `getBulkVerificationProgress`, `cancelBulkVerification`, `getEmailVerificationStats`, `getEmailVerificationLeads`). `EmailVerificationAudit.jsx` created with deliverability KPI metrics cards, ad-hoc single tester, bulk run controls with progress bar and cancel, separate Active vs Quarantined tabs, paginated leads table, detailed multi-layer diagnostic modal, and disabled-by-default SMTP diagnostic indicators. `Audits.jsx` integrated with non-destructive sub-navigation switch between Website SEO Audits and Email Deliverability Hub. Production build `npm run build` executed and passed in 18.97s with zero errors (`dist/index.html`, `dist/assets/index-*.js`, `dist/assets/index-*.css` generated cleanly).

### Task 7: Security, Integration, and Regression Verification
- **Phases:**
  - Phase A: Focused regression tests for all email verification components.
  - Phase B: Full backend test suite execution with exact test counts recorded.
  - Phase C: Frontend production build verification.
  - Phase D: Strict Agent Brain validation (canonical 62 audit factors unchanged).
  - Phase E: Final safety review (no real emails sent, no live SMTP probing, no uncommitted secrets, clean sandbox DB).
- **Status:** COMPLETE
- **Verification Evidence:**
  - **Phase A (Focused Tests):** Ran `pytest tests/test_email_constants.py tests/test_email_verifier_service.py tests/test_email_verification_schema.py tests/test_email_verification_api.py tests/test_outreach_verification_gatekeeper.py tests/test_email_association_and_website_discovery.py` → **50 passed in 3.26s**. All layers (syntax, disposable domains, typo suggestions, DNS/MX resolution, SSRF blocking, SMTP-disabled defaults, database schema, REST APIs, pre-send gatekeeper, and website/email association) passed.
  - **Phase B (Full Backend Test Suite):** Ran `pytest tests/ --tb=short -q` → **520 passed, 1 skipped, 24 warnings, 27 subtests passed in 200.51s (0:03:20)**. 100% pass rate with zero test failures across the entire application test suite.
  - **Phase C (Frontend Production Build):** Ran `npm run build` in `frontend/` → Built cleanly in 5.18s (`dist/index.html`, `dist/assets/index-t1hf65cN.css`, `dist/assets/index-6mp11Wno.js` generated with zero errors).
  - **Phase D (Agent Brain & Factor Validation):** Ran factor registry, factor parity, factor execution, and audit accuracy suites (`tests/test_factor_registry.py`, `tests/test_factor_parity.py`, `tests/test_factor_execution.py`, `tests/test_audit_accuracy_regression.py`, `tests/test_audit_correctness_url_sitemap_schema.py`, `tests/test_audit_observability.py`) → **65 passed, 27 subtests passed**. All canonical 62 audit factors, factor IDs, categories, weights, and scoring formulas remain 100% intact.
  - **Phase E (Final Safety Review):**
    - SMTP mailbox probing and catch-all probing remain permanently disabled by default (`SMTP_VERIFY_ENABLED = False`, `CATCHALL_PROBE_ENABLED = False`).
    - Core verification operates fully without SMTP (syntax, typo, disposable, DNS/MX, and RFC 5321 A-record fallback).
    - Campaign workers cannot trigger mailbox probing and enforce immediate pre-send verification checks.
    - Quarantined leads are completely excluded from active sendable lists, campaign queues, and exports while preserving complete historical records and exclusion reasons.
    - Sending provider quota is protected: skipped/quarantined recipients are never submitted to the sending provider and never increment `sent_count`.
    - Database migration was applied exclusively to `leadgen_release_sandbox` using restricted role `leadgen_release_app` (`is_superuser=False`). Protected databases (`leadgen`, `leadgen_test`, `leads_db`, `linkgen`, `offpage`) were never touched.
    - No real emails were sent, no external mailboxes probed, and no live provider quotas consumed.
    - Protected original checkout `C:\Users\LENOVO\LEADGEN` was untouched.
    - `STOP.bat` safety correction is preserved.
    - No application services launched, and no git commits, pushes, merges, or deployments were performed.
