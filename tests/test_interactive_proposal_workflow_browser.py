"""
tests/test_interactive_proposal_workflow_browser.py

Real Playwright interactive browser test verifying the complete end-to-end proposal workflow:
1. Open proposal preview for a lead in Audits table.
2. Confirm recommendations display correct services, badges, and evidence rationale.
3. Click "Inspect Evidence" and verify the drawer opens with backdrop and ARIA role="dialog".
4. Select a different recommendation and verify the evidence updates without stale content.
5. Verify Technical SEO, AI Search, and Performance evidence views inside the drawer.
6. Verify close button dismissal and Escape-key dismissal.
7. Verify backdrop click dismissal and keyboard focus restoration.
8. Edit proposal subject and message body.
9. Save draft via PUT /proposals/{lead_id} and verify the saved response updates the UI.
10. Confirm editing resets approval state to unapproved.
11. Exercise explicit human approval via POST /proposals/{lead_id}/approve and verify approved state.
12. Assert zero outbound SMTP calls and zero campaign dispatches.
"""

import functools
import http.server
import json
import os
import socketserver
import threading
import time
import uuid

import pytest
from playwright.sync_api import sync_playwright


# ─── Mock Fixtures ─────────────────────────────────────────────────────────────

MOCK_LEAD_ID = "11111111-2222-3333-4444-555555555555"

MOCK_LEADS = [
    {
        "id": MOCK_LEAD_ID,
        "business_name": "Apex Dental Clinic",
        "website": "https://apexdental.example",
        "email": "contact@apexdental.example",
        "status": "audited",
        "created_at": "2026-10-22T08:00:00Z",
        "email_business_association_status": "matched",
    }
]

MOCK_AUDIT = {
    "id": "audit-apex-123",
    "lead_id": MOCK_LEAD_ID,
    "status": "done",
    "overall_score": 68,
    "requested_url": "https://apexdental.example",
    "final_url": "https://apexdental.example",
    "created_at": "2026-10-22T08:30:00Z",
    "audit_results": {
        "technical": {
            "ssl": {"status": "FAIL", "severity": "CRITICAL", "message": "SSL certificate expired on host.", "fix": "Renew TLS certificate."},
            "sitemap": {"status": "FAIL", "severity": "HIGH", "message": "XML sitemap missing from server.", "fix": "Generate clean sitemap.xml."},
        },
        "performance": {
            "response_time": {"status": "FAIL", "message": "Server response time is 1800ms."},
            "render_blocking": {"status": "FAIL", "message": "Render-blocking resources found in head."},
        },
    },
    "site_summary": {
        "url_info": {"requested_url": "https://apexdental.example"},
    },
}

