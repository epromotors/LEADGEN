# tests/test_page_architecture_classifier.py
# Comprehensive tests for evidence-based page architecture classifier:
#   1. single_page: section-only fragment navigation (e.g. /#services, #about)
#   2. single_page with standalone policy/legal documents retained in inventory
#   3. multi_page: navigation leads to distinct HTML routes (/about, /services)
#   4. hybrid: meaningful section anchors AND distinct content routes both exist
#   5. Section extraction: auditing in-page sections (id, heading, word count)
#   6. Tracking parameter and directory index alias normalization
#   7. Confidence rating, evidence collection, and limitation disclosures

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "auditor" / "auditor"))

import pytest
from bs4 import BeautifulSoup
from auditor.architecture import (
    classify_page_architecture,
    is_standalone_policy_page,
    normalize_clean_route,
    extract_in_page_sections,
)


def test_pure_single_page_architecture():
    """Test pure single-page site with only fragment navigation targeting sections."""
    html = """
    <!DOCTYPE html>
    <html>
      <head><title>Nexus Agency</title></head>
      <body>
        <header>
          <nav>
            <a href="#home">Home</a>
            <a href="#services">Services</a>
            <a href="#portfolio">Portfolio</a>
            <a href="#team">Our Team</a>
            <a href="#contact">Contact Us</a>
          </nav>
        </header>
        <main>
          <section id="home"><h1>Welcome to Nexus</h1><p>We are a specialized agency helping brands scale with cutting edge digital technology.</p></section>
          <section id="services"><h2>Our Core Services</h2><p>Comprehensive growth architecture, full-funnel customer acquisition, and enterprise consulting.</p></section>
          <section id="portfolio"><h2>Featured Case Studies</h2><p>Proven client engagements delivering measurable revenue acceleration and verified ROI.</p></section>
          <section id="team"><h2>Leadership Team</h2><p>Experienced industry operators and dedicated domain specialists based in Dubai and London.</p></section>
          <section id="contact"><h2>Get in Touch</h2><p>Schedule an introductory briefing session with our senior advisory team today.</p></section>
        </main>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    arch = classify_page_architecture(soup, "https://nexus.example")

    assert arch["architecture"] == "single_page"
    assert arch["confidence"] == "high"
    assert arch["section_count"] == 5
    assert len(arch["primary_navigation"]["fragment_nav_links"]) == 5
    assert len(arch["distinct_content_pages"]) == 0
    assert arch["distinct_document_count"] == 1
    # Check section details
    section_ids = [s["id"] for s in arch["sections"]]
    assert section_ids == ["home", "services", "portfolio", "team", "contact"]
    assert any("Our Core Services" in s["heading"] for s in arch["sections"])


def test_single_page_retaining_standalone_policies():
    """
    Test single-page site that retains legitimate privacy and cookie policy pages
    in its inventory without falsely classifying the site as multi-page.
    """
    html = """
    <!DOCTYPE html>
    <html>
      <head><title>Channel Nexus</title></head>
      <body>
        <nav>
          <a href="#home">Home</a>
          <a href="#pillars">Pillars</a>
          <a href="#portfolio">Portfolio</a>
          <a href="#about">About</a>
          <a href="#contact">Contact</a>
        </nav>
        <section id="home"><h1>Two Markets One Bridge</h1><p>Niche technology advisory and accelerator.</p></section>
        <section id="pillars"><h2>Pillars</h2><p>Five services, one accountable team across GCC and India.</p></section>
        <section id="portfolio"><h2>Portfolio</h2><p>Enterprise cybersecurity and data orchestration vendors.</p></section>
        <section id="about"><h2>About</h2><p>Bridge between global founders and regional enterprise buyers.</p></section>
        <section id="contact"><h2>Contact</h2><p>Connect with our partner network.</p></section>
        <footer>
          <a href="privacy-policy.html">Privacy Policy</a>
          <a href="cookie-policy.html">Cookie Policy</a>
        </footer>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    crawled = [
        {"url": "https://channelnexus.me/", "final_url": "https://channelnexus.me/"},
        {"url": "https://channelnexus.me/privacy-policy.html", "final_url": "https://channelnexus.me/privacy-policy.html"},
        {"url": "https://channelnexus.me/cookie-policy.html", "final_url": "https://channelnexus.me/cookie-policy.html"},
    ]
    arch = classify_page_architecture(soup, "https://channelnexus.me", crawled_pages=crawled)

    assert arch["architecture"] == "single_page"
    assert arch["confidence"] == "high"
    assert arch["section_count"] == 5
    assert arch["distinct_document_count"] == 3
    assert len(arch["standalone_policy_pages"]) == 2
    assert any("privacy-policy" in p for p in arch["standalone_policy_pages"])
    assert any("cookie-policy" in p for p in arch["standalone_policy_pages"])
    # Evidence must explicitly acknowledge retained policies
    assert any("standalone policy document" in ev for ev in arch["evidence"])


