# LEADGEN Master Product Plan

**Purpose:** Single source of truth for completing LEADGEN as a trustworthy advanced SEO, Local SEO, AI-search readiness/visibility, website quality, web-design diagnostics, and client-proposal platform.

**Status at creation:** Scope and execution plan only. This document does not claim the listed future work is implemented.

**Baseline:** Published `main` at `1253824` (verify from Git before execution).

**Working repository:** `C:\Users\LENOVO\LEADGEN-RELEASE`

**Protected original checkout:** `C:\Users\LENOVO\LEADGEN` (must remain untouched).

**Published commits to preserve:**
- `9eceda8` — Windows selector event-loop fix
- `83f92a0` — database schema initialization safeguard
- `8332ef2` — crawl limits and audit observability
- `1253824` — synchronous audit network-work safeguards

---

## 1. Product vision

LEADGEN should not merely generate a checklist PDF. It should perform a credible, evidence-backed assessment of a live business website, distinguish confirmed defects from unavailable evidence, explain how each issue affects discoverability or user experience, prioritize fixes realistically, display results in a modern interface, generate a polished client-ready PDF, and help TEB Solutions prepare an accurate personalized service proposal.

The service recommendation should integrate relevant needs across:

1. Technical SEO and crawlability.
2. On-page SEO and content quality.
3. Local SEO and business/entity consistency.
4. AI-search readiness and measurable AI-search visibility where data can be gathered reliably.
5. Performance and browser-rendered behavior.
6. Web design, UI/UX, accessibility, conversion paths, and observable frontend/code/runtime defects.
7. Website redesign or implementation work where evidence supports it.

The system must never promise rankings, AI citations, traffic increases, conversion lifts, or guaranteed search outcomes. Recommendations should be based on evidence actually collected.

## 2. Current baseline: what exists and what does not

### Existing implementation (verify against code before relying on this list)

- React/Vite frontend and FastAPI backend.
- PostgreSQL-backed leads/audits and API contracts.
- Canonical 62 audit factors grouped into 11 categories.
- Basic technical, on-page, indexability, content, Local SEO, performance, schema, UX, and crawl checks.
- Bounded crawler and sitemap work, response size limits, finite network timeouts and timing logs.
- Optional Playwright browser evidence, disabled by default; local fixture tests cover rendered content, console errors, failed requests, resource limits and SSRF controls.
- ReportLab PDF generation.
- Existing email/campaign workflows, which must be inspected before proposing integration changes.
- Four published commits listed above.

### Known correctness problems from the Car Medic Motors report

1. A lead/root URL `https://carmedicmotors.in/` was represented in the report as `https://carmedicmotors.in/lucknow`, without the three URL identities being clearly separated.
2. Sitemap reporting used `https://carmedicmotors.in/lucknow/robots.txt` and claimed no sitemap existed, even though the user reports a sitemap is present.
3. The report reported LocalBusiness JSON-LD present in one factor and missing in another.
4. The PDF's generic priorities labelled many unrelated issues `CRITICAL`.
5. The frontend and PDF were not visibly redesigned by the four backend-focused commits.

These defects must be reproduced in deterministic tests and corrected before the product can be treated as trustworthy.

## 3. Non-negotiable agent rules

1. Read this plan at the start of every session and before any new work. If the requested action conflicts with this plan, stop and explain the conflict instead of silently changing scope.
2. Keep this plan read-only during execution. Only the user may authorize a change to the scope document.
3. Work exclusively in `C:\Users\LENOVO\LEADGEN-RELEASE`; never alter `C:\Users\LENOVO\LEADGEN`.
4. Verify current branch, HEAD, remote state and clean/dirty working tree before work. Never overwrite unrelated changes.
5. Branch new work from a verified current published `main`, using `fix/audit-truth-and-report-ux` unless that branch exists or the repository state requires a safe alternative. Never rewrite the four published commits.
6. Work in the phase order below. A phase is complete only after its acceptance gate passes.
7. No tangential refactors, providers, frameworks, AI model APIs, TREG integration, Lighthouse, PSI, email campaign changes, database migrations or cloud deployment unless a specific phase here requires them and the dependency/impact is reviewed first.
8. Do not claim a capability exists merely because a module, test stub, API field or documentation entry exists. Verify the real code path and output.
9. Do not weaken tests to obtain a passing suite. Every regression test must fail against the demonstrated defect and pass after the fix.
10. Keep commits local, small, and phase-gated. Do not push, merge or deploy without a separate explicit release authorization.
11. Never show credentials, access tokens, JWTs, passwords, private lead data or a full DB URL in logs or reports. Never edit `.env` to make tests pass.
12. Never write to `leadgen` or `leadgen_test` during automated/live testing. Use a newly verified disposable database and remove only task-owned test artifacts.
13. Do not send emails or run campaigns during verification. Email generation must first be tested as a preview only.
14. Never use `START.bat` or `STOP.bat` in controlled tests; manage only process IDs created by the task.
15. After each phase, report changed files, commands, actual test outcomes, and the next planned phase. No circular re-planning after a gate passes.