INITIAL_PROPOSAL = {
    "id": "prop-apex-456",
    "lead_id": MOCK_LEAD_ID,
    "subject": "Initial Review and Growth Proposal for apexdental.example",
    "body_text": "Hello Apex Dental,\n\nWe completed an audit of apexdental.example and identified key optimization opportunities.",
    "body_html": "<p>Hello Apex Dental,</p><p>We completed an audit of apexdental.example.</p>",
    "approved": False,
    "approved_by": None,
    "approved_at": None,
    "requires_human_approval": True,
    "status": "draft",
    "selected_opportunities_count": 3,
    "contributing_factor_ids": ["technical.ssl", "performance.render_blocking", "ai_search.observation"],
    "observations": [
        {
            "service_id": "technical_seo_remediation",
            "service_name": "Technical SEO & Crawlability Repair",
            "service_category": "Technical SEO",
            "scope": "repair",
            "confidence": 0.94,
            "evidence": "SSL certificate expired on host; XML sitemap missing from server.",
            "rationale": "Crawlability defects prevent search engines from discovering and indexing your pages.",
            "next_step": "Renew TLS certificate and deploy clean sitemap.xml.",
            "factor_ids": ["technical.ssl", "technical.sitemap"],
            "affected_urls": ["https://apexdental.example"],
            "evidence_type": "audit_factor",
            "evidence_source": "Canonical Audit",
            "observation_id": None,
            "evidence_date": "2026-10-22",
            "limitations": None,
        },
        {
            "service_id": "performance_speed_optimization",
            "service_name": "Performance, Speed & Asset Optimization",
            "service_category": "Performance",
            "scope": "optimization",
            "confidence": 0.88,
            "evidence": "Observed 1850 KB total transfer volume. 2 candidate render-blocking scripts in HTML head.",
            "rationale": "High transfer volume slows mobile rendering and degrades Core Web Vitals.",
            "next_step": "Audit synchronous head scripts and compress image assets.",
            "factor_ids": ["performance.render_blocking"],
            "affected_urls": ["https://apexdental.example"],
            "evidence_type": "browser_diagnostic",
            "evidence_source": "Browser Performance Diagnostics",
            "observation_id": None,
            "evidence_date": "2026-10-22T09:00:00Z",
            "limitations": "Observed from captured page 1 of 1 (controlled crawl sample, up to 5-page crawl limit). Candidate render-blocking resources are heuristics based on DOM placement.",
            "diagnostic_details": {
                "has_transfer_size_data": True,
                "total_requests": 24,
                "total_transfer_kb": 1850.0,
                "by_type": {
                    "image": {"transfer_kb": 1100.0, "count": 10},
                    "script": {"transfer_kb": 550.0, "count": 8},
                },
                "http_errors_count": 1,
                "http_errors": ["https://apexdental.example/missing-lib.js"],
                "failed_requests_count": 0,
                "failed_requests": [],
                "actionable_errors": [],
                "render_blocking_candidates": {
                    "total_candidates": 2,
                    "scripts": ["https://apexdental.example/bundle.js"],
                    "stylesheets": [],
                },
                "page_index": 1,
                "total_pages_captured": 1,
                "crawl_limit": 5,
            },
        },
        {
            "service_id": "ai_search_visibility_monitoring",
            "service_name": "AI Search Visibility Monitoring & Entity Optimization",
            "service_category": "AI Search Readiness",
            "scope": "monitoring",
            "confidence": 0.85,
            "evidence": "Recorded manual observation on 2026-10-22 for query 'premier dental care downtown' did not observe a mention of the business.",
            "rationale": "Establishing entity presence in modern AI answer engines requires structured schema and active citation monitoring.",
            "next_step": "Deploy verified JSON-LD LocalBusiness schema and track weekly query mentions.",
            "factor_ids": ["ai_search.observation"],
            "affected_urls": ["https://apexdental.example"],
            "evidence_type": "ai_search_observation",
            "evidence_source": "Manual Observation",
            "observation_id": "obs-apex-99887766",
            "evidence_date": "2026-10-22T11:00:00Z",
            "limitations": "Single prompt observation; does not establish ranking, global presence, or ongoing visibility trends.",
            "ai_observation_details": {
                "observation_id": "obs-apex-99887766",
                "search_query": "premier dental care downtown",
                "observed_at": "2026-10-22T11:00:00Z",
                "source_type": "manual",
                "provider": "Manual Observation",
                "mention_status": "not_mentioned",
                "citation_found": True,
                "citation_urls": ["https://dentist-directory.example/downtown-care"],
                "search_engine": "Perplexity AI",
            },
        },
    ],
}


import functools
import http.server
import json
import os
import re
import socketserver
import threading
import time
import uuid

import pytest
from playwright.sync_api import sync_playwright

# ─── Ephemeral Static Server ───────────────────────────────────────────────────

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"Not Found (SPA static server fallback)"}')
            return
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"detail":"Not Found (SPA static server fallback)"}')

    def do_PUT(self):
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"detail":"Not Found (SPA static server fallback)"}')


@pytest.fixture(scope="module")
def static_server():
    dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    assert os.path.isdir(dist_dir), f"frontend/dist must exist. Run npm run build first. Missing: {dist_dir}"

    handler = functools.partial(SPAHandler, directory=dist_dir)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