def test_pure_multi_page_architecture():
    """Test classic multi-page site with navigation leading to distinct routes."""
    html = """
    <!DOCTYPE html>
    <html>
      <head><title>Enterprise SaaS</title></head>
      <body>
        <header>
          <nav>
            <a href="/">Home</a>
            <a href="/solutions">Solutions</a>
            <a href="/pricing">Pricing</a>
            <a href="/about-us">About Us</a>
            <a href="/blog">Blog</a>
            <a href="/contact">Contact</a>
          </nav>
        </header>
        <main>
          <h1>Enterprise Cloud Management</h1>
          <p>Automate your hybrid infrastructure with unified policy enforcement.</p>
        </main>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    crawled = [
        {"url": "https://saas.example/", "final_url": "https://saas.example/"},
        {"url": "https://saas.example/solutions", "final_url": "https://saas.example/solutions"},
        {"url": "https://saas.example/pricing", "final_url": "https://saas.example/pricing"},
        {"url": "https://saas.example/about-us", "final_url": "https://saas.example/about-us"},
        {"url": "https://saas.example/blog", "final_url": "https://saas.example/blog"},
        {"url": "https://saas.example/contact", "final_url": "https://saas.example/contact"},
    ]
    arch = classify_page_architecture(soup, "https://saas.example", crawled_pages=crawled)

    assert arch["architecture"] == "multi_page"
    assert arch["confidence"] == "high"
    assert len(arch["distinct_content_pages"]) >= 5
    assert arch["distinct_document_count"] >= 6
    assert arch["primary_navigation"]["fragment_ratio"] == 0.0


def test_hybrid_architecture():
    """
    Test hybrid site containing both meaningful section fragment anchors
    AND distinct content routes in its primary navigation structure.
    """
    html = """
    <!DOCTYPE html>
    <html>
      <head><title>Hybrid Product</title></head>
      <body>
        <header>
          <nav>
            <a href="#features">Key Features</a>
            <a href="#integrations">Integrations</a>
            <a href="#pricing">Pricing</a>
            <a href="/case-studies">Case Studies</a>
            <a href="/resources/guides">Guides</a>
            <a href="/company">Company</a>
          </nav>
        </header>
        <main>
          <section id="features"><h2>Features</h2><p>Intelligent workflow automation and real-time data synchronisation.</p></section>
          <section id="integrations"><h2>Integrations</h2><p>Connect with Salesforce, HubSpot, Stripe and over 50 native tools.</p></section>
          <section id="pricing"><h2>Pricing</h2><p>Transparent tiered subscription plans for teams of all sizes.</p></section>
        </main>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    crawled = [
        {"url": "https://hybrid.example/", "final_url": "https://hybrid.example/"},
        {"url": "https://hybrid.example/case-studies", "final_url": "https://hybrid.example/case-studies"},
        {"url": "https://hybrid.example/resources/guides", "final_url": "https://hybrid.example/resources/guides"},
        {"url": "https://hybrid.example/company", "final_url": "https://hybrid.example/company"},
    ]
    arch = classify_page_architecture(soup, "https://hybrid.example", crawled_pages=crawled)

    assert arch["architecture"] == "hybrid"
    assert arch["confidence"] == "high"
    assert arch["section_count"] == 3
    assert len(arch["primary_navigation"]["fragment_nav_links"]) == 3
    assert len(arch["distinct_content_pages"]) == 3
    assert any("Meaningful in-page section anchors" in ev for ev in arch["evidence"])


def test_directory_index_and_tracking_normalization():
    """
    Verify that tracking parameter variants (?utm_source=...) and directory
    aliases (/index.html) are normalized and NOT counted as separate content routes.
    """
    clean_index = normalize_clean_route("https://example.com/index.html", "https://example.com")
    assert clean_index == "https://example.com/"

    clean_tracking = normalize_clean_route("https://example.com/services?utm_source=google&fbclid=xyz", "https://example.com")
    assert clean_tracking == "https://example.com/services"

    html = """
    <html>
      <head><title>Tracking Test</title></head>
      <body>
        <nav>
          <a href="/#features">Features</a>
          <a href="/index.html#features">Features Duplicate</a>
          <a href="/?utm_source=newsletter#features">Features Tracking</a>
          <a href="#pricing">Pricing</a>
        </nav>
        <section id="features"><h2>Features</h2><p>Detailed capabilities.</p></section>
        <section id="pricing"><h2>Pricing</h2><p>Pricing table.</p></section>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    arch = classify_page_architecture(soup, "https://example.com")

    # Tracking & alias variants must be collapsed
    assert arch["architecture"] == "single_page"
    assert len(arch["primary_navigation"]["fragment_nav_links"]) == 2
    assert arch["primary_navigation"]["fragment_nav_links"] == ["#features", "#pricing"]
    assert len(arch["distinct_content_pages"]) == 0


def test_policy_path_detection():
    """Verify is_standalone_policy_page accurately identifies legal/policy documents."""
    assert is_standalone_policy_page("/privacy-policy.html") is True
    assert is_standalone_policy_page("/cookie-policy.html") is True
    assert is_standalone_policy_page("/terms-of-service") is True
    assert is_standalone_policy_page("/legal/disclaimer") is True
    assert is_standalone_policy_page("/gdpr-compliance") is True

    # Real content routes must not be classified as policy pages
    assert is_standalone_policy_page("/services/seo-audit") is False
    assert is_standalone_policy_page("/about-us") is False
    assert is_standalone_policy_page("/case-studies") is False
    assert is_standalone_policy_page("/pricing") is False