## 4. Architecture and scoring policy

### Preserve the canonical baseline

Keep the 62 existing canonical factors, their IDs, names, group assignments, weights, expected types, scoring formulas, and API/database/PDF compatibility unless a separate, explicit, versioned scoring proposal is approved.

Advanced audits can initially produce **diagnostics, evidence, coverage data and optional insights** without automatically increasing the number of scored factors. If new scored factors eventually prove necessary, propose a versioned registry, migration/persistence, score version, API contract, frontend, PDF and regression-test update before implementation. Do not quietly modify factor weights.

### Shared evidence model

Build/reuse common evidence objects where feasible. Every finding should track:
- factor ID and group;
- status and confidence/evidence quality;
- requested URL, final response URL and declared canonical URL as distinct values;
- source and timestamp of evidence;
- response status/content type/redirect chain where applicable;
- whether the check completed, failed, timed out, was skipped or is not applicable;
- short observation, expected condition and actionable recommendation;
- priority rationale.

Avoid each factor constructing its own URLs or independently parsing the same HTML/JSON-LD if shared page evidence is available.

### Status semantics

- `PASS`: check executed and explicit passing criteria were met.
- `WARN`: non-fatal limitation or issue observed.
- `FAIL`: sufficient evidence confirms a defect.
- `ERROR`/unavailable: the check could not execute reliably; do not report a confirmed site defect.
- N/A: preserve the existing contract if supported.

An HTTP 200 response is not proof an XML sitemap is valid. Missing evidence is not a PASS. A timed-out check is not proof that the website has the defect.

## 5. Phase 0 — Preflight and evidence baseline

1. Verify published `main`, expected commit lineage, branch/remote status and clean working tree.
2. Read `.agent` control files, `SYSTEM.md`, project documentation, README, changelog, frontend page structure, audit modules, PDF generator, and email/outreach workflow.
3. Identify actual functions and data paths for URL normalization, lead URL persistence, classifier, requested audit target, redirect/final URL, canonical parsing, robots/sitemap discovery, schema parsing, 62-factor scoring, report generation and email personalization.
4. Save a baseline fixture/report for deterministic test comparisons, using no production data or secrets.
5. Capture current UI screenshots and render current PDF pages for before/after comparison.
6. Record known defects and tests that reproduce them.

**Gate:** root cause paths identified; no unrelated working-tree changes overwritten; baseline tests and screenshots retained in task artifacts (not committed as secrets or generated production reports).

## 6. Phase 1 — Audit truth and core correctness

### 6.1 URL identity

Track separately:
- `requested_url`: exact normalized user/lead audit target.
- `final_url`: actual final response URL after redirects.
- `canonical_url`: HTML-declared canonical value.

Never substitute canonical URL for the requested target. Record real redirect chain separately. Define a clear root-vs-path crawl scope. Ensure report title, lead, audit record, frontend, API and PDF show these distinctions without changing the requested target silently.

### 6.2 Robots and sitemaps

- Derive the origin using URL parsing, including scheme, host and effective port; site-wide robots discovery must not append `/robots.txt` to a requested page path.
- Fetch origin `/robots.txt` first.
- Parse all `Sitemap:` declarations, validating URL resolution and safe boundaries.
- Probe existing supported origin-root candidates if no usable declaration exists, including `/sitemap.xml`, `/sitemap_index.xml`, `/sitemap-index.xml`, `/wp-sitemap.xml` and relevant existing CMS candidates.
- Validate content type as a hint and validate XML structure/root as the deciding check. Reject HTTP 200 HTML pages as sitemaps.
- Handle sitemap indexes with existing limits of at most 5 child sitemap fetches and 100 discovered URLs unless reviewed evidence justifies another cap.
- Preserve SSRF, redirect, response-size, timeout and cleanup safeguards.
- Return diagnostic evidence: actual requested/final sitemap URL, HTTP status, parse result, index/URL counts and reason accepted/rejected.
- Distinguish confirmed missing sitemap from inaccessible, timed-out or invalid resource.

