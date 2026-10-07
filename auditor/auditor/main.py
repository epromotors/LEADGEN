#!/usr/bin/env python3
# main.py — SEO Audit Tool CLI Entry Point
# TEB Solutions | tebsolutions.in
# Usage: python main.py https://example.com

import sys
import os
import time
import datetime

# ── Path fix for running from project root ──────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auditor.core import make_session, normalize_url, fetch_page, get_domain
from auditor.crawler import crawl_site, audit_page_seo, aggregate_site_issues
from auditor.technical import (
    audit_ssl, audit_sitemap, audit_robots,
    audit_canonical, audit_favicon, audit_mobile
)
from auditor.onpage import (
    audit_title, audit_meta_description, audit_h1,
    audit_og_tags, audit_schema
)
from auditor.images import audit_alt_text, audit_webp, audit_lazy_loading
from auditor.links import audit_broken_links
from auditor.social import audit_social_links, audit_contact_links, audit_whatsapp
from auditor.trust import audit_trust_pages
from reporter.pdf_report import build_pdf
from config import SCORE_WEIGHTS, TEST_SCORES, SCORE_BANDS


# ── Terminal colours ──────────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD  = "\033[1m"
RED   = "\033[91m"
YLW   = "\033[93m"
GRN   = "\033[92m"
BLU   = "\033[94m"
DIM   = "\033[2m"

STATUS_STYLE = {"PASS": GRN + "[PASS]", "WARN": YLW + "[WARN]", "FAIL": RED + "[FAIL]"}

def print_result(label: str, result: dict, indent=4):
    status = result.get("status", "FAIL")
    style = STATUS_STYLE.get(status, "? ????")
    msg = result.get("message", "")
    print(f"{' '*indent}{style}{RESET}  {BOLD}{label}{RESET}")
    print(f"{' '*(indent+7)}{DIM}{msg[:100]}{RESET}")


def compute_score(audit_results: dict) -> int:
    """
    Compute weighted overall score 0–100.
    Each group is scored independently then weighted.
    """
    group_scores = {}

    for group_key, tests in audit_results.items():
        total_pts = 0
        earned_pts = 0
        for test_id, result in tests.items():
            max_pts = TEST_SCORES.get(test_id, 5)
            total_pts += max_pts
            status = result.get("status", "FAIL")
            if status == "PASS":
                earned_pts += max_pts
            elif status == "WARN":
                earned_pts += max_pts * 0.5
        pct = (earned_pts / total_pts * 100) if total_pts else 100
        group_scores[group_key] = pct

    # Weighted average
    weight_map = {
        "technical": SCORE_WEIGHTS["technical"],
        "onpage":    SCORE_WEIGHTS["onpage"],
        "images":    SCORE_WEIGHTS["images"],
        "links":     SCORE_WEIGHTS["links"],
        "conversion":SCORE_WEIGHTS["conversion"],
    }
    total_weight = sum(weight_map.values())
    weighted_sum = sum(group_scores.get(k, 0) * w for k, w in weight_map.items())
    return round(weighted_sum / total_weight)