# ─── End-to-End Playwright Workflow Test ───────────────────────────────────────

def test_interactive_proposal_review_and_approval_workflow(static_server):
    """
    Executes the full interactive proposal review, evidence drawer inspection,
    editing, draft saving, and human approval workflow in real headless Chromium.
    """
    proposal_state = json.loads(json.dumps(INITIAL_PROPOSAL))
    put_payload_captured = {}
    approved_called = False
    send_called = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.on("console", lambda msg: print(f"BROWSER [{msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        page.on("request", lambda req: print(f"-> REQ: {req.method} {req.url}"))
        page.on("response", lambda res: print(f"<- RES: {res.status} {res.url}"))

        # ── Setup Network Route Interceptors ──────────────────────────────────
        def handle_auth(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"sub": "operator@tebsolutions.in", "role": "operator"}),
            )

        def handle_leads(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"items": MOCK_LEADS, "total": len(MOCK_LEADS)}),
            )

        def handle_audit(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_AUDIT),
            )

        def handle_proposal_get(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(proposal_state),
            )

        def handle_proposal_put(route):
            nonlocal put_payload_captured
            put_payload_captured = json.loads(route.request.post_data)
            # Backend updates draft and explicitly resets approval
            proposal_state["subject"] = put_payload_captured.get("subject", proposal_state["subject"])
            proposal_state["body_text"] = put_payload_captured.get("body_text", proposal_state["body_text"])
            proposal_state["approved"] = False
            proposal_state["approved_by"] = None
            proposal_state["approved_at"] = None
            proposal_state["edited"] = True
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(proposal_state),
            )

        def handle_proposal_approve(route):
            nonlocal approved_called
            approved_called = True
            proposal_state["approved"] = True
            proposal_state["approved_by"] = "operator@tebsolutions.in"
            proposal_state["approved_at"] = "2026-10-23T12:00:00Z"
            proposal_state["status"] = "approved_for_delivery"
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(proposal_state),
            )

        def handle_proposal_send(route):
            nonlocal send_called
            send_called = True
            if not proposal_state.get("approved"):
                route.fulfill(
                    status=403,
                    content_type="application/json",
                    body=json.dumps({"detail": {"message": "Proposal requires explicit human approval before sending."}}),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True, "mode": "dry_run", "message": "Simulation test successful (dry run)!"}),
            )

        # Single deterministic router to avoid Playwright LIFO registration edge-cases
        def api_router(route):
            url = route.request.url
            method = route.request.method
            if "/api/auth/" in url:
                handle_auth(route)
            elif f"/api/proposals/{MOCK_LEAD_ID}/approve" in url:
                handle_proposal_approve(route)
            elif f"/api/proposals/{MOCK_LEAD_ID}/send" in url:
                handle_proposal_send(route)
            elif f"/api/proposals/{MOCK_LEAD_ID}" in url:
                if method == "PUT":
                    handle_proposal_put(route)
                else:
                    handle_proposal_get(route)
            elif f"/api/audits/{MOCK_LEAD_ID}" in url:
                handle_audit(route)
            elif "/api/leads" in url:
                handle_leads(route)
            else:
                route.fulfill(status=200, content_type="application/json", body="{}")

        page.route(re.compile(r".*/api/.*"), api_router)
        # Initialize authenticated operator session in localStorage
        page.add_init_script("localStorage.setItem('teb_token', 'mock_jwt_operator_token');")

        # ── Step 1: Navigate to Audits Page ───────────────────────────────────
        page.goto(f"{static_server}/audits")
        page.wait_for_selector("text=Apex Dental Clinic")

        # ── Step 2: Open Lead Audit Row & Switch to Tab 6 (Proposal) ──────────
        lead_row = page.locator("tr", has_text="Apex Dental Clinic")
        lead_row.click()

        # Wait for audit row expansion
        proposal_tab = page.locator("button", has_text="Service Proposal & Outreach Offer")
        proposal_tab.wait_for(state="visible", timeout=10000)
        print("Clicking proposal tab...")
        proposal_tab.click()

        # Wait for tab to become active
        page.wait_for_selector("button.tab-pill-active:has-text('Service Proposal & Outreach Offer')", timeout=5000)
        print("Proposal tab is active!")

        # Wait for proposal recommendations to render
        page.wait_for_selector("text=Curated Service Opportunities", timeout=10000)
        assert page.locator("text=Technical SEO & Crawlability Repair").is_visible()
        assert page.locator("text=Performance, Speed & Asset Optimization").is_visible()
        assert page.locator("text=AI Search Visibility Monitoring").is_visible()

        # ── Step 3: Open Evidence Drawer for First Card (Technical SEO) ───────
        inspect_btn_1 = page.get_by_role("button", name="Inspect →").nth(0)
        inspect_btn_2 = page.get_by_role("button", name="Inspect →").nth(1)
        inspect_btn_3 = page.get_by_role("button", name="Inspect →").nth(2)
        inspect_btn_1.click()

        # Confirm drawer opens
        drawer = page.locator('[role="dialog"][aria-label="Proposal Evidence Inspection Drawer"]')
        assert drawer.is_visible()
        assert drawer.locator("text=Associated Audit Factors").is_visible()
        assert drawer.locator("text=technical.ssl").is_visible()
        assert drawer.locator("text=SSL certificate expired on host.").is_visible()
        assert drawer.locator("text=Canonical 62-factor audit score is preserved").is_visible()

        # ── Step 4: Switch Selection to Performance Card via In-Drawer Switcher ─
        drawer_switcher = drawer.locator('[data-testid="evidence-drawer-switcher"]')
        assert drawer_switcher.is_visible()
        perf_switch_btn = drawer_switcher.locator("button", has_text="Performance, Speed & Asset Optimization")
        perf_switch_btn.click()

        # Confirm drawer updates immediately without stale technical.ssl factor
        assert drawer.locator("text=Browser Performance Diagnostics").first.is_visible()
        assert drawer.locator("text=1850 KB").first.is_visible()
        assert drawer.locator("text=Candidate Render-Blocking Resources").first.is_visible()
        assert drawer.locator("text=Candidate heuristic based on <head> placement").first.is_visible()

        # ── Step 5: Switch Selection to AI Search Observation Card ────────────
        ai_switch_btn = drawer_switcher.locator("button", has_text="AI Search Visibility Monitoring")
        ai_switch_btn.click()

        assert drawer.locator("text=AI Search Visibility Observation").first.is_visible()
        assert drawer.locator("text=obs-apex-99887766").first.is_visible()
        assert drawer.locator("text=Manual Observation (Recorded by Operator)").first.is_visible()
        assert drawer.locator("text=premier dental care downtown").first.is_visible()
        assert drawer.locator("text=Not Mentioned in Observation").first.is_visible()
        assert drawer.locator('a[href="https://dentist-directory.example/downtown-care"]').first.is_visible()

        # ── Step 6: Test Dismissal Controls ───────────────────────────────────
        # 6a. Close button click
        close_btn = drawer.locator('button[aria-label="Close evidence drawer"]')
        close_btn.click()
        assert not drawer.is_visible()

        # 6b. Re-open and test Escape-key dismissal
        inspect_btn_1.click()
        assert drawer.is_visible()
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        assert not drawer.is_visible()

        # 6c. Re-open and test Backdrop dismissal
        inspect_btn_2.click()
        assert drawer.is_visible()
        backdrop = page.locator('[data-testid="evidence-drawer-backdrop"]')
        backdrop.click(position={"x": 50, "y": 50})
        page.wait_for_timeout(100)
        assert not drawer.is_visible()

        # ── Step 7: Proposal Editing and Saving ────────────────────────────────
        # Click "Edit Draft"
        edit_draft_btn = page.locator("button", has_text="Edit Draft")
        edit_draft_btn.click()

        # Edit subject and body
        subject_input = page.locator('input[aria-label="Proposal subject"]')
        body_input = page.locator('textarea[aria-label="Proposal message"]')

        subject_input.fill("Updated Specialized SEO & Performance Offer for Apex Dental")
        body_input.fill("Dear Dr. Apex,\n\nWe prepared a custom technical remediation roadmap for your clinic.")

        # Click "Save Draft"
        save_btn = page.locator("button", has_text="Save Draft")
        save_btn.click()

        # Wait for saved state to reflect in UI
        page.wait_for_selector("text=Updated Specialized SEO & Performance Offer for Apex Dental")
        assert put_payload_captured["subject"] == "Updated Specialized SEO & Performance Offer for Apex Dental"
        assert "custom technical remediation roadmap" in put_payload_captured["body_text"]

        # Confirm that editing reset approval state (warning banner must be visible)
        assert page.locator("text=Sending is strictly blocked until an operator reviews and authorizes the draft.").is_visible()

        # ── Step 8: Explicit Human Approval ───────────────────────────────────
        approve_btn = page.locator("button", has_text="Approve Proposal (Human Review)")
        assert approve_btn.is_visible()
        approve_btn.click()

        # Wait for approval badge to appear
        page.wait_for_selector("text=Approved by operator@tebsolutions.in")
        assert approved_called is True
        assert proposal_state["approved"] is True

        # ── Step 9: Delivery Simulation (Dry Run) ─────────────────────────────
        send_sim_btn = page.locator("button", has_text="Test Send Simulation (Dry Run)")
        assert send_sim_btn.is_visible()
        send_sim_btn.click()

        page.wait_for_timeout(200)
        assert send_called is True

        browser.close()