### 6.3 Shared JSON-LD/structured data

- Parse scripts once through a shared helper where practical.
- Handle object/array roots, `@graph`, nested entities, type strings/arrays and full schema type URLs.
- Separate presence of schema, supported entity type and required properties.
- Keep visible HTML business/contact data distinct from JSON-LD-only information.
- Make the generic schema and LocalBusiness checks consistent when given the same evidence.

### 6.4 Priority model and recommendation correctness

Replace blanket `CRITICAL` labels with a deterministic policy. Separate status from priority. Make priority reflect impact, affected scope, confidence and evidence quality. Remove unsubstantiated statements about ranking lifts, conversion percentages or legal requirements. Each action must relate to the actual observed finding and explain why.

### 6.5 Regression cases

Cover: root requested URL plus `/lucknow` canonical; real redirect chain; page-path robots bug; robots-declared sitemap; sitemap index/children; HTML masquerading as XML; malformed XML; timeout; sitemap cap; JSON-LD `@graph`; `@type` arrays; contradictory current schema result; error-vs-failure status; score stability.

**Gate:** all demonstrated URL/sitemap/schema defects reproduced before fix and pass afterward; all 62 factors and scores preserve contract; no production DB/network needed for deterministic tests.

## 7. Phase 2 — Seven advanced audit domains plus web-design code health

Build each as evidence-backed diagnostics. Do not claim an external signal was measured unless it was actually retrieved.

### Domain A — AI-search readiness and visibility

Readiness checks:
- Crawl access/robots rules for relevant search and AI crawlers, clearly separating crawler access from ranking or inclusion claims.
- Clear entities, consistent brand/business facts, useful headings and direct question-answer content.
- Structured data that agrees with visible content.
- Unique, original information with source/author/date information where relevant.
- Page accessibility and indexability.
- `llms.txt` may be shown as an optional informational observation only; do not imply it is a recognized ranking requirement or guarantees AI citation.

Visibility measurements:
- Define a repeatable query set by brand, products/services, locations and informational intents.
- Where legally and technically permitted, take dated observations of brand/domain mentions and citations from available AI-search interfaces or approved data sources.
- Store engine, date, query, market/language, response excerpt, cited URLs, capture method and repeatability/limitations.
- Separate AI visibility measurements from readiness heuristics. Never fabricate AI answer appearances or infer visibility from JSON-LD alone.
- Report coverage, query sampling methodology and uncertainty. Treat rankings/AI answers as volatile observations, not guaranteed outcomes.

### Domain B — Deep technical SEO, crawlability and indexability

- Root robots.txt and sitemap discovery; sitemap URL validation and sitemap-to-crawl coverage.
- HTTP status codes, redirect chains/loops, canonical conflicts and duplicate URL variants.
- Meta robots and `X-Robots-Tag` rules.
- Orphan pages, internal-link graph, crawl depth and important-page reachability.
- Broken internal links, carefully bounded external link status checks, image/script/style resource failures.
- Pagination and query parameters, trailing slash, hostname and scheme normalization.
- Duplicate/near-duplicate URLs and thin/empty templates where evidence is adequate.
- Raw HTML versus rendered DOM differences.
- Optional hreflang and international targeting checks only where applicable.

### Domain C — Actual Google Search performance and indexing

- Optional Google Search Console connection via explicit user authorization and read-only scopes where sufficient.
- Query/page/country/device/date performance: clicks, impressions, CTR and average position, with API sampling/limitations disclosed.
- URL Inspection/indexing coverage only for properties authorized by the user and endpoints actually available.
- Connect query/page performance to audit findings without claiming causation without evidence.
- Identify declining pages, high-impression/low-CTR candidates and query/page overlap where data supports it.
- Clear empty-data, permissions-missing and property-not-connected states.
- Never request or store Google credentials directly; implement secure OAuth/token handling only in a separately reviewed integration phase.

