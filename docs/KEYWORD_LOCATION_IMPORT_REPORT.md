# Keyword and Location Import Integration Report

**Date:** 2026-10-17 (Session 3 update)
**Workspace:** `C:\Users\LENOVO\LEADGEN-RELEASE`
**Git Branch:** `fix/audit-url-sitemap-correctness`
**Git HEAD:** `6fbc450` (`feat: add account-aware provider key rotation`)

---

## 1. Executive Summary

Support for user-provided keyword and location list files is integrated into the LEADGEN lead-discovery subsystem (`lead_discovery_service.py`, `backend/app/routers/leads.py`, and `frontend/src/components/BulkImportDiscovery.jsx`).

The importer supports the multi-niche pipe-delimited format (`Category | kw1 | kw2 | ...`) and the region-prefixed city format (`REGION:City Name`), as well as standard single-item-per-line formats. It handles UTF-8 BOM, strips whitespace, ignores comments and section headers, removes case-insensitive duplicates while preserving original casing, validates entry lengths, and flags malformed items without exposing source contents or secrets.

---

## 2. Files Modified (All Sessions)

### Repository Code Modified

1. `backend/app/config.py` — `DISCOVERY_MAX_ENTRIES_PER_FILE` increased to 1000; `DISCOVERY_MAX_COMBINATIONS_LIMIT` = 500 confirmed.
2. `backend/app/services/lead_discovery_service.py` — `parse_txt_upload_content()` with `file_type` parameter; `DISCOVERY_REGION_MAP`; `calculate_combinations()` + `create_job()` + `run_discovery_job()` with `batch_offset` pagination. Batching arithmetic corrected (Session 2): `step_size = budget` not `max_allowed`.
3. `backend/app/routers/leads.py` — `batch_offset` and `file_type` wiring.
4. `frontend/src/components/BulkImportDiscovery.jsx` — localStorage persistence, merge logic, batch pagination controls, zero provider calls on import/preview.
5. `tests/test_lead_discovery_integration.py` — 23 tests covering all integration scenarios including boundary batching and real-list-size arithmetic.

---

## 3. Source File Analysis

### `KEYWORDS.txt`

- **Format:** Section header `[KEYWORDS]`, pipe-delimited records (`Category | kw1 | kw2 | ...`)
- **Total Lines:** 87
- **Comment / Section Lines Ignored:** 17
- **Valid Extracted Keywords:** 423 unique entries
- **Duplicate Entries Deduplicated:** 18
- **Malformed / Rejected Entries:** 0
- **Encoding:** UTF-8 valid (BOM-compatible)

### `LOCATIONS.txt`

- **Format:** Section header `[CITIES]`, region comments with Unicode box drawing, `REGION:City Name` records
- **Total Lines:** 76
- **Comment / Section Lines Ignored:** 7
- **Valid Extracted Locations:** 68 unique locations (mapped to `City, Country` format)
- **Duplicate Entries Deduplicated:** 0
- **Malformed / Rejected Entries:** 1 (Line 75: `IN:R` rejected — city name "R" is single-character/incomplete)
- **Encoding:** UTF-8 valid

---

## 4. Import, Merge, Persistence, and Discovery Queries

1. **Import:** Files submitted to `/api/leads/discovery/upload-txt?file_type=keywords|locations`. Parsing is in-memory only.
2. **Merge:** Merge mode (default ON) appends newly uploaded items case-insensitively into existing lists without data loss.
3. **Persistence:** Working lists persisted in browser `localStorage` (`leadgen_custom_keywords`, `leadgen_custom_locations`). No database migrations required.
4. **Query Generation:** Locations enforced as target constraints: `"{keyword} in {city}"`. Example: `"commercial lawyers in Roorkee, India"`.

---

## 5. Batching and Safety Budget Controls

- **Total Combinations:** 423 keywords x 68 locations = **28,764** total potential search queries
- **Single-Job Hard Cap:** 500 combinations (`DISCOVERY_MAX_COMBINATIONS_LIMIT`). Jobs exceeding this budget are rejected with `exceeds_safety_limit=True`. This is the **per-job execution guard**, not the pagination step size.
- **Navigation Step Size:** The user-configured execution budget is used for `total_batches` and `current_batch_num`.

### Correct Batch Counts for 28,764 Combinations

| Execution Budget | Total Batches | Formula |
|-----------------|---------------|---------|
| 100 (default) | **288** | ceil(28,764 / 100) |
| 500 (max cap) | **58** | ceil(28,764 / 500) |

### Batching Behavior

- Operator steps through batches with offset advancing by the configured budget: Batch 1: 1-100, Batch 2: 101-200, ..., Batch 288: 28,701-28,764
- Final partial batch has `effective_budget` clamped to remaining count; `current_batch_num` uses unclamped budget as step for consistent numbering
- No combinations are silently dropped. Consecutive batch windows are contiguous with no gaps or overlaps.
- **Zero API Quota on Preview:** File selection, parsing, merging, and preview make zero provider requests. Searches only execute on "Start Discovery Job" click.

---

## 6. Verification and Test Results (Session 3)

### Backend Tests

| Module | Result | Duration |
|--------|--------|---------|
| test_lead_discovery_integration.py (23 tests) | 23 PASSED | 258.78s |
| test_existing_scraper_isolated.py | 14 PASSED | 1.87s |
| test_two_key_rotation_provider_manager.py | 29 PASSED | — |
| test_phase2_security_review.py | 91 PASSED, 1 SKIPPED | — |
| test_phase3_workstream_b.py | 13 PASSED | — |
| test_phase3_workstream_c.py | 34 PASSED | — |
| test_phase2_security_followup.py | 41 PASSED | — |
| test_audit_correctness_url_sitemap_schema.py | 17 PASSED | — |
| test_startup_schema_safeguard.py | 5 PASSED | — |
| test_phase2_verification.py | 25 PASSED | 185.78s |
| test_gsc_service.py + test_dns_rebinding_proxy.py + test_phase2_browser_provider.py | 73 PASSED | 2.71s |
| test_ai_search_service.py + test_audit_accuracy_regression.py | 44 PASSED | 5.85s |
| 14 quick test modules | 33 PASSED | 3.17s |
| **TOTAL** | **442 PASSED, 1 SKIPPED** | — |

### Frontend Production Build

- Command: `npm run build` in `frontend/`
- Result: **Success** — 1886 modules transformed, built in 6.40s, 0 errors

### Agent Brain Validation

- `validate_agent_brain.py`: `strict_valid: true`, 62 factors consistent across all 7 layers, 0 missing/broken/orphan/duplicate, 2 non-blocking warnings

---

## 7. Working-Tree and Git State

- **Branch:** `fix/audit-url-sitemap-correctness`
- **HEAD:** `6fbc450`
- **Status:** All modifications remain uncommitted and unpushed as required
- **Protected databases and environment configurations:** Untouched
- **sample_leads.csv:** Removed from Git index (staged), file preserved on disk