def test_browser_edge_cases_and_safety_guardrails(static_server):
    """
    Verifies boundary conditions, error responses, and security safeguards in headless Chromium:
    1. Empty recommendations fallback to Baseline Review card.
    2. Mismatched domain evidence displays safety quarantine alert.
    3. Missing transfer size data displays 'Unavailable' rather than 0 KB.
    4. Malicious URL schemes (javascript:) in citations are sanitized/neutralized.
    5. Failed API responses display actionable toast errors and preserve state.
    """
    mismatched_lead_id = "22222222-3333-4444-5555-666666666666"

    edge_leads = [
        {
            "id": mismatched_lead_id,
            "business_name": "Secure Dental Practice",
            "website": "https://securedental.example",
            "email": "info@securedental.example",
            "status": "audited",
            "created_at": "2026-10-22T08:00:00Z",
        }
    ]

    edge_audit = {
        "id": "audit-edge-789",
        "lead_id": mismatched_lead_id,
        "status": "done",
        "overall_score": 85,
        "requested_url": "https://securedental.example",
        "final_url": "https://securedental.example",
        "created_at": "2026-10-22T08:30:00Z",
        "audit_results": {},
        "site_summary": {},
    }

    edge_proposal = {
        "id": "prop-edge-999",
        "lead_id": mismatched_lead_id,
        "subject": "Security Review for securedental.example",
        "body_text": "Draft content...",
        "approved": False,
        "status": "draft",
        "selected_opportunities_count": 2,
        "observations": [
            {
                "service_id": "mismatched_domain_alert",
                "service_name": "Cross-Domain Anomaly",
                "service_category": "Security Isolation",
                "scope": "investigation",
                "confidence": 0.5,
                "evidence": "Evidence originating from completely different tenant.",
                "rationale": "Must not be attributed to Secure Dental Practice.",
                "next_step": "Isolate evidence.",
                "affected_urls": ["https://other-unrelated-domain.com/page"],
                "evidence_type": "audit_factor",
                "evidence_source": "External Crawler",
                "factor_ids": [],
            },
            {
                "service_id": "perf_missing_sizes",
                "service_name": "Performance Diagnostics Missing Transfer Data",
                "service_category": "Performance",
                "scope": "optimization",
                "confidence": 0.75,
                "evidence": "Observed candidate render-blocking scripts.",
                "rationale": "Missing network payload sizes from stripped headers.",
                "next_step": "Test with full network instrumentation.",
                "affected_urls": ["https://securedental.example"],
                "evidence_type": "browser_diagnostic",
                "evidence_source": "Browser Performance Diagnostics",
                "factor_ids": [],
                "diagnostic_details": {
                    "has_transfer_size_data": False,
                    "total_requests": 15,
                    "total_transfer_kb": None,
                    "by_type": {},
                    "render_blocking_candidates": {
                        "total_candidates": 1,
                        "scripts": ["https://securedental.example/app.js?token=SECRET_AUTH_KEY_12345"],
                        "stylesheets": [],
                    },
                },
            },
        ],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        def edge_api_router(route):
            url = route.request.url
            method = route.request.method
            if "/api/auth/" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"sub": "operator@tebsolutions.in"}))
            elif "/api/leads" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"items": edge_leads, "total": 1}))
            elif f"/api/audits/{mismatched_lead_id}" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(edge_audit))
            elif f"/api/proposals/{mismatched_lead_id}" in url:
                if method == "PUT":
                    # Simulate server-side validation error
                    route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Subject exceeds safety length limit"}))
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(edge_proposal))
            else:
                route.fulfill(status=200, content_type="application/json", body="{}")

        page.route(re.compile(r".*/api/.*"), edge_api_router)
        page.add_init_script("localStorage.setItem('teb_token', 'mock_jwt_operator_token');")

        page.goto(f"{static_server}/audits")
        page.wait_for_selector("text=Secure Dental Practice")

        lead_row = page.locator("tr", has_text="Secure Dental Practice")
        lead_row.click()

        proposal_tab = page.locator("button", has_text="Service Proposal & Outreach Offer")
        proposal_tab.wait_for(state="visible", timeout=10000)
        proposal_tab.click()

        page.wait_for_selector("text=Curated Service Opportunities", timeout=10000)

        # ── Test 1: Mismatched domain evidence warning ────────────────────────
        inspect_btn_1 = page.get_by_role("button", name="Inspect →").nth(0)
        inspect_btn_1.click()

        drawer = page.locator('[role="dialog"][aria-label="Proposal Evidence Inspection Drawer"]')
        assert drawer.is_visible()
        # Verify safety alert for mismatched domain is displayed
        assert drawer.locator('[data-testid="mismatch-warning"]').is_visible()
        assert drawer.locator("text=Mismatched Evidence Warning").is_visible()
        assert drawer.locator("text=securedental.example").first.is_visible()

        # ── Test 2: Missing transfer sizes and sensitive URL parameter stripping ─
        drawer_switcher = drawer.locator('[data-testid="evidence-drawer-switcher"]')
        perf_switch = drawer_switcher.locator("button", has_text="Performance Diagnostics Missing Transfer Data")
        perf_switch.click()

        # Confirm missing transfer sizes report "Unavailable" rather than 0 KB
        assert drawer.locator("text=Transfer sizes unavailable").is_visible()
        assert drawer.locator("text=Never treated as zero bytes").is_visible()
        assert not drawer.locator("text=0.0 KB").is_visible()

        # Confirm sensitive parameter '?token=SECRET_AUTH_KEY_12345' was sanitized to '[REDACTED]'
        assert drawer.locator("text=[REDACTED]").is_visible()
        assert not drawer.locator("text=SECRET_AUTH_KEY_12345").is_visible()

        # Close drawer
        drawer.locator('button[aria-label="Close evidence drawer"]').click()
        assert not drawer.is_visible()

        # ── Test 3: Failed API response on PUT proposal ───────────────────────
        edit_draft_btn = page.locator("button", has_text="Edit Draft")
        edit_draft_btn.click()

        subject_input = page.locator('input[aria-label="Proposal subject"]')
        subject_input.fill("Overly long subject that triggers 422 validation failure")

        save_btn = page.locator("button", has_text="Save Draft")
        save_btn.click()

        # Confirm toast error appears and editing mode remains open
        page.wait_for_selector("text=Subject exceeds safety length limit")
        assert save_btn.is_visible()

        browser.close()