### Domain D — Advanced performance and browser testing

- Preserve existing lab LCP/CLS/TTFB measurement and optional Playwright capture.
- Add reliable local/browser diagnostics for render blocking, slow requests, transfer size, script errors, failed resources, DOM readiness and resource loading.
- Distinguish lab/synthetic values from field data.
- Core Web Vitals field measurements include LCP, INP and CLS; do not pretend lab simulation alone proves field INP or CrUX results.
- Optionally connect to a supported approved field-data source after credentials/config are authorized.
- Track viewport/device and test conditions, cache state, repeated-run variability and sample size.
- No score mutation from score-neutral lab data unless a future score version is explicitly approved.

### Domain E — Advanced content and search intent

- Content extraction quality and main-content versus boilerplate separation.
- Title/meta/H1 uniqueness and heading semantics.
- Near-duplicate content and likely cannibalization candidates.
- Thin-content/template issues based on content quality and intent, not arbitrary word-count rules alone.
- Topic and question coverage gaps using actual target query data when connected; otherwise mark as heuristic.
- Internal links from related pages, page purpose, content freshness and evidence of outdated details.
- Conversational/question answering readiness and useful, direct responses without keyword stuffing.
- Recommendations must cite affected pages and evidence, not just demand arbitrary word counts.

### Domain F — Entity, Local SEO and business consistency

- Business name/address/phone/hours consistency between visible page, JSON-LD, contact page and authorized business listing data.
- LocalBusiness/Organization/AutoRepair and other appropriate schema type/property validation.
- Location page coverage, duplicate or thin location pages, city/service-title relevance.
- Map and directions/contact access where appropriate.
- Google Business Profile data only via authorized integration; do not scrape or claim inaccessible profile data.
- Distinguish visible NAP, schema NAP and third-party listing NAP.
- Flag mismatch evidence without guessing the correct business data.

### Domain G — Accessibility, trust, usability and conversion

- Keyboard navigation, focus visibility, semantic landmarks, accessible names, form labels and error messages.
- Contrast measured when possible; disclose limitations of automated contrast checks.
- Responsive layout/overflow and mobile tap-target diagnostics.
- Navigation clarity, phone/email/contact path, CTA visibility and form usability.
- Broken forms or failed client-side requests only when observable during authorized testing.
- Privacy/terms/cookie observations must be legally cautious and jurisdiction-aware, never unsupported legal advice.
- Trust signals and business contact details must be evidence-based.

### Domain H — Advanced web design, implementation and observable code health

Goal: find actionable redesign/repair opportunities and connect them to a truthful web-design service proposal.

Assess observable/live behavior:
- Page layout hierarchy, header/hero/content/footer structure, alignment and spacing consistency.
- Visual hierarchy, typography scale, line length, contrast, brand consistency and readability.
- Responsive breakpoints, horizontal overflow, clipping, broken grids, overlapping elements and content that disappears at mobile/tablet/desktop sizes.
- Navigation quality, CTA placement, form flow, phone/email/WhatsApp interaction paths and conversion friction.
- Broken images/assets, missing CSS/JS, HTTP 4xx/5xx subresources, failed requests, browser console errors and relevant runtime errors.
- Excessive or render-blocking resources, oversized assets, obvious layout shift and performance/design tradeoffs.
- Semantic HTML, heading hierarchy, accessible controls, image alt coverage and use of correct interactive elements.
- Design inconsistency across key pages, reused components, duplicate/low-quality page templates and weak location/service page templates.
- Reproducible screenshots, page/viewport, failed request evidence and browser logs where captured.

Important capability boundary:
- A public-site crawl can inspect rendered output, response headers, HTML/CSS/JS resources, browser console/runtime errors and resource failures. It cannot truthfully claim a full source-code audit of private source code that was not supplied.
- Label findings as **observed live-site defect**, **static asset/markup concern**, **rendered-browser issue**, **heuristic design recommendation**, or **requires source-code access/manual review**.
- Source-code static analysis is a separate authorized mode only when the user provides access to the repository or files. Never exploit, bypass authentication or attempt destructive security testing.
- Screenshots and visual comparison must use authorized, bounded browser tests; default browser capture remains disabled unless explicitly enabled for a controlled audit.

