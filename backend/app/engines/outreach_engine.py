"""
outreach_engine.py — Branded HTML Email Outreach Engine

Sends a professional, personalised HTML email with:
  - TEB Solutions / Tattavit branding + logo
  - Personalised audit findings per lead
  - Before/After metrics table
  - CTA button
  - 60-90 second randomised delay between sends
  - Rotating SMTP sender accounts
"""

import asyncio
import random
import smtplib
import logging
import uuid
import re
from html import escape
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Lead, Audit, AuditStatus, Campaign, CampaignEmailLog, CampaignStatus, ActivityLog, LeadStatus
from app.config import settings
from app.utils.spintax import process_template

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────
MIN_DELAY_SECONDS = 60     # 60 seconds (min)
MAX_DELAY_SECONDS = 90     # 90 seconds (max) — random between 60–90s


LOGO_URL = "https://tebsolutions.in/wp-content/uploads/elementor/thumbs/Tattavit-Blue-PNG-r8gipfogfjoxbz71axei1wro8c57p2i5omo93ilce8.png"

# Subject lines: curiosity-gap for website design/redesign, no spam triggers (no "free", no ALL CAPS, <50 chars)
DEFAULT_SUBJECT_TEMPLATE = (
    "{"
    "{domain} — noticed this on mobile|"
    "first impression of {domain}'s homepage|"
    "{domain} — modern redesign idea|"
    "is {domain} losing mobile visitors?|"
    "a design thought for {domain}|"
    "spotted this on {domain}"
    "}"
)
# Use subdued production subjects for first-contact plain-text outreach.
DEFAULT_SUBJECT_TEMPLATE = "{a note about {domain}|an idea for {domain}|website observation: {domain}|regarding {domain}}"
NO_SITE_SUBJECT_TEMPLATE = (
    "{"
    "{business_name} — couldn't find your website|"
    "{business_name} — is your website offline?|"
    "looked for {business_name} online today"
    "}"
)


# ─── Shared style tokens ───────────────────────────────────────────────────────
_PRIMARY    = "#2563eb"   # single brand blue — CTA + links only
_PRIMARY_D  = "#1e40af"   # dark blue (header bar)
_SUCCESS    = "#16a34a"   # green (offer card accent)
_DANGER     = "#b91c1c"   # red (errors)
_ISSUE_BG   = "#fff7ed"   # warm orange tint — issue card
_ISSUE_BORDER = "#f97316" # orange border
_IMPACT_BG  = "#eff6ff"   # light blue — why it matters card
_IMPACT_BORDER = "#2563eb"
_OFFER_BG   = "#f0fdf4"   # pale green — what you get card
_OFFER_BORDER  = "#16a34a"
_CARD_BG    = "#f8fafc"
_BORDER     = "#e2e8f0"
_TEXT_MAIN  = "#111827"   # near-black primary text
_TEXT_BODY  = "#4b5563"   # secondary text
_TEXT_MUTE  = "#6b7280"   # muted
_TEXT_XMUTE = "#9ca3af"   # very muted


def _email_wrapper(inner_html: str) -> str:
    """Wrap email sections in the shared outer table + header + footer."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta http-equiv="X-UA-Compatible" content="IE=edge"/>
</head>
<body style="margin:0;padding:0;background:#eef2f7;font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:{_TEXT_MAIN};">

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:32px 0;">
<tr><td align="center">

<!-- Card -->
<table width="620" cellpadding="0" cellspacing="0"
       style="background:#ffffff;border-radius:16px;overflow:hidden;
              box-shadow:0 4px 32px rgba(0,0,0,0.10);border:1px solid {_BORDER};">

  <!-- ── LOGO HEADER (navy, full-width) ── -->
  <tr>
    <td style="background-color:#0d1b2a;
               border-bottom:2px solid #1e3a5f;
               margin:0;padding:0;">
      <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="center" valign="middle"
              style="padding:26px 24px;">
            <img src="{LOGO_URL}" alt="TEB Solutions"
                 width="180"
                 style="display:block;max-width:180px;width:180px;
                        height:auto;margin:0 auto;border:0;
                        outline:none;text-decoration:none;"/>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  {inner_html}

  <!-- ── Divider ── -->
  <tr><td style="height:1px;background:{_BORDER};font-size:0;line-height:0;"></td></tr>

  <!-- ── Footer ── -->
  <tr>
    <td style="background:#f1f5f9;padding:20px 36px;">
      <p style="font-size:12px;color:{_TEXT_MUTE};margin:0 0 6px;text-align:center;line-height:1.6;">
        Ashish &mdash; TEB Solutions &middot; tebsolutions.in
      </p>
      <p style="font-size:11px;color:{_TEXT_XMUTE};text-align:center;margin:8px 0 0;line-height:1.7;">
        Not interested? Reply <strong>STOP</strong> and I'll remove you immediately.
      </p>
    </td>
  </tr>

</table>
<!-- /Card -->

</td></tr>
</table>
<!-- /Outer wrapper -->

</body>
</html>"""


def _section(content: str, pt: int = 28, pb: int = 20, px: int = 36) -> str:
    return f'<tr><td style="padding:{pt}px {px}px {pb}px;">{content}</td></tr>'


def _pill(text: str, color: str, bg: str) -> str:
    return (f'<span style="display:inline-block;background:{bg};color:{color};'
            f'font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;'
            f'padding:4px 12px;border-radius:20px;">{text}</span>')


def _cta_button(href: str, label: str, bg: str = None) -> str:
    bg = bg or _PRIMARY
    return (f'<a href="{href}" '
            f'style="display:inline-block;background:{bg};color:#ffffff;font-weight:700;'
            f'font-size:15px;padding:15px 36px;border-radius:10px;text-decoration:none;'
            f'letter-spacing:0.3px;box-shadow:0 4px 14px rgba(29,78,216,0.35);">'
            f'{label}</a>')


def _info_box(title: str, body: str, border: str, bg: str) -> str:
    return f"""<div style="background:{bg};border-left:4px solid {border};
                          border-radius:0 10px 10px 0;padding:18px 20px;margin-top:4px;">
  <p style="font-weight:700;font-size:13px;color:{_TEXT_MAIN};margin:0 0 10px;">{title}</p>
  {body}
</div>"""





def _card(body: str, bg: str, border_color: str, heading: str = "") -> str:

    """A left-bordered card section, used for issue/impact/offer blocks."""

    head = (f'<p style="font-weight:700;font-size:15px;color:{_TEXT_MAIN};margin:0 0 12px;">{heading}</p>'

            if heading else "")

    return (f'<div style="background:{bg};border-left:4px solid {border_color};'

            f'border-radius:0 6px 6px 0;padding:20px 22px;">'

            f'{head}{body}</div>')





def _contact_row() -> str:
    """Minimal contact block — plain text only to avoid Promotions classification."""
    return """<table cellpadding="0" cellspacing="0" style="font-size:13px;color:#475569;margin-top:4px;">
      <tr><td style="padding:3px 0;width:80px;">Phone:</td>
          <td style="padding:3px 0;">+91-86300-03882</td></tr>
      <tr><td style="padding:3px 0;">Email:</td>
          <td style="padding:3px 0;">info@tebsolutions.in</td></tr>
      <tr><td style="padding:3px 0;">Website:</td>
          <td style="padding:3px 0;"><a href="https://tebsolutions.in" style="color:#1d4ed8;text-decoration:none;">tebsolutions.in</a></td></tr>
    </table>"""


# ─── Email Validation Helper ──────────────────────────────────────────────────
def is_valid_email(email: str) -> bool:
    if not email:
        return False
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 254


# ─── "No Website / Parked" Email Template ────────────────────────────────────