def run_audit(url: str) -> tuple[dict, int, str]:
    """Run all 19+ audit tests. Returns (results_dict, score, pdf_path)."""
    url = normalize_url(url)
    domain = get_domain(url)
    session = make_session()

    print(f"\n{BOLD}{BLU}{'='*60}{RESET}")
    print(f"{BOLD}  TEB Solutions — SEO Audit Engine{RESET}")
    print(f"{BOLD}{BLU}{'='*60}{RESET}")
    print(f"  Target: {BLU}{url}{RESET}")
    print(f"  Domain: {domain}")
    print(f"  Time:   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{BLU}{'-'*60}{RESET}\n")

    # ── Fetch homepage ────────────────────────────────────────────────────────
    print(f"{BLU}▶ Fetching homepage...{RESET}")
    page = fetch_page(url, session)
    if not page["ok"]:
        print(f"{RED}[FAILED] to fetch {url}: {page['error']}{RESET}")
        sys.exit(1)

    soup = page["soup"]
    html = page["html"]
    print(f"  {GRN}OK{RESET} — {page['status_code']} | {len(html):,} bytes\n")

    audit_results = {}

    # ── GROUP A: Technical ─────────────────────────────────────────────────────
    print(f"{BOLD}[A] Technical Foundation{RESET}")
    technical = {}
    technical["ssl"]       = audit_ssl(url, session)
    technical["sitemap"]   = audit_sitemap(url, session)
    technical["robots"]    = audit_robots(url, session)
    technical["canonical"] = audit_canonical(soup, url)
    technical["favicon"]   = audit_favicon(soup, url, session)
    technical["mobile"]    = audit_mobile(soup)

    for tid, res in technical.items():
        print_result(tid, res)
    audit_results["technical"] = technical
    print()

    # ── GROUP B: On-Page SEO ───────────────────────────────────────────────────
    print(f"{BOLD}[B] On-Page SEO{RESET}")
    onpage = {}
    onpage["page_title"]      = audit_title(soup)
    onpage["meta_desc"]       = audit_meta_description(soup)
    onpage["h1"]              = audit_h1(soup)
    onpage["og_tags"]         = audit_og_tags(soup, url)
    onpage["schema"]          = audit_schema(soup)

    for tid, res in onpage.items():
        print_result(tid, res)
    audit_results["onpage"] = onpage
    print()

    # ── GROUP C: Images ────────────────────────────────────────────────────────
    print(f"{BOLD}[C] Image & Media Optimisation{RESET}")
    images = {}
    images["alt_text"]    = audit_alt_text(soup)
    images["webp"]        = audit_webp(soup, html)
    images["lazy_load"]   = audit_lazy_loading(soup)

    for tid, res in images.items():
        print_result(tid, res)
    audit_results["images"] = images
    print()

    # ── GROUP D: Links & Mobile ────────────────────────────────────────────────
    print(f"{BOLD}[D] Links (this may take 30–60 seconds){RESET}")
    links = {}
    links["broken_links"] = audit_broken_links(soup, url, session)
    for tid, res in links.items():
        print_result(tid, res)
    audit_results["links"] = links
    print()

    # ── GROUP E: Conversion & Trust ────────────────────────────────────────────
    print(f"{BOLD}[E] Conversion & Trust Signals{RESET}")
    conversion = {}
    conversion["social"]    = audit_social_links(soup, url, session)
    conversion["contact"]   = audit_contact_links(soup)
    conversion["whatsapp"]  = audit_whatsapp(soup)
    conversion["trust"]     = audit_trust_pages(soup, url)

    for tid, res in conversion.items():
        print_result(tid, res)
    audit_results["conversion"] = conversion
    print()

    # ── GROUP F: Site-Wide Crawl ───────────────────────────────────────────────
    print(f"{BOLD}[F] Site-Wide Page Crawl (up to 100 pages){RESET}")
    print(f"    {DIM}Discovering pages via sitemap + internal links...{RESET}")

    crawled_pages = []
    page_audits   = []
    site_summary  = {}

    def _progress(page_url, done, total):
        bar_len = 30
        filled  = int(bar_len * done / total)
        bar     = "#" * filled + "-" * (bar_len - filled)
        short   = page_url.replace(url, "")[:45] or "/"
        print(f"\r    [{bar}] {done}/{total}  {DIM}{short:<45}{RESET}", end="", flush=True)

    try:
        crawled_pages = crawl_site(url, session, max_pages=100, progress_cb=_progress)
        print()   # newline after progress bar
        page_audits  = [audit_page_seo(p) for p in crawled_pages]
        site_summary = aggregate_site_issues(page_audits)

        total_p  = site_summary["total_pages"]
        fail_p   = site_summary["status_counts"]["FAIL"]
        warn_p   = site_summary["status_counts"]["WARN"]
        pass_p   = site_summary["status_counts"]["PASS"]
        cov      = site_summary["coverage_score"]

        status_sym = GRN+"[PASS]" if fail_p == 0 else (YLW+"[WARN]" if fail_p < total_p * 0.3 else RED+"[FAIL]")
        print(f"    {status_sym}{RESET}  Crawled {total_p} pages  |  "
              f"{GRN}{pass_p} clean{RESET}  {YLW}{warn_p} warn{RESET}  {RED}{fail_p} fail{RESET}")

        if site_summary["top_issues"]:
            print(f"    {DIM}Top issues across site:{RESET}")
            for check, count in site_summary["top_issues"][:5]:
                print(f"      {YLW}*{RESET} {check}: {count} page(s)")

    except Exception as e:
        print(f"\n    {YLW}[WARN] Crawl warning: {e}{RESET}")
        site_summary = {}
    print()

    # ── Score ──────────────────────────────────────────────────────────────────
    score = compute_score(audit_results)
    band_label = next((l for lo,hi,l,_ in SCORE_BANDS if lo <= score < hi), "")
    print(f"{BOLD}{BLU}{'='*60}{RESET}")
    print(f"{BOLD}  OVERALL SEO SCORE: {score}/100  {band_label}{RESET}")
    print(f"{BLU}{'='*60}{RESET}\n")

    # ── PDF ────────────────────────────────────────────────────────────────────
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    safe_domain = domain.replace(".", "_")

    # Cross-platform: save to <project_root>/reports/ (works on Windows & Linux)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir  = os.path.join(project_root, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    pdf_path = os.path.join(reports_dir, f"SEO_Audit_{safe_domain}_{ts}.pdf")

    print(f"{BLU}▶ Generating PDF report...{RESET}")
    build_pdf(url, audit_results, score, pdf_path,
              site_summary=site_summary, page_audits=page_audits)
    print(f"  {GRN}[PDF saved]:{RESET} {pdf_path}\n")

    return audit_results, score, pdf_path


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python main.py <URL>")
        print(f"Example: python main.py https://tebsolutions.in")
        sys.exit(1)
    
    target_url = sys.argv[1]
    results, score, pdf = run_audit(target_url)
    print(f"\n{GRN}Done! Report: {pdf}{RESET}\n")