**Gate for this phase:** each domain has a capability definition, evidence schema, clear limitations, fixtures, and an acceptance test. Do not advertise unsupported tests as implemented.

## 8. Phase 3 — Modern, visibly upgraded frontend

Use the existing React/Vite stack unless code inspection justifies otherwise.

Create a cohesive design system using actual TEB Solutions brand assets/colors if available. Use reusable spacing, typography, layout, cards, charts, status/priority tokens, and responsive breakpoints.

Deliver visibly improved interfaces:
- Audit overview with requested/final/canonical URLs, score, statuses and coverage.
- Category summaries for the canonical 11 groups.
- Detailed findings with status, priority, confidence, evidence, actual URL and recommended fix.
- Sitemap/robots diagnostics panel.
- Crawl coverage and per-page issues list.
- Browser-vs-raw evidence comparison when available.
- Optional Advanced Audit areas, with explicit statuses such as Not connected, Not run, Unavailable, and Complete.
- Search Console/AI visibility panels that show real data or clear disconnected/unsupported states, never fake data.
- Action plan and export/report controls.
- Loading, partial, timeout, empty, and failed states; avoid stale findings being displayed as current.
- Accessible keyboard states, readable contrast, responsive mobile, tablet and desktop layouts.

Do not simply recolor the existing page. Provide before/after screenshots of key screens. Verify existing login, leads, audits and PDF workflows still function with fixture-backed or isolated data.

**Gate:** production build and frontend tests pass, visual differences are evident and reviewed, and the rendered UI displays correct backend/API fields.

## 9. Phase 4 — Professional PDF report redesign

Redesign the ReportLab output to be client-ready and visually consistent with the frontend and TEB Solutions identity.

Required structure:
1. Branded cover, business/website, requested URL, date and overall score.
2. Executive summary with verified strengths and top opportunities.
3. Scope/methodology: requested, redirect/final, canonical URLs; pages crawled; browser enabled/disabled; unavailable checks.
4. Category score breakdown tied to the canonical 62-factor contract.
5. Prioritized action plan with honest urgency and reason.
6. Evidence-backed detailed findings with inspected URLs and recommended actions.
7. Robots/sitemap diagnostics.
8. Crawl coverage and page-by-page results.
9. Performance and browser data labeled synthetic/lab/field accurately.
10. Search Console and AI-search observations only if data was actually collected.
11. Website design, accessibility, responsive behavior and observable code/runtime findings.
12. Limitations, skipped checks, retrieval errors and methodology.
13. Professional page headers/footers, page numbering, readable tables and correct page breaks.

PDF requirements:
- No contradictory findings for shared evidence.
- No invented values, fake comparison data, generic placeholder phone/email/URLs, unsupported legal/ranking promises or fabricated API measurements.
- Keep colors/labels/priority consistent with frontend.
- Avoid excessive blank space, overflow, unreadable tables, duplicated recommendations and sections that imply a check occurred when it did not.
- Report output values must match API and persisted factor results.

**Gate:** generate deterministic fixture PDFs, validate PDF signature/parser, render key pages to images and visually inspect cover, summary, action plan, detail tables, site-crawl section and page breaks. A successful PDF build alone is insufficient.

## 10. Phase 5 — Website service-opportunity and client email workflow

This is a core product outcome: after a complete audit of a live site, LEADGEN should turn verified deficiencies into a credible proposal for TEB Solutions, combining the applicable services:

- SEO and technical SEO remediation.
- Local SEO and business/entity consistency.
- AI-search readiness and measurable visibility monitoring where available.
- Website UI/UX improvements.
- Website redesign or implementation when actual design/technical evidence supports it.
- Performance, accessibility and conversion improvements.

### Evidence-to-offer mapping

Examples:
- Confirmed URL/canonical/indexability/crawl issues → technical SEO remediation.
- Validated sitemap, internal-link or indexability problems → crawl/indexing repair.
- Consistent schema/visible business detail mismatches → structured data and Local SEO improvements.
- Confirmed viewport, navigation, typography, broken asset or form defects → web design/UX repair or redesign opportunity.
- Confirmed browser errors, resource failures or oversized assets → implementation/performance fixes.
- Content/query coverage gaps backed by actual query or page evidence → content/SEO strategy.
- AI-search readiness gaps → content/entity improvements; actual AI visibility monitoring only where observed from a supported source.