def build_no_site_email(lead, site_type_str: str) -> str:
    """
    Website design service proposal email for leads with no live website.
    Email 1 goal: earn a YES reply — not close a sale.

    ── CRITICAL DESIGN RULES ──────────────────────────────────────────────────
    • NO audit report, NO PDF, NO attachment of any kind (pdf_attachment_path
      is intentionally NOT passed when this template is used — see send loop).
    • NO pricing, NO service price list (Guardrail #15 — deferred to Email 2).
    • This is a web DESIGN PITCH, not an SEO audit delivery email.
    • Audit findings, score bars, issue bullets = ONLY in build_html_email()
      for REAL-site leads. Never add audit content here.
    ── ───────────────────────────────────────────────────────────────────────
    """
    name    = lead.business_name
    website = lead.website or ""

    reason_map = {
        "parked":      "appears to be parked or listed for sale",
        "demo":        "is showing a coming-soon / placeholder page",
        "not_found":   "is returning a 404 error",
        "unreachable": "appears to be offline",
    }
    reason = reason_map.get(site_type_str, "doesn't appear to be live")

    plain_website = website.replace("https://","").replace("http://","").rstrip("/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Quick note for {name}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;">

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#f3f4f6;padding:32px 12px;">
    <tr><td align="center">

      <!-- Card (max 580px, fluid on mobile) -->
      <table cellpadding="0" cellspacing="0" border="0"
             style="width:100%;max-width:560px;background:#ffffff;
                    border-radius:10px;border:1px solid #e5e7eb;
                    font-family:Arial,Helvetica,sans-serif;">

        <!-- ── Logo strip ── -->
        <tr>
          <td style="padding:20px 32px 18px;border-bottom:1px solid #f3f4f6;">
            <img src="{LOGO_URL}" alt="TEB Solutions" height="32"
                 style="display:block;height:32px;width:auto;">
          </td>
        </tr>

        <!-- ── Body ── -->
        <tr>
          <td style="padding:28px 32px 8px;
                     font-size:15px;line-height:26px;color:#374151;">

            <p style="margin:0 0 16px;">Hi,</p>

            <p style="margin:0 0 16px;">
              I came across <strong>{name}</strong> while researching businesses
              in your industry — but your website
              (<a href="{website}" style="color:#2563eb;">{plain_website}</a>)
              {reason}.
            </p>

            <p style="margin:0 0 16px;">
              That means when potential customers search for you online,
              they either <strong>find nothing</strong> or land on a
              competitor's page instead.
            </p>

            <p style="margin:0 0 24px;">
              We help businesses like yours get a professional, lead-ready
              website built quickly. I'd love to send you a short note on
              what that could look like for {name} — completely no pressure.
            </p>

            <!-- CTA button -->
            <table cellpadding="0" cellspacing="0" border="0"
                   style="margin-bottom:16px;">
              <tr>
                <td style="background:#2563eb;border-radius:6px;">
                  <a href="mailto:info@tebsolutions.in
?subject=Yes%20%E2%80%94%20Tell%20me%20more%20%28{name}%29"
                     style="display:inline-block;padding:13px 30px;
                            font-family:Arial,sans-serif;
                            font-size:15px;font-weight:bold;
                            color:#ffffff;text-decoration:none;
                            white-space:nowrap;">
                    Reply YES &mdash; tell me more
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 28px;font-size:13px;color:#6b7280;">
              Or just reply to this email &mdash; I'll follow up within a few hours.
            </p>

            <p style="margin:0 0 4px;">Best,</p>
            <p style="margin:0;font-weight:bold;color:#111827;">The TEB Solutions Team</p>
            <p style="margin:4px 0 0;font-size:13px;color:#6b7280;">
              <a href="https://tebsolutions.in"
                 style="color:#2563eb;text-decoration:none;">tebsolutions.in</a>
              &nbsp;&nbsp;|&nbsp;&nbsp;
              <a href="mailto:info@tebsolutions.in"
                 style="color:#2563eb;text-decoration:none;">info@tebsolutions.in</a>
            </p>

          </td>
        </tr>

        <!-- ── Footer / Unsubscribe ── -->
        <tr>
          <td style="padding:18px 32px 22px;
                     border-top:1px solid #f3f4f6;
                     text-align:center;">
            <p style="margin:0;font-size:11px;line-height:19px;color:#9ca3af;">
              You received this because <strong>{plain_website}</strong> was
              included in our outreach list.<br>
              To unsubscribe instantly, reply with the word
              <strong style="color:#6b7280;">STOP</strong>
              &mdash; you will never hear from us again.<br>
              &copy; 2026 TEB Solutions &nbsp;&middot;&nbsp;
              <a href="https://tebsolutions.in"
                 style="color:#9ca3af;text-decoration:underline;">tebsolutions.in</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>

</body>
</html>"""



# ─── Audit Issue Bullets Builder ──────────────────────────────────────────────

def _build_audit_bullets(audit: Optional[object]) -> str:
    """Return HTML <li> items for each failing SEO factor — helpful tone, concise."""
    if not audit:
        return ""

    items = []
    if not getattr(audit, 'ssl_valid', True):
        items.append(("🔒", "Missing SSL", 'Your site is marked as "Not Secure" by Google.'))
    if not getattr(audit, 'has_sitemap', True):
        items.append(("🗺️", "No XML Sitemap", "Search engines cannot properly index your pages."))
    if getattr(audit, 'has_robots', True) is False:
        items.append(("🤖", "No robots.txt", "Crawlers don't know which pages to index."))
    
    broken_links = getattr(audit, 'broken_links_count', 0)
    if broken_links and broken_links > 0:
        items.append(("🔗", f"{broken_links} Broken Links", "Dead links creating a poor user experience."))
    
    if getattr(audit, 'missing_h1', False):
        items.append(("📝", "Missing H1 Tag", "Reduces SEO visibility and crawl effectiveness."))
    
    missing_alt = getattr(audit, 'missing_alt_count', 0)
    if missing_alt and missing_alt > 0:
        items.append(("🖼️", f"{missing_alt} Images Missing Alt", "Missed ranking opportunities in Google Image Search."))
    
    if getattr(audit, 'uses_webp', True) is False:
        items.append(("⚡", "Images not WebP", "Converting images improves page speed score."))
    
    if getattr(audit, 'has_json_ld', True) is False:
        items.append(("🧩", "No Schema Markup", "Miss out on rich results in search."))
    
    if getattr(audit, 'mobile_friendly', True) is False:
        items.append(("📱", "Not Mobile Responsive", "Broken mobile layout means lost enquiries."))

    missing_social = getattr(audit, 'missing_social', [])
    if missing_social:
        platforms = ", ".join(p.capitalize() for p in missing_social)
        items.append(("🌐", f"Missing Social ({platforms})", "Weaker credibility signal for visitors and Google."))
    
    if not items:
        items.append(("✅", "Site is Technically Solid", "Ready for content and conversion improvements."))

    if getattr(audit, 'has_cta', True) is False:
        items.append(("🎯", "Missing Call-to-Action", "Visitors don't know what step to take next."))
    if getattr(audit, 'has_hero_headline', True) is False:
        items.append(("📢", "No Clear Value Prop", "Visitors don't instantly know what you do."))
    if getattr(audit, 'contrast_ok', True) is False:
        items.append(("👁️", "Low Contrast Text", "Text is hard to read, lowering engagement."))

    # Limit to 6 bullets max for scannability
    items = items[:6]
    
    html = ""
    for i, (icon, title, desc) in enumerate(items):
        padding_bottom = "20px" if i == len(items) - 1 else "8px"
        html += f"""                      <!-- Issue -->
                      <tr><td style="padding:0 24px {padding_bottom};">
                        <table width="100%" cellpadding="0" cellspacing="0" style="background:rgba(239,68,68,0.05);border:1px solid #fee2e2;border-radius:8px;">
                          <tr>
                            <td width="44" align="center" style="padding:14px 6px 14px 14px;font-size:20px;">{icon}</td>
                            <td style="padding:14px 16px 14px 6px;">
                              <p style="margin:0;font-size:13.5px;font-weight:700;color:#991b1b;">{title}</p>
                              <p style="margin:3px 0 0;font-size:12.5px;color:#b91c1c;opacity:0.85;">{desc}</p>
                            </td>
                          </tr>
                        </table>
                      </td></tr>
"""
    return html


def _build_score_bar(audit: Optional[object]) -> str:
    """Generate a visual SEO score bar."""
    if not audit:
        return ""
    passing = sum([
        bool(audit.ssl_valid),
        bool(audit.has_sitemap),
        bool(audit.has_robots),
        (audit.broken_links_count or 0) == 0,
        not bool(audit.missing_h1),
        (audit.missing_alt_count or 0) == 0,
        bool(audit.uses_webp),
        bool(audit.has_json_ld),
        bool(audit.mobile_friendly),
        len(audit.missing_social or []) == 0,
    ])
    score = passing  # out of 10
    pct   = score * 10
    if score <= 3:
        bar_color = "#b91c1c"
        score_color = "#b91c1c"
    elif score <= 6:
        bar_color = "#d97706"
        score_color = "#92400e"
    else:
        bar_color = "#15803d"
        score_color = "#15803d"

    return f"""
<table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:4px;">
  <tr>
    <td style="font-size:13px;color:#475569;padding-bottom:7px;">
      SEO health score: <strong style="color:{score_color};font-size:15px;">{score}/10</strong>
      <span style="color:{_TEXT_XMUTE};font-size:12px;"> &nbsp;({passing} of 10 factors passing)</span>
    </td>
  </tr>
  <tr>
    <td>
      <div style="background:#e2e8f0;border-radius:999px;height:10px;width:100%;overflow:hidden;">
        <div style="background:{bar_color};border-radius:999px;height:10px;width:{pct}%;"></div>
      </div>
    </td>
  </tr>
</table>"""


def _build_quick_checks(audit: Optional[object]) -> str:
    """Build the 2x2 quick checks grid with actual results."""
    def check(passed: bool, label: str, ok_text: str, fail_text: str) -> str:
        icon   = "✅" if passed else "❌"
        text   = ok_text if passed else fail_text
        color  = "#15803d" if passed else "#b91c1c"
        bg     = "#f0fdf4" if passed else "#fef2f2"
        border = "#bbf7d0" if passed else "#fecaca"
        return f"""
        <td style="width:50%;padding:6px;vertical-align:top;">
          <div style="background:{bg};border:1px solid {border};border-radius:10px;padding:14px;">
            <p style="font-weight:700;color:{_TEXT_MAIN};margin:0 0 4px;font-size:13px;">{icon} {label}</p>
            <p style="color:{color};font-size:12px;margin:0;line-height:1.5;">{text}</p>
          </div>
        </td>"""

    if not audit:
        ssl = h1 = mobile = schema = False
    else:
        ssl    = bool(audit.ssl_valid)
        h1     = not bool(audit.missing_h1)
        mobile = bool(audit.mobile_friendly)
        schema = bool(audit.has_json_ld)

    r1 = f"""<tr>
      {check(ssl,    "SSL / Security",      "SSL secure — visitors see the padlock.",        "No SSL — 'Not Secure' warning drives visitors away.")}
      {check(h1,     "Page Structure",      "H1 heading found — page topic is clear.",       "Missing H1 — Google cannot determine your page topic.")}
    </tr>"""
    r2 = f"""<tr>
      {check(mobile, "Mobile Responsive",   "Mobile-optimised and responsive.",               "Not mobile responsive — broken on phones.")}
      {check(schema, "Rich Results Ready",  "JSON-LD Schema found — eligible for stars/FAQs.", "No Schema markup — missing Rich Results in Google.")}
    </tr>"""
    return r1 + r2

# ─── Cost-Impact Bullets Builder ────────────────────────────────────────────────

def _build_cost_bullets(audit) -> str:
    """Build dynamic 'What these issues are costing you' red-arrow bullets based on audit data."""
    bullets = []

    if audit:
        if not getattr(audit, 'ssl_valid', True):
            bullets.append(("Security warning scares off visitors", "Your site shows 'Not Secure' — new visitors judge credibility in <strong>under 3 seconds</strong> and leave immediately."))
        if not getattr(audit, 'mobile_friendly', True):
            bullets.append(("Broken mobile experience wastes every rupee on ads", "A slow, non-responsive site increases bounce rate and means your ad budget is being wasted on visitors who bounce."))
        if not getattr(audit, 'has_sitemap', True) or not getattr(audit, 'has_robots', True):
            bullets.append(("Google cannot properly rank your pages", "Without a sitemap or robots.txt, search engines miss pages entirely — you're invisible to people actively searching for you."))
        broken = getattr(audit, 'broken_links_count', 0) or 0
        if broken > 0:
            bullets.append((f"{broken} broken link{'s' if broken > 1 else ''} = lost leads every single day", "Confusing navigation or broken links means visitors can't find your contact details or WhatsApp button — every broken link is a lost enquiry."))
        if not getattr(audit, 'has_json_ld', True):
            bullets.append(("Missing from Google's rich results", "No Schema markup means you don't appear with star ratings, FAQs, or business info boxes — your competitors get those spots instead."))
        missing_social = getattr(audit, 'missing_social', []) or []
        if missing_social:
            bullets.append(("Weak social credibility hurts conversions", "Visitors check your social presence before calling. Missing profiles signal an unmaintained business — a <strong>security risk</strong> and a trust killer."))

    # Fallback if everything passes
    if not bullets:
        bullets = [
            ("New visitors judge credibility in under 3 seconds", "Based on design, speed and clarity — first impressions are everything."),
            ("A slow site wastes every rupee you spend on ads", "Every bounce from a slow page is paid-for traffic that never converts."),
            ("An unmaintained site is a security risk", "One hacked plugin can take you offline and destroy your Google ranking overnight."),
        ]

    bullets = bullets[:4]  # max 4 bullets
    rows = ""
    for i, (title, desc) in enumerate(bullets):
        border_top = "border-top:1px solid #fee2e2;" if i > 0 else ""
        rows += f"""                      <tr>
                        <td style="{border_top}padding:14px 0;">
                          <table cellpadding="0" cellspacing="0" border="0" width="100%">
                            <tr>
                              <td width="22" valign="top" style="padding-top:2px;">
                                <span style="font-size:15px;font-weight:800;color:#dc2626;">&#8594;</span>
                              </td>
                              <td style="font-size:13.5px;line-height:22px;color:#374151;">
                                <strong style="color:#111827;">{title}</strong><br>
                                <span style="color:#b91c1c;font-size:13px;">{desc}</span>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
"""
    return rows


def _build_how_we_help(name: str) -> str:
    """Build the 'How TEB Solutions can help {name}' numbered service list."""
    services = [
        ("Website redesign &amp; UX improvement",
         "We modernise your site without losing your brand &mdash; faster, cleaner, more leads."),
        ("Technical SEO fixes",
         "SSL, sitemap, robots.txt, Schema markup, mobile viewport &mdash; all sorted correctly."),
        ("New website design",
         "Custom, mobile-first from scratch if needed &mdash; built for conversions, not just looks."),
        ("Ongoing website management",
         "Updates, backups, security, content edits &mdash; so you never worry about your site again."),
    ]
    rows = ""
    for i, (svc_title, svc_desc) in enumerate(services):
        border_top = "border-top:1px solid #bbf7d0;" if i > 0 else ""
        rows += f"""                      <tr>
                        <td style="{border_top}padding:14px 0;">
                          <p style="margin:0 0 3px;font-size:14px;font-weight:700;color:#14532d;">{i+1}. {svc_title}</p>
                          <p style="margin:0;font-size:13px;line-height:21px;color:#166534;">{svc_desc}</p>
                        </td>
                      </tr>
"""
    return rows


# ─── HTML Email Builder (SEO Audit) ───────────────────────────────────────────

# ─── Hook Selector ────────────────────────────────────────────────────────────

def _pick_hook(audit) -> str:
    """
    Return the single most impactful audit finding as a human sentence.
    Used as the email opening hook — one clear, specific problem only.
    Priority order matches deliverability impact.
    """
    if not audit:
        return "there are several technical issues affecting your search visibility."

    if not getattr(audit, 'ssl_valid', True):
        return (
            "your site shows a <strong>\"Not Secure\"</strong> warning in every browser. "
            "Visitors see this the moment they land — and most leave immediately."
        )
    if not getattr(audit, 'mobile_friendly', True):
        return (
            "your website <strong>appears broken on mobile devices</strong>. "
            "Over 60% of search traffic is mobile — a broken layout loses those visitors before they read a word."
        )
    broken = getattr(audit, 'broken_links_count', 0) or 0
    if broken > 0:
        return (
            f"there are <strong>{broken} broken link{'s' if broken > 1 else ''}</strong> on your site. "
            "Broken links frustrate visitors and are a direct negative ranking signal for Google."
        )
    if not getattr(audit, 'has_sitemap', True):
        return (
            "your site has <strong>no XML sitemap</strong>. "
            "Without one, search engines can miss pages entirely — pages that could be bringing you traffic."
        )
    if getattr(audit, 'missing_h1', False):
        return (
            "your site is <strong>missing a primary H1 heading</strong>. "
            "Google uses this to understand what your page is about — without it, your ranking potential drops significantly."
        )
    if not getattr(audit, 'has_json_ld', True):
        return (
            "your site has <strong>no Schema markup</strong>. "
            "This means you won't appear in Google's rich results (star ratings, FAQs, business panels) — spots your competitors may already hold."
        )
    missing_alt = getattr(audit, 'missing_alt_count', 0) or 0
    if missing_alt > 0:
        return (
            f"<strong>{missing_alt} image{'s' if missing_alt > 1 else ''}</strong> on your site "
            "have no alt text — a missed ranking opportunity in Google Image Search and an accessibility fail."
        )
    if not getattr(audit, 'uses_webp', True):
        return (
            "your images aren't in modern WebP format. "
            "This slows page load time — "
            "<strong>a 1-second delay reduces conversions by up to 7%</strong>."
        )
    # Fallback
    return (
        "while your site passes the big technical checks, "
        "there are a few smaller optimisations that could improve both rankings and conversion."
    )


def _score_from_audit(audit) -> int:
    """Return the 0–10 SEO health score from the audit object."""
    if not audit:
        return 0
    passing = sum([
        bool(getattr(audit, 'ssl_valid', False)),
        bool(getattr(audit, 'has_sitemap', False)),
        bool(getattr(audit, 'has_robots', False)),
        (getattr(audit, 'broken_links_count', 1) or 1) == 0,
        not bool(getattr(audit, 'missing_h1', True)),
        (getattr(audit, 'missing_alt_count', 1) or 1) == 0,
        bool(getattr(audit, 'uses_webp', False)),
        bool(getattr(audit, 'has_json_ld', False)),
        bool(getattr(audit, 'mobile_friendly', False)),
        len(getattr(audit, 'missing_social', None) or []) == 0,
    ])
    return passing


# ─── HTML Email Builder — Website Design & Redesign Proposal (Email 1) ──────────

def build_html_email(lead, audit=None) -> str:
    """
    Website design & redesign proposal Email 1 for leads with a website.
    Email 1 goal: earn a YES reply for a free review.
    NO PDF, NO audit report, NO attachment.
    """
    name    = lead.business_name or "there"
    website = lead.website or ""
    domain  = (
        website.replace("https://", "").replace("http://", "")
               .replace("www.", "").rstrip("/").split("/")[0]
    ) or "your website"

    try:
        accounts = settings.get_smtp_accounts()
        your_name = accounts[0].get("sender_name", "Ashish") if accounts else "Ashish"
    except Exception:
        your_name = "Ashish"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>Website review &amp; observations for {domain}</title>
  <style>
    body {{ margin:0; padding:0; background-color:#eef2f7;
           -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table {{ border-spacing:0; border-collapse:collapse; }}
    img   {{ border:0; display:block; line-height:0; max-width:100%; height:auto; }}
    a     {{ color:#2563eb; }}

    /* ── Responsive ── */
    @media only screen and (max-width:620px) {{
      .card     {{ width:100% !important; border-radius:0 !important; }}
      .px36     {{ padding-left:20px !important; padding-right:20px !important; }}
      .h1       {{ font-size:20px !important; line-height:1.35 !important; }}
      .two-col td    {{ display:block !important; width:100% !important;
                       padding:4px 0 !important; }}
      .cta-btn  {{ width:100% !important; text-align:center !important;
                  box-sizing:border-box !important; }}
    }}
  </style>
</head>
<body>

<!-- OUTER WRAPPER -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color:#eef2f7; padding:32px 12px;">
<tr><td align="center">

<!-- CARD -->
<table role="presentation" class="card"
       style="width:100%; max-width:600px; background:#ffffff;
              border-radius:14px; overflow:hidden;
              border:1px solid #e2e8f0;
              font-family:'Segoe UI',Arial,Helvetica,sans-serif;
              color:#111827;">

  <!-- HEADER: navy, logo + tagline — Guardrail #22 -->
  <tr>
    <td style="background-color:#0d1b2a;
               border-bottom:2px solid #1e3a5f;
               padding:18px 24px;">
      <table role="presentation" width="100%">
        <tr>
          <td align="left" valign="middle">
            <img src="{LOGO_URL}"
                 alt="TEB Solutions" width="140"
                 style="display:block; width:140px; height:auto;" />
          </td>
          <td align="right" valign="middle"
              style="font-size:12px; color:#93c5fd; font-weight:600;
                     letter-spacing:0.5px; white-space:nowrap;">
            Web Design &amp; Digital
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- SERVICE PILL -->
  <tr>
    <td class="px36"
        style="background-color:#eff4ff; padding:12px 36px 0;">
      <span style="display:inline-block; padding:4px 12px;
                   background-color:#1d4ed8; color:#e0ecff;
                   border-radius:999px; font-size:11px;
                   font-weight:700; letter-spacing:0.8px;">
        Website Design &bull; Redesign &bull; Technical Review
      </span>
    </td>
  </tr>

  <!-- HEADLINE -->
  <tr>
    <td class="px36"
        style="background-color:#eff4ff; padding:14px 36px 6px;">
      <h1 class="h1"
          style="margin:0 0 6px; font-size:22px; line-height:1.4;
                 color:#0f172a; font-weight:700;">
        Observations on {domain}&rsquo;s website structure &amp; experience
      </h1>
      <p style="margin:0 0 14px; font-size:14px; color:#1d4ed8; font-weight:500;">
        A few practical observations on site structure, mobile presentation, and visitor navigation.
      </p>
    </td>
  </tr>

  <!-- BODY COPY -->
  <tr>
    <td class="px36"
        style="background-color:#eff4ff; padding:0 36px 18px;">
      <p style="margin:0 0 12px; font-size:14px; color:#111827;">
        Hi {name},
      </p>
      <p style="margin:0 0 14px; font-size:15px; line-height:1.75; color:#111827;">
        I took a look at <strong>{domain}</strong> while reviewing local commercial and property management websites,
        and noted a few straightforward opportunities to modernise the user experience so the site loads faster,
        presents a more cohesive layout, and makes it simpler for visitors to navigate your services.
      </p>
      <p style="margin:0; font-size:15px; line-height:1.75; color:#111827;">
        At <strong>TEB Solutions</strong>, we design, build, and maintain high-performing websites for growing businesses
        that value clear presentation and reliable digital architecture.
      </p>
    </td>
  </tr>

  <!-- FOCUS AREAS CARD -->
  <tr>
    <td class="px36" style="padding:0 36px 16px; background-color:#eff4ff;">
      <table role="presentation" width="100%"
             style="background:#ffffff; border-radius:10px;
                    border:1px solid #dbe4ff;">
        <tr>
          <td style="padding:14px 18px; font-size:14px; color:#0f172a;">
            <p style="margin:0 0 8px; font-weight:700; color:#0f172a;">
              Key factors that shape visitor confidence and usability:
            </p>
            <ul style="margin:0; padding-left:18px; color:#374151; line-height:1.85;">
              <li><strong>Modern First Impression:</strong> Clear communication of services and credentials immediately upon landing.</li>
              <li><strong>Mobile Responsiveness:</strong> Seamless layout, readable typography, and effortless navigation on small screens.</li>
              <li><strong>Direct Contact Pathways:</strong> Intuitive, visible access to contact and enquiry details across all pages.</li>
              <li><strong>Technical Foundations:</strong> Clean page indexing, XML sitemap configuration, and reliable load performance.</li>
            </ul>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- PORTFOLIO STRIP -->
  <tr>
    <td class="px36" style="padding:0 36px 18px; background-color:#eff4ff;">
      <p style="margin:0 0 8px; font-size:12px; font-weight:700;
                color:#374151; text-transform:uppercase; letter-spacing:0.7px;">
        Recent websites we've built &amp; managed:
      </p>
      <table role="presentation" class="two-col" width="100%">
        <tr>
          <!-- Hexaprime -->
          <td width="33%" style="padding:3px 4px;">
            <div style="background:#ffffff; border:1px solid #dbe4ff;
                        border-radius:8px; padding:10px 10px;
                        text-align:center;">
              <p style="margin:0; font-size:13px; font-weight:700;
                         color:#1d4ed8;">Hexaprime.me</p>
              <p style="margin:3px 0 0; font-size:11px; color:#6b7280;">
                Branding &amp; Web
              </p>
            </div>
          </td>
          <!-- Channelnexus -->
          <td width="33%" style="padding:3px 4px;">
            <div style="background:#ffffff; border:1px solid #dbe4ff;
                        border-radius:8px; padding:10px 10px;
                        text-align:center;">
              <p style="margin:0; font-size:13px; font-weight:700;
                         color:#1d4ed8;">Channelnexus.me</p>
              <p style="margin:3px 0 0; font-size:11px; color:#6b7280;">
                SaaS Landing
              </p>
            </div>
          </td>
          <!-- Sketchlife -->
          <td width="33%" style="padding:3px 4px;">
            <div style="background:#ffffff; border:1px solid #dbe4ff;
                        border-radius:8px; padding:10px 10px;
                        text-align:center;">
              <p style="margin:0; font-size:13px; font-weight:700;
                         color:#1d4ed8;">Sketchlife.ae</p>
              <p style="margin:3px 0 0; font-size:11px; color:#6b7280;">
                UAE Lifestyle
              </p>
            </div>
          </td>
        </tr>
        <tr>
          <td colspan="3" style="padding:7px 4px 0;">
            <p style="margin:0; font-size:12px; color:#6b7280; font-style:italic;">
              + many more white-label solutions across UAE, India &amp; the UK.
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- QUICK CHECK CARDS 2x2 -->
  <tr>
    <td class="px36" style="padding:0 36px 16px; background-color:#eff4ff;">
      <p style="margin:0 0 8px; font-size:13px; font-weight:700; color:#374151;">
        Helpful evaluation points for your current site:
      </p>
      <table role="presentation" class="two-col" width="100%">
        <tr>
          <td width="50%" style="padding:3px 4px;">
            <div style="border-radius:8px; border:1px dashed #c7d2fe;
                        background:#ffffff; padding:9px 11px; font-size:13px;">
              <div style="font-weight:700; color:#1d4ed8; margin-bottom:3px;">
                First impression
              </div>
              <div style="color:#374151; line-height:1.5;">
                Does your homepage instantly show what you do and why you're trusted?
              </div>
            </div>
          </td>
          <td width="50%" style="padding:3px 4px;">
            <div style="border-radius:8px; border:1px dashed #c7d2fe;
                        background:#ffffff; padding:9px 11px; font-size:13px;">
              <div style="font-weight:700; color:#1d4ed8; margin-bottom:3px;">
                Mobile experience
              </div>
              <div style="color:#374151; line-height:1.5;">
                Is everything easy to tap, read and scroll on a small phone?
              </div>
            </div>
          </td>
        </tr>
        <tr>
          <td width="50%" style="padding:3px 4px;">
            <div style="border-radius:8px; border:1px dashed #c7d2fe;
                        background:#ffffff; padding:9px 11px; font-size:13px;">
              <div style="font-weight:700; color:#1d4ed8; margin-bottom:3px;">
                Visitor contact flow
              </div>
              <div style="color:#374151; line-height:1.5;">
                Are direct contact and enquiry pathways clearly visible throughout?
              </div>
            </div>
          </td>
          <td width="50%" style="padding:3px 4px;">
            <div style="border-radius:8px; border:1px dashed #c7d2fe;
                        background:#ffffff; padding:9px 11px; font-size:13px;">
              <div style="font-weight:700; color:#1d4ed8; margin-bottom:3px;">
                Google basics
              </div>
              <div style="color:#374151; line-height:1.5;">
                Search Console set up? Sitemap &amp; robots.txt configured?
              </div>
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- INFORMATIONAL CLOSING (NO CALL TO ACTION) -->
  <tr>
    <td class="px36" style="padding:0 36px 20px; background-color:#eff4ff;">
      <table role="presentation" width="100%"
             style="background:#f1f5f9; border-radius:10px;
                    border:1px solid #cbd5e1;">
        <tr>
          <td style="padding:14px 18px; font-size:13.5px; color:#475569; line-height:1.6;">
            These observations are shared purely as helpful context for your team's website planning.
            There is no need to reply or follow up.
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- DIVIDER -->
  <tr>
    <td style="height:1px; background:#e2e8f0; font-size:0; line-height:0;"></td>
  </tr>

  <!-- FOOTER — navy matching header, Guardrail #22 -->
  <tr>
    <td class="px36"
        style="background:#0d1b2a; padding:18px 36px 22px;">
      <p style="margin:0 0 4px; font-size:13px; color:#e5e7eb; line-height:1.6;">
        Best regards,<br />
        <strong>{your_name}</strong><br />
        TEB Solutions &nbsp;&middot;&nbsp;
        <a href="https://tebsolutions.in"
           style="color:#93c5fd; text-decoration:none;">tebsolutions.in</a>
      </p>
      <p style="margin:6px 0 0; font-size:11px; color:#94a3b8; line-height:1.7;">
        Email: info@tebsolutions.in &nbsp;&middot;&nbsp; Web: tebsolutions.in
      </p>
      <p style="margin:10px 0 0; font-size:11px; color:#64748b; line-height:1.6;">
        If this note is not relevant to your team, please feel free to disregard.
        &copy; 2026 TEB Solutions &mdash; Web Design &amp; Digital Solutions.
      </p>
    </td>
  </tr>

</table><!-- /CARD -->
</td></tr>
</table><!-- /OUTER WRAPPER -->

</body>
</html>"""

# ─── Geo-Smart Pricing ────────────────────────────────────────────────────────

_TIER_PRICES: dict[str, tuple] = {
    # currency: (blueprint, fix_report, complete, redesign,
    #             guestpost/mo, maintenance/mo, listing, blog/mo)
    "USD": ("$25",       "$50",       "$99",       "$300",      "$39/mo",   "$39/mo",   "$49",    "$45/mo"),
    "INR": ("₹1,999",   "₹4,999",   "₹7,999",   "₹29,999",  "₹2,999/mo","₹2,999/mo","₹3,999", "₹3,499/mo"),
}


def get_pricing(currency_code: str | None) -> dict:
    """
    Return pricing tiers as a dict.
    Policy: INR for Indian leads (currency_code='INR'), USD for all others.
    Never raises — returns USD on any error.
    """
    try:
        code = (currency_code or "USD").upper()
        # Only INR gets local pricing; everyone else gets USD
        prices = _TIER_PRICES.get(code, _TIER_PRICES["USD"])
    except Exception:
        prices = _TIER_PRICES["USD"]
    return {
        "blueprint":    prices[0],
        "fix_report":   prices[1],
        "complete":     prices[2],
        "redesign":     prices[3],
        "guestpost":    prices[4],
        "maintenance":  prices[5],
        "listing":      prices[6],
        "blog":         prices[7],
    }



# ─── build_html_email_full() — Email 2 (Website Design Proposal, sent after YES reply) ───

def build_html_email_full(lead, audit) -> str:
    """
    Full branded HTML Email 2 — Website Design & Redesign Proposal.
    Sent after the prospect replies YES to Email 1 (web design pitch).

    Design rules (Guardrail #22):
      - Navy #0d1b2a logo header (full-width, logo centred at 180px)
      - No gradient banners in the body — only the header
      - Plain-text styled services list (no pricing table)
      - Single CTA button at the very end
      - Under 25KB HTML · Max 1 <img> (logo only)
      - List-Unsubscribe ONLY here (Email 2), NOT in Email 1

    Content pivot (web-design-first, not SEO-audit-first):
      - Opening: thanks for reply, here's what we'd do for your site
      - Section 1: design + UX issues noticed on their site (from audit data,
        reframed in design language — not SEO jargon)
      - Section 2: what a modern redesign delivers
      - Section 3: services & pricing (design-focused)
      - Section 4: portfolio proof
      - Single CTA: book / reply keyword
    """
    name    = lead.business_name or "there"
    website = lead.website or ""
    domain  = (
        website.replace("https://", "").replace("http://", "")
               .replace("www.", "").rstrip("/").split("/")[0]
    )
    first_name = name.split()[0] if name else "there"

    # ── Geo-localised pricing (Guardrail #21 — INR for India, USD for all others) ─
    currency_code = getattr(audit, "currency_code", None) if audit else None
    pricing     = get_pricing(currency_code)
    p_redesign  = pricing["redesign"]
    p_fix       = pricing["fix_report"]      # repurposed: "Starter Design Package"
    p_complete  = pricing["complete"]        # repurposed: "Full Design + SEO Launch"
    p_maintain  = pricing["maintenance"]
    p_blog      = pricing["blog"]            # repurposed: "Content & Landing Pages"

    # ── Design/UX issues from audit — reframed in web-design language ────────────
    issue_bullets_html = _build_audit_bullets(audit)
    issue_count = len([l for l in (issue_bullets_html or "").split("\n") if "<tr>" in l]) or 3

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>Website redesign proposal — {domain}</title>
  <style>
    @media only screen and (max-width:600px) {{
      .card      {{ width:100% !important; }}
      .body-cell {{ padding:24px 20px 8px !important; }}
      .foot-cell {{ padding:16px 20px 20px !important; }}
      .logo-cell {{ padding:18px 20px 14px !important; }}
      .cta-btn   {{ padding:13px 22px !important; font-size:14px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#eef2f7;
             font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;">

  <!-- Outer wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background-color:#eef2f7;padding:32px 12px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" border="0"
             style="max-width:600px;width:100%;">

        <!-- ══ LOGO HEADER — navy #0d1b2a (Guardrail #22) ══ -->
        <tr>
          <td style="background-color:#0d1b2a;
                     border-bottom:2px solid #1e3a5f;
                     border-radius:12px 12px 0 0;
                     margin:0;padding:0;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td align="center" valign="middle"
                    style="padding:28px 24px;color:#ffffff;">
                  <img src="{LOGO_URL}"
                       alt="TEB Solutions"
                       width="180"
                       style="display:block;max-width:180px;width:180px;
                              height:auto;margin:0 auto;border:0;
                              outline:none;text-decoration:none;" />
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ══ WHITE BODY ══ -->
        <tr>
          <td style="background:#ffffff;
                     border-left:1px solid #dde3ec;
                     border-right:1px solid #dde3ec;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0">

              <!-- Opening — thanks for YES reply -->
              <tr>
                <td class="body-cell" style="padding:36px 40px 20px;">
                  <p style="margin:0 0 16px;font-size:15px;line-height:26px;color:#374151;">
                    Hi <strong style="color:#111827;">{first_name}</strong>,
                  </p>
                  <p style="margin:0 0 14px;font-size:15px;line-height:26px;color:#374151;">
                    Thanks for replying &mdash; glad you're open to it.
                    I had a closer look at <strong>{domain}</strong> and put
                    together a short proposal specifically for your business.
                  </p>
                  <p style="margin:0;font-size:15px;line-height:26px;color:#374151;">
                    Below you'll find what we noticed on your current site,
                    what a modern redesign would deliver, and the services
                    we'd recommend &mdash; along with clear, no-surprise pricing.
                  </p>
                </td>
              </tr>

              <!-- ── Section 1: What we noticed on your site ── -->
              <tr>
                <td style="padding:4px 40px 24px;">
                  <p style="margin:0 0 14px;font-size:13px;font-weight:700;
                             letter-spacing:1px;text-transform:uppercase;
                             color:#6b7280;">
                    Design &amp; technical issues we noticed on {domain}
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0"
                         style="border:1px solid #fca5a5;border-radius:8px;
                                background:#fff8f8;overflow:hidden;">
{issue_bullets_html}
                  </table>
                  <p style="margin:12px 0 0;font-size:13px;line-height:21px;color:#6b7280;">
                    These are exactly the kind of issues we fix as part of
                    every project &mdash; you won't need to manage any of it yourself.
                  </p>
                </td>
              </tr>

              <!-- ── Section 2: What a modern redesign delivers ── -->
              <tr>
                <td style="padding:0 40px 24px;">
                  <p style="margin:0 0 14px;font-size:13px;font-weight:700;
                             letter-spacing:1px;text-transform:uppercase;
                             color:#6b7280;">
                    What a modern redesign delivers
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0"
                         style="border:1px solid #d1fae5;border-radius:8px;
                                background:#f0fdf4;overflow:hidden;padding:6px 18px;">
                    <tr><td style="padding:14px 18px;">
                      <p style="margin:0 0 8px;font-size:14px;line-height:24px;color:#1a1a1a;">
                        &#9989; <strong>First impression that converts</strong> &mdash;
                        visitors instantly understand what you do and why to trust you.
                      </p>
                      <p style="margin:0 0 8px;font-size:14px;line-height:24px;color:#1a1a1a;">
                        &#9989; <strong>Mobile-first, fast-loading</strong> &mdash;
                        works perfectly on every phone and passes Core Web Vitals.
                      </p>
                      <p style="margin:0 0 8px;font-size:14px;line-height:24px;color:#1a1a1a;">
                        &#9989; <strong>Clear lead-capture paths</strong> &mdash;
                        Call, WhatsApp, and enquiry buttons placed where visitors look.
                      </p>
                      <p style="margin:0 0 8px;font-size:14px;line-height:24px;color:#1a1a1a;">
                        &#9989; <strong>Google-ready from day one</strong> &mdash;
                        SSL, sitemap, robots.txt, Search Console, Schema markup all set up correctly.
                      </p>
                      <p style="margin:0;font-size:14px;line-height:24px;color:#1a1a1a;">
                        &#9989; <strong>Ongoing peace of mind</strong> &mdash;
                        optional monthly maintenance so your site stays live, secure and updated.
                      </p>
                    </td></tr>
                  </table>
                </td>
              </tr>

              <!-- ── Section 3: Services & Pricing (plain-text list, Guardrail #22) ── -->
              <tr>
                <td style="padding:0 40px 28px;">
                  <p style="margin:0 0 14px;font-size:13px;font-weight:700;
                             letter-spacing:1px;text-transform:uppercase;
                             color:#6b7280;">
                    Our services &amp; pricing
                  </p>

                  <div style="font-family:Arial,sans-serif;font-size:15px;
                              color:#1a1a1a;line-height:1.9;padding:0;">

                    <p style="margin:0 0 10px;">
                      &#127959; <strong>Website Redesign</strong> &mdash;
                      We rebuild your existing site from the ground up &mdash; modern layout,
                      mobile-first, conversion-focused. Includes SSL, sitemap, Search Console setup.
                      <strong style="color:#15803d;">{p_redesign}</strong> project.</p>

                    <p style="margin:0 0 10px;">
                      &#127760; <strong>Full Design + SEO Launch Package</strong> &mdash;
                      Redesign + on-page SEO setup + Schema markup + Google Business Profile
                      optimisation + 30-day performance check.
                      <strong style="color:#15803d;">{p_complete}</strong> one-time.
                      <em style="color:#6b7280;">(most chosen)</em></p>

                    <p style="margin:0 0 10px;">
                      &#128196; <strong>Starter Design Package</strong> &mdash;
                      Clean, professional single-page or 3-page website for businesses
                      that need to get online quickly.
                      <strong style="color:#15803d;">{p_fix}</strong> one-time.</p>

                    <p style="margin:0 0 10px;">
                      &#128736; <strong>Website Maintenance</strong> &mdash;
                      Monthly WordPress updates, security patches, backups, uptime monitoring
                      and speed checks. Never worry about your site going down or getting hacked.
                      <strong style="color:#15803d;">{p_maintain}</strong>.</p>

                    <p style="margin:0 0 0;">
                      &#9997; <strong>Content &amp; Landing Pages</strong> &mdash;
                      Keyword-targeted blog posts and campaign landing pages published monthly.
                      Keeps Google crawling and builds topical authority around your services.
                      <strong style="color:#15803d;">{p_blog}</strong>.</p>
                  </div>

                  <p style="margin:16px 0 0;font-size:13px;color:#9ca3af;line-height:20px;">
                    Not sure which fits? Just reply with the service name and I'll
                    send a no-obligation breakdown within a few hours.
                  </p>
                </td>
              </tr>

              <!-- ── Section 4: Portfolio proof ── -->
              <tr>
                <td style="padding:0 40px 28px;">
                  <p style="margin:0 0 12px;font-size:13px;font-weight:700;
                             letter-spacing:1px;text-transform:uppercase;
                             color:#6b7280;">
                    Recent projects
                  </p>
                  <table width="100%" cellpadding="0" cellspacing="0" border="0"
                         style="border:1px solid #dbe4ff;border-radius:8px;
                                background:#eff4ff;overflow:hidden;">
                    <tr><td style="padding:14px 18px;">
                      <p style="margin:0 0 6px;font-size:14px;color:#1a1a1a;line-height:22px;">
                        &#127760; <strong style="color:#1d4ed8;">Hexaprime.me</strong>
                        &mdash; Full branding &amp; web design
                      </p>
                      <p style="margin:0 0 6px;font-size:14px;color:#1a1a1a;line-height:22px;">
                        &#128279; <strong style="color:#1d4ed8;">Channelnexus.me</strong>
                        &mdash; SaaS product landing page
                      </p>
                      <p style="margin:0 0 8px;font-size:14px;color:#1a1a1a;line-height:22px;">
                        &#9992; <strong style="color:#1d4ed8;">Sketchlife.ae</strong>
                        &mdash; UAE lifestyle brand website
                      </p>
                      <p style="margin:0;font-size:12px;color:#6b7280;font-style:italic;">
                        + many more white-label solutions across UAE, India &amp; the UK.
                      </p>
                    </td></tr>
                  </table>
                </td>
              </tr>

              <!-- ── Closing ── -->
              <tr>
                <td style="padding:0 40px 32px;">
                  <p style="margin:0;font-size:15px;line-height:26px;color:#374151;">
                    Happy to walk you through any of these in detail &mdash; no
                    obligation. Most projects are delivered within 2&ndash;3 weeks
                    of kickoff.<br><br>
                    Just reply with the service keyword below or hit the button:
                  </p>
                  <p style="margin:14px 0 0;font-size:13px;color:#6b7280;line-height:20px;">
                    <strong>REDESIGN</strong> &nbsp;/&nbsp;
                    <strong>COMPLETE</strong> &nbsp;/&nbsp;
                    <strong>STARTER</strong> &nbsp;/&nbsp;
                    <strong>MAINTAIN</strong> &nbsp;/&nbsp;
                    <strong>CONTENT</strong>
                    &mdash; I'll send a tailored breakdown.
                  </p>
                </td>
              </tr>

            </table>
          </td>
        </tr>

        <!-- ══ SINGLE CTA (Guardrail #22) ══ -->
        <tr>
          <td align="center"
              style="background:#f8fafc;
                     border-left:1px solid #dde3ec;
                     border-right:1px solid #dde3ec;
                     padding:28px 40px 32px;">
            <a href="mailto:info@tebsolutions.in?subject=YES%20%E2%80%94%20Website%20Redesign%20Proposal%20%28{domain}%29"
               class="cta-btn"
               style="display:inline-block;background:#1d4ed8;color:#ffffff;
                      font-weight:700;font-size:15px;padding:16px 40px;
                      border-radius:999px;text-decoration:none;
                      letter-spacing:0.3px;">
              YES &mdash; let's discuss my website
            </a>
            <p style="margin:14px 0 0;font-size:13px;color:#9ca3af;">
              Or just hit reply &mdash; I'll get back to you within a few hours.
            </p>
          </td>
        </tr>

        <!-- ══ FOOTER — navy matching header (Guardrail #22) ══ -->
        <tr>
          <td class="foot-cell"
              style="background:#0d1b2a;
                     border:1px solid #1e3a5f;
                     border-top:none;
                     border-radius:0 0 12px 12px;
                     padding:20px 40px 24px;">
            <p style="margin:0 0 4px;font-size:13px;color:#e5e7eb;text-align:center;line-height:1.6;">
              Ashish &mdash; TEB Solutions &nbsp;&middot;&nbsp;
              <a href="https://tebsolutions.in"
                 style="color:#93c5fd;text-decoration:none;">tebsolutions.in</a>
              &nbsp;&middot;&nbsp;
              <a href="mailto:info@tebsolutions.in"
                 style="color:#93c5fd;text-decoration:none;">info@tebsolutions.in</a>
            </p>
            <p style="margin:6px 0 0;font-size:11px;color:#9ca3af;text-align:center;line-height:1.6;">
              Phone: +91&nbsp;86303&nbsp;03982 &nbsp;&middot;&nbsp;
              WhatsApp: <a href="https://wa.me/message/BQGXXMD5SZRKF1"
                           style="color:#93c5fd;text-decoration:underline;">Chat on WhatsApp (92582&nbsp;03982)</a>
            </p>
            <p style="margin:10px 0 0;font-size:11px;color:#4b5563;text-align:center;line-height:1.7;">
              Not interested? Reply <strong style="color:#9ca3af;">STOP</strong>
              and I'll remove you immediately.<br>
              &copy; 2026 TEB Solutions &mdash; Web Design, Redesign &amp; Management.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>

</body>
</html>"""

# ─── SMTP Send (Synchronous — run in executor) ────────────────────────────────

def build_plain_outreach_email(lead, audit=None, site_type=None) -> str:
    """Build the first-contact email as a clean, observational plain-text note with zero CTAs and zero spam triggers."""
    business_name = (lead.business_name or "there").strip()
    domain = (
        (lead.website or "")
        .replace("https://", "")
        .replace("http://", "")
        .replace("www.", "")
        .rstrip("/")
        .split("/")[0]
    ) or "your website"

    try:
        accounts = settings.get_smtp_accounts()
        your_name = accounts[0].get("sender_name", "Ashish") if accounts else "Ashish"
    except Exception:
        your_name = "Ashish"

    if getattr(site_type, "value", site_type) in {"parked", "demo", "not_found", "unreachable"}:
        website_reference = f" at {domain}" if domain else ""
        return (
            f"Hi {business_name},\n\n"
            f"I was looking for {business_name} online and noticed that your website{website_reference} "
            f"does not currently appear to be active.\n\n"
            "At TEB Solutions, we design and launch clean, modern websites for growing businesses.\n\n"
            "Recent websites we have built & managed:\n"
            "- Hexaprime.me (Branding & Web)\n"
            "- Channelnexus.me (SaaS Landing)\n"
            "- Sketchlife.ae (UAE Lifestyle)\n\n"
            "Sharing this in case your team is currently reviewing your online presence.\n\n"
            "Best regards,\n"
            f"{your_name}\n"
            "TEB Solutions · tebsolutions.in\n"
            "info@tebsolutions.in\n\n"
            "If this note is not relevant to your team, please feel free to disregard."
        )

    return (
        f"Hi {business_name},\n\n"
        f"I took a look at {domain} while reviewing commercial and local business websites, "
        f"and put together a few objective observations regarding visitor navigation, presentation, and technical setup.\n\n"
        "At TEB Solutions, we design, build, and maintain high-performing websites for growing businesses.\n\n"
        "Key factors that shape visitor confidence and usability:\n"
        "- Modern First Impression: Clear communication of services and credentials immediately upon landing.\n"
        "- Mobile Responsiveness: Seamless layout, readable typography, and easy navigation on small screens.\n"
        "- Direct Contact Pathways: Simple, intuitive access to phone and enquiry options across all pages.\n"
        "- Technical Foundations: Clean page indexing, XML sitemap configuration, and reliable load performance.\n\n"
        "Recent websites we've built & managed:\n"
        "- Hexaprime.me (Branding & Web)\n"
        "- Channelnexus.me (SaaS Landing)\n"
        "- Sketchlife.ae (UAE Lifestyle)\n"
        "+ ongoing web solutions across India, the UAE, and the UK.\n\n"
        "Helpful evaluation points for your current site:\n"
        "- First impression: Does the homepage clearly state your offerings and trust credentials within seconds?\n"
        "- Mobile experience: Is navigation and layout seamless on mobile devices?\n"
        "- Contact accessibility: Are inquiry and contact details easily visible?\n"
        "- Search foundation: Are Search Console, sitemap, and robots.txt properly configured?\n\n"
        "These notes are shared purely as helpful background for your team's website planning. "
        "There is no need to reply or follow up.\n\n"
        "Best regards,\n"
        f"{your_name}\n"
        "TEB Solutions · tebsolutions.in\n"
        "info@tebsolutions.in\n\n"
        "If this note is not relevant to your team, please feel free to disregard.\n"
        "© 2026 TEB Solutions — Web Design & Digital Solutions."
    )


def build_minimal_html_email(plain_body: str) -> str:
    """Render the same first-contact copy with restrained, email-safe styling."""
    safe_body = escape(plain_body)
    linked_body = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" style="color:#1d4ed8;text-decoration:underline;">\1</a>',
        safe_body,
    )
    linked_body = linked_body.replace("\n", "<br>")

    return f"""<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:#f8fafc;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;">
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #e2e8f0;">
        <tr><td style="height:5px;background:#0f2747;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="padding:28px 32px;font-family:Georgia,'Times New Roman',serif;color:#172033;font-size:16px;line-height:1.7;">
          <div style="font-family:Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:1.2px;color:#1d4ed8;margin-bottom:18px;">TEB SOLUTIONS · WEBSITE DESIGN &amp; REDESIGN</div>
          {linked_body}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _send_email_sync(
    account: dict,
    to_email: str,
    subject: str,
    html_body: str,
    is_followup: bool = False,          # True = Email 2 (full audit); False = Email 1 (trust-builder)
    lead_name: str = "",                 # used in personalised plain-text
    domain: str = "",                    # used in personalised plain-text
    hook_line: str = "",                 # the specific finding from _pick_hook()
    pdf_attachment_path: str = None,     # path to the generated PDF audit report
    plain_body: str = "",                # Email 1: send a single text/plain MIME part
) -> tuple:
    """Send email synchronously via SMTP. Returns (success: bool, error: str).

    Inbox-placement rules applied here:
      Email 1 (trust-builder):
        - From = person name, not company name   → avoids Promotions routing
        - NO List-Unsubscribe header             → List-Unsubscribe = #1 Promotions signal
        - Rich personalised plain-text part      → better text/html ratio
      Email 2 (full audit, follow-up):
        - List-Unsubscribe included (RFC 2369)   → leads who replied YES expect it
    """
    sender_email = account["email"]
    login_email  = account.get("login_email", sender_email)
    smtp_host    = account["smtp_host"]
    smtp_port    = int(account.get("smtp_port", 465))
    password     = account["password"]
    sender_name  = account.get("sender_name", "Ashish")   # human first name from config

    try:
        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{sender_name} <{sender_email}>"   # person name, NOT "TEB Solutions"
        msg["To"]      = to_email
        msg["Subject"] = subject

        # List-Unsubscribe: REMOVED from both Email 1 and Email 2.
        # It is the #1 signal Gmail uses to route to Promotions.
        # The STOP instruction in the email body text is legally sufficient.

        # Reply-To: if configured, replies go to this address
        reply_to = account.get("reply_to", "info@tebsolutions.in")
        if reply_to:
            msg["Reply-To"] = reply_to

        if plain_body:
            outgoing_msg = MIMEMultipart("alternative") if html_body else MIMEText(plain_body, "plain", "utf-8")
            if html_body:
                outgoing_msg.attach(MIMEText(plain_body, "plain", "utf-8"))
                outgoing_msg.attach(MIMEText(html_body, "html", "utf-8"))
            outgoing_msg["From"] = msg["From"]
            outgoing_msg["To"] = msg["To"]
            outgoing_msg["Subject"] = msg["Subject"]
            if reply_to:
                outgoing_msg["Reply-To"] = reply_to

            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(login_email, password)
                    server.sendmail(sender_email, to_email, outgoing_msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.ehlo()
                    server.starttls()
                    server.login(login_email, password)
                    server.sendmail(sender_email, to_email, outgoing_msg.as_string())
            return True, ''

        # ── Plain-text part: personalised, conversational ────────────────────
        name_part = f"for {lead_name}" if lead_name else ""
        domain_part = f" on {domain}" if domain else ""
        hook_part = f"\n\nSpecifically — {hook_line}" if hook_line else ""

        if is_followup:
            text_body = (
                f"Hi {lead_name},\n\n"
                f"As promised — here is the full audit breakdown{domain_part}.\n\n"
                f"I've listed every issue we found, what it's costing you in lost traffic,\n"
                f"and three ways we can fix it — starting from a simple report all the way\n"
                f"to a full website rebuild.\n\n"
                f"Reply with 'Fix', 'Blueprint', or 'Complete' and we'll get started.\n\n"
                f"Best,\n{sender_name}\n"
                f"TEB Solutions · tebsolutions.in\n\n"
                f"---\n"
                f"Not interested? Reply STOP and I'll remove you immediately."
            )
        else:
            text_body = (
                f"Hi{(' ' + lead_name) if lead_name else ''},\n\n"
                f"I took a look at {domain or 'your website'} while reviewing local business websites, "
                f"and put together a few objective observations regarding visitor navigation, presentation, and technical setup.\n\n"
                f"At TEB Solutions, we design, build, and maintain high-performing websites for growing businesses.\n\n"
                f"These notes are shared purely as helpful background for your team's website planning. "
                f"There is no need to reply or follow up.\n\n"
                f"Best regards,\n{sender_name}\n"
                f"TEB Solutions · tebsolutions.in\n"
                f"info@tebsolutions.in\n\n"
                f"If this note is not relevant to your team, please feel free to disregard."
            )

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html",  "utf-8"))

        # Attach PDF if provided (typically for Email 2)
        if pdf_attachment_path:
            import os
            from email.mime.application import MIMEApplication
            if os.path.exists(pdf_attachment_path):
                with open(pdf_attachment_path, "rb") as f:
                    pdf_part = MIMEApplication(f.read(), _subtype="pdf")
                    pdf_part.add_header('Content-Disposition', 'attachment', filename=f"{domain}_SEO_Audit_Report.pdf")
                    msg.attach(pdf_part)
            else:
                logger.warning(f"PDF attachment not found at: {pdf_attachment_path}")

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                server.login(login_email, password)
                server.sendmail(sender_email, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(login_email, password)
                server.sendmail(sender_email, to_email, msg.as_string())

        return True, ''
    except Exception as e:
        err_str = str(e)
        logger.error(f"SMTP send failed to {to_email} via {sender_email}@{smtp_host}:{smtp_port} — {err_str}")
        return False, err_str



# ─── Campaign Runner (Background Task) ────────────────────────────────────────

_RUNNING_CAMPAIGNS: set[str] = set()

async def run_campaign(campaign_id: str):
    """
    Background task: sends personalised branded HTML emails with:
    - Pause/resume support (checks campaign.status before each send)
    - Concurrency lock (prevents duplicate runners on pause/resume)
    - Skips leads emailed within the last 7 days
    - Tracks next_email_at countdown for live UI timer
    - Logs every email attempt to CampaignEmailLog
    - Updates pending_lead_ids so the campaign can be resumed
    """
    if campaign_id in _RUNNING_CAMPAIGNS:
        logger.warning(f"Campaign {campaign_id} is already actively running. Ignoring duplicate start request.")
        return

    _RUNNING_CAMPAIGNS.add(campaign_id)
    try:
        await _run_campaign_worker(campaign_id)
    finally:
        _RUNNING_CAMPAIGNS.discard(campaign_id)


async def _run_campaign_worker(campaign_id: str):
    from app.models import CampaignEmailLog
    from app.utils.site_checker import parse_site_status, SiteType

    accounts = settings.get_smtp_accounts()
    if not accounts:
        logger.error("No SMTP accounts configured. Aborting campaign.")
        return

    account_index = 0

    async with AsyncSessionLocal() as db:
        campaign = await db.get(Campaign, uuid.UUID(campaign_id))
        if not campaign:
            logger.error(f"Campaign {campaign_id} not found.")
            return

        campaign.status = CampaignStatus.sending
        campaign.next_email_at = None
        await db.commit()

        # Helper to check today's sent count per SMTP account
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        async def get_today_count(sender_email: str) -> int:
            from sqlalchemy import select, func
            stmt = (
                select(func.count(CampaignEmailLog.id))
                .where(
                    CampaignEmailLog.status == "sent",
                    CampaignEmailLog.created_at >= today_start,
                    CampaignEmailLog.message.ilike(f"%({sender_email})%")
                )
            )
            result = await db.execute(stmt)
            return result.scalar() or 0

        subject_template = campaign.subject_template or DEFAULT_SUBJECT_TEMPLATE

        # ── Determine which leads still need sending ───────────────────────
        # If pending_lead_ids is populated (resume), use that; else use full list.
        all_ids = campaign.lead_ids or []
        pending = list(campaign.pending_lead_ids or []) or list(all_ids)

        sent    = campaign.sent_count or 0
        skipped = campaign.skipped_count or 0
        failed  = campaign.failed_count or 0

        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        for idx, lead_id_str in enumerate(list(pending)):
            # ── Check for pause/stop before every send ─────────────────────
            await db.refresh(campaign)
            if campaign.status == CampaignStatus.paused:
                # Save remaining work so we can resume later
                campaign.pending_lead_ids = pending[idx:]
                campaign.sent_count  = sent
                campaign.skipped_count = skipped
                campaign.failed_count  = failed
                campaign.next_email_at = None
                await db.commit()
                logger.info(f"Campaign {campaign_id} paused at lead {lead_id_str}.")
                return  # stop processing; campaign stays 'paused'

            try:
                lead_id = uuid.UUID(str(lead_id_str))
                lead    = await db.get(Lead, lead_id)
                if not lead:
                    # Lead deleted — just remove from pending
                    continue

                # ── 7-day skip check ──────────────────────────────────────
                if lead.last_emailed_at and lead.last_emailed_at > seven_days_ago:
                    skipped += 1
                    campaign.skipped_count = skipped
                    log_entry = CampaignEmailLog(
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        business_name=lead.business_name,
                        email=lead.email,
                        status="skipped",
                        message=f"Skipped — emailed {lead.last_emailed_at.strftime('%d %b %Y')} (within 7 days)",
                    )
                    db.add(log_entry)
                    await db.commit()
                    logger.info(f"Skipped {lead.email} — emailed within 7 days")
                    continue

                # ── Fetch audit ───────────────────────────────────────────
                audit_result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
                audit        = audit_result.scalar_one_or_none()

                site_type = None
                if audit and audit.error_message:
                    site_type = parse_site_status(audit.error_message)

                is_no_site = site_type in (
                    SiteType.PARKED, SiteType.DEMO, SiteType.NOT_FOUND, SiteType.UNREACHABLE,
                )

                # ── Email Validation Before Sending ───────────────────────
                if not is_valid_email(lead.email):
                    skipped += 1
                    campaign.skipped_count = skipped
                    log_entry = CampaignEmailLog(
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        business_name=lead.business_name,
                        email=lead.email,
                        status="skipped",
                        message="Invalid email address format",
                    )
                    db.add(log_entry)
                    # Save progress as skipped leads also advance the list
                    campaign.pending_lead_ids = pending[idx + 1:]
                    await db.commit()
                    logger.info(f"Skipped {lead.email} — Invalid email address format")
                    continue

                domain_str = (lead.website or "").replace("https://","").replace("http://","").replace("www.","").rstrip("/").split("/")[0]
                variables = {
                    "business_name": lead.business_name,
                    "website":       lead.website,
                    "domain":        domain_str,
                }
                if is_no_site:
                    subject = process_template(NO_SITE_SUBJECT_TEMPLATE, variables)
                else:
                    subject = process_template(subject_template, variables)

                plain_body = build_plain_outreach_email(lead, audit, site_type)
                if is_no_site:
                    html_body = build_no_site_email(lead, site_type.value if site_type else "unreachable")
                else:
                    html_body = build_html_email(lead, audit)

                # Rotate sender account and enforce Hostinger Daily Limit (1000/day)
                account = None
                original_index = account_index
                
                while True:
                    candidate_account = accounts[account_index % len(accounts)]
                    candidate_email = candidate_account["email"]
                    
                    if await get_today_count(candidate_email) < 1000:
                        account = candidate_account
                        account_index += 1
                        break
                    
                    account_index += 1
                    # If we checked every account and none has capacity
                    if account_index - original_index >= len(accounts):
                        break

                if not account:
                    logger.info("Daily send limit reached for all accounts. Resume tomorrow.")
                    campaign.status = CampaignStatus.paused
                    campaign.next_email_at = None
                    campaign.pending_lead_ids = pending[idx:]
                    campaign.sent_count = sent
                    campaign.skipped_count = skipped
                    campaign.failed_count = failed
                    await db.commit()
                    return

                loop    = asyncio.get_running_loop()
                result  = await loop.run_in_executor(
                    None,
                    lambda: _send_email_sync(
                        account, lead.email, subject, html_body,
                        plain_body=plain_body,
                        # pdf_attachment_path intentionally NOT passed here.
                        # Email 1 (both no-site web-design pitch and real-site hook)
                        # must NEVER attach a PDF or audit report. PDF attachment is
                        # reserved exclusively for Email 2 (build_html_email_full),
                        # sent only AFTER the lead replies YES. (Guardrail #15/#22)
                    ),
                )
                success, smtp_err = result

                # Determine sender label (Hostinger / Gmail / etc.)
                smtp_host = account.get("smtp_host", "smtp.gmail.com")
                if "hostinger" in smtp_host.lower():
                    via_label = f"via Hostinger ({account['email']})"
                elif "gmail" in smtp_host.lower():
                    via_label = f"via Gmail ({account['email']})"
                else:
                    via_label = f"via {smtp_host} ({account['email']})"

                if success:
                    sent += 1
                    lead.status          = LeadStatus.emailed
                    lead.last_emailed_at = datetime.utcnow()
                    campaign.sent_count  = sent

                    log_entry = CampaignEmailLog(
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        business_name=lead.business_name,
                        email=lead.email,
                        status="sent",
                        message=f"Sent {via_label}. Subject: {subject}",
                    )
                    db.add(log_entry)

                    act_log = ActivityLog(
                        event_type="email_sent",
                        lead_id=lead.id,
                        message=f"Email sent to {lead.email} ({lead.business_name}) {via_label}.",
                    )
                    db.add(act_log)

                    # Determine if this is the last remaining lead
                    is_last = (idx == len(pending) - 1)
                    if is_last:
                        campaign.status        = CampaignStatus.done
                        campaign.next_email_at = None
                        campaign.pending_lead_ids = []

                    await db.commit()
                    logger.info(f"Email sent → {lead.email}")

                    # ── Humanised delay — set countdown timer ─────────────
                    if not is_last:
                        delay      = random.randint(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)  # 1 to 1.5 min between emails
                        next_time  = datetime.utcnow() + timedelta(seconds=delay)
                        campaign.next_email_at = next_time
                        # Save progress so resume works after a crash
                        campaign.pending_lead_ids = pending[idx + 1:]
                        await db.commit()
                        logger.info(f"Next email at {next_time.strftime('%H:%M:%S')} (in {delay//60}m {delay%60}s)")
                        await asyncio.sleep(delay)

                else:
                    failed += 1
                    campaign.failed_count = failed

                    # Reset lead so it appears as fresh in future campaigns
                    lead.last_emailed_at = None
                    # Restore original status: 'audited' only if the audit completed successfully.
                    audit_check = await db.execute(select(Audit).where(Audit.lead_id == lead.id))
                    audit = audit_check.scalar_one_or_none()
                    lead.status = LeadStatus.audited if audit and audit.status == AuditStatus.done else LeadStatus.new

                    # Determine human-friendly SMTP error reason
                    if "550" in smtp_err and "limit" in smtp_err.lower():
                        err_reason = "Daily sending limit exceeded"
                    elif "454" in smtp_err or "Try again later" in smtp_err:
                        err_reason = "Server busy – try again later"
                    elif "535" in smtp_err or "authentication" in smtp_err.lower():
                        err_reason = "Authentication failed"
                    elif "timeout" in smtp_err.lower():
                        err_reason = "Connection timeout"
                    else:
                        err_reason = smtp_err[:120] if smtp_err else "Unknown SMTP error"

                    log_entry = CampaignEmailLog(
                        campaign_id=campaign.id,
                        lead_id=lead.id,
                        business_name=lead.business_name,
                        email=lead.email,
                        status="failed",
                        message=f"{via_label} — {err_reason}",
                    )
                    db.add(log_entry)

                    act_log = ActivityLog(
                        event_type="email_failed",
                        lead_id=lead.id,
                        message=f"Failed to send to {lead.email} ({lead.business_name}) {via_label}: {err_reason}",
                    )
                    db.add(act_log)
                    await db.commit()

            except Exception as e:
                logger.exception(f"Error processing lead {lead_id_str}: {e}")
                failed += 1
                campaign.failed_count = failed
                await db.commit()
                continue

        # ── Mark done (handles edge case where last lead threw) ────────────
        if campaign.status not in (CampaignStatus.done, CampaignStatus.paused):
            campaign.status        = CampaignStatus.done
            campaign.next_email_at = None
            campaign.pending_lead_ids = []
            await db.commit()

        logger.info(
            f"Campaign {campaign_id} done. "
            f"Sent: {sent} | Skipped: {skipped} | Failed: {failed}"
        )