Never recommend a full redesign merely because a website failed a generic design heuristic. Distinguish small fixes from broader redesign opportunities and explain the supporting evidence.

### Proposed opportunity record

For each potential service opportunity, record:
- relevant audit finding IDs;
- evidence and affected URLs;
- service category;
- proposed scope (repair, optimization, redesign or monitoring);
- confidence and prerequisites;
- rationale and next step.

### Email generation requirements

- Generate a personalized draft after audit completion, using only verified findings from that audit.
- Choose at most 2–3 salient, high-confidence observations instead of dumping all 62 factors into an email.
- Connect each observation to a relevant service offer and a simple invitation for a manual review or conversation.
- If URL identity, sitemap or schema confidence is unresolved, do not use those findings as outreach claims.
- Never fabricate traffic, ranking position, revenue loss, conversion lifts, competitor superiority, audits, or AI visibility.
- Clearly separate observed facts from suggestions and avoid alarmist or false “critical” claims.
- Allow preview/edit/approve; do not send automatically as part of the audit or verification test.
- Preserve existing unsubscribe/suppression rules, email eligibility, sender controls and campaign safety guards.
- Record which finding IDs contributed to each generated claim, so the draft can be audited and corrected.

### Email acceptance tests

- A broken sitemap observation maps only to a relevant SEO recommendation when verified.
- A verified mobile/layout/form/browser defect can map to web design/UX service.
- An AI-readiness heuristic is not presented as proof of lost AI traffic.
- Contradictory or low-confidence findings are excluded from the draft or disclosed cautiously.
- Email claims can be traced to actual audit evidence.
- Draft is previewed and requires human approval before sending.
- No actual email is sent in automated tests.

## 11. Phase 6 — Test and validation strategy

### Unit/regression tests

- Requested, final and canonical URL separation.
- Redirect chain and path/scheme/hostname normalization.
- Origin robots.txt and sitemap directives.
- Sitemap index/child bounds, bad XML, HTML 200, errors and timeout states.
- Shared JSON-LD parser and cross-factor consistency.
- 62-factor registry, order/identity/weights, score formulas and N/A handling.
- Evidence/status/priority logic.
- Response byte limits, timeout, cleanup and crawler security.
- Raw HTML versus rendered browser differences.
- CWV lab/field labeling and confidence.
- Design issue evidence classifications.
- API to frontend/PDF result consistency.
- Evidence-to-service mapping and email draft claim provenance.

### Benchmark/known-site tests

Create a versioned local fixture corpus representing:
- Correct site with declared sitemap.
- Subpath page with domain-root robots/sitemap.
- Root URL with different canonical path.
- Real HTTP redirect chain.
- Valid and invalid XML sitemap.
- Sitemap index with more children than allowed.
- Multiple JSON-LD entities, arrays and `@graph`.
- JavaScript-rendered H1/title/CTA with raw-versus-rendered differences.
- Missing/failed CSS/JS/image resources and console errors.
- Responsive layout defects at mobile/tablet/desktop viewports.
- Misleading or unavailable metadata that must not be labelled a confirmed defect.

Track expected observations, false positives, false negatives and retrieval failures. Do not claim universal accuracy from a few fixtures. Use live sites only in the single authorized validation phase and do not use them as unstable unit-test dependencies.

### Integration/end-to-end tests

- Use a newly verified disposable database; never target `leadgen` or `leadgen_test` for test writes.
- Test one controlled audit after all offline gates pass.
- Verify audit reaches correct terminal status, factor results persist, PDF is valid and consistent, frontend displays the data and email draft is preview-only.
- Ensure no email is sent.
- Clean up only the test lead, related audit, test PDF and disposable DB created by the run; verify removal.

### Full suite

Collect suite count, then actually execute all safe offline tests. Report passed/failed/error/skipped/deselected counts separately. Verify test side effects before execution. Do not state that test collection means tests ran.

## 12. Phase 7 — Final validation of the original defect

After all offline gates pass, run one controlled audit of `https://carmedicmotors.in/` with:
- newly created, explicitly verified disposable database;
- browser capture disabled for this base correctness pass;
- crawl max set to 3;
- finite total runtime budget;
- exactly one audit attempt.

Validate in audit result, logs, API, frontend and PDF:
1. Requested URL remains the root URL.
2. Any real final redirect destination is recorded separately.
3. Canonical `/lucknow` is shown only as canonical metadata unless an explicit product policy says otherwise.
4. Actual origin robots.txt and declared sitemap URLs/statuses are logged and checked.
5. Sitemap is validated as XML, not inferred from HTTP status alone.
6. Generic and LocalBusiness schema findings agree with shared evidence.
7. Priorities reflect evidence and do not label all failures Critical.
8. Exactly 62 factors and expected score semantics remain intact.
9. PDF and frontend match the audit API data.
10. Generated email draft contains only verified, traceable claims and is not sent.

If the live site is unavailable, protected by a challenge, or cannot be validated within the budget, report exactly what was tested and why. Do not infer a defect from a failed fetch. Do not rerun indefinitely.

Cleanup: remove only task-owned test artifacts and disposable database; stop only task-owned processes; verify the database, test records and PDF are absent. If cleanup fails, stop and report the exact leftover artifact.

## 13. Phase 8 — Release-readiness decision

No push/deploy during implementation. Report:
- Root causes and fixes.
- Files changed and commits per phase.
- Frontend before/after screenshots.
- PDF before/after rendered pages.
- Exact capability status for all 8 audit domains.
- Search Console connection state and exact data available, if implemented.
- AI-search monitoring sources and coverage, if implemented.
- Test commands and true execution counts.
- End-to-end audit and cleanup results.
- Remaining limitations and external prerequisites.
- Current branch, HEAD, status and commit history.

Declare `READY FOR RELEASE REVIEW` only if all required gates pass. Otherwise declare `NOT READY` and list specific blockers. No “finished” claim based only on clean builds or passing backend tests.

## 14. Mandatory agent recovery instruction

Whenever the agent is unsure what to do next, believes the task is blocked, or starts proposing work outside scope:

1. Re-read Sections 1, 3, 5–13 of this plan.
2. Identify the current phase and its acceptance gate.
3. State the last completed gate using actual test/evidence results.
4. Resume only the next incomplete gate.
5. Do not restart completed phases unless a regression or concrete new evidence requires it.
6. Do not add unrelated features.
7. If current user instructions differ from this plan, ask for clarification before making an irreversible choice.

This document is the read-only product scope source of truth. Do not edit it as part of ordinary implementation work. Any changes to the plan require explicit user authorization.

---

## Source context / product rationale

The product direction includes advanced AI-oriented search experiences discussed in The Times of India article “Google Search gets its biggest upgrade in 25 years: Here's what's actually changing” (May 20, 2026), including AI Overviews, AI Mode, interactive results, and agent-like discovery. Treat this as motivation to measure real AI-search readiness and visibility—not evidence that any specific optimization guarantees AI citations.

Useful official documentation to verify at implementation time:
- Google guidance for AI features in Search: https://developers.google.com/search/docs/appearance/ai-features
- Google Search Console Search Analytics API: https://developers.google.com/webmaster-tools/v1/searchanalytics/query
- Google Search Central advice for content in AI search: https://developers.google.com/search/blog/2025/05/succeeding-in-ai-search/

Source-derived plans, current code capabilities, future features, heuristic findings, and externally measured metrics must always be labeled distinctly.

## 15. Copy/paste master agent directive

Use the following as the persistent top-level instruction for Antigravity after placing this file at `docs/LEADGEN_MASTER_PRODUCT_PLAN.md` on the new local feature branch:

> Read `docs/LEADGEN_MASTER_PRODUCT_PLAN.md` completely before changing code. This file is the read-only source of truth for the LEADGEN product goal, scope, phases, safety rules, acceptance gates, and final release criteria. Do not change the document during implementation. Verify repository state first, then work only on the first incomplete phase. Follow the gates in order. Preserve the four published commits and the protected original checkout. Do not start later phases early, add unrelated features, skip tests, or claim completion from a build/test count alone. At each checkpoint, report evidence and actual executed test results, then continue to the next incomplete phase without re-planning completed work. If you lose context, stop and reread the plan, identify the current phase and its acceptance gate, and resume there. If a required decision or prerequisite is missing, stop at that specific blocker. No push, merge, production data writes, emails, or deployment without a separate explicit authorization.
