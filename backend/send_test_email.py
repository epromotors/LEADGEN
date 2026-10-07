"""
send_test_email.py  —  LeadGen OS test email sender
=====================================================
Fetches a fresh lead with an audit from the DB, renders the NEW
short conversion template, and sends it to a specified address.

Usage (from LEADGEN/backend/):
    python send_test_email.py [to_email]

Default recipient: epromotors@gmail.com
"""

import asyncio
import sys
import os

# ── Ensure the app package is importable ──────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select, text
from app.database import AsyncSessionLocal
from app.models import Lead, Audit
from app.engines.outreach_engine import build_minimal_html_email, build_plain_outreach_email, _send_email_sync, DEFAULT_SUBJECT_TEMPLATE
from app.utils.spintax import process_template
from app.config import settings
from app.logger import setup_logging
import logging

setup_logging()
logger = logging.getLogger("test_email")

TO_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "epromotors@gmail.com"


async def fetch_best_lead():
    """
    Pick the best lead for the test:
    1. Has an audit record  (so the hook is personalised)
    2. Has an email address
    3. Prefer a low audit score (more specific hook)
    """
    async with AsyncSessionLocal() as db:
        # Leads that have at least one audit
        result = await db.execute(
            select(Lead, Audit)
            .join(Audit, Audit.lead_id == Lead.id)
            .where(Lead.email.isnot(None))
            .where(Lead.email != "")
            .where(Lead.website.isnot(None))
            .where(Lead.website != "")
            .limit(1)
        )
        row = result.first()
        if row:
            lead, audit = row
            return lead, audit

        # Fallback: any lead with an email even without audit
        result2 = await db.execute(
            select(Lead)
            .where(Lead.email.isnot(None))
            .where(Lead.email != "")
            .limit(1)
        )
        lead = result2.scalar_one_or_none()
        return lead, None


async def main():
    logger.info("=" * 55)
    logger.info("LeadGen OS — New Template Test Send")
    logger.info(f"Recipient : {TO_EMAIL}")
    logger.info("=" * 55)

    # ── Fetch lead ────────────────────────────────────────────────────────────
    lead, audit = await fetch_best_lead()

    if not lead:
        logger.error("No leads found in the database. Upload some leads first.")
        print("\n  ❌  No leads in DB. Use the LeadGen dashboard to upload leads first.")
        return

    logger.info(f"Using lead  : {lead.business_name} <{lead.email}>")
    logger.info(f"Website     : {lead.website}")
    logger.info("Template    : Website Design & Redesign Proposal (Email 1)")

    # ── Build email ───────────────────────────────────────────────────────────
    plain_body = build_plain_outreach_email(lead, audit)
    html_body = build_minimal_html_email(plain_body)

    domain = (
        (lead.website or "")
        .replace("https://", "").replace("http://", "")
        .replace("www.", "").rstrip("/").split("/")[0]
    )
    variables = {
        "business_name": lead.business_name,
        "website": lead.website,
        "domain": domain,
    }
    raw_subject = process_template(DEFAULT_SUBJECT_TEMPLATE, variables)
    subject = f"{raw_subject} [TEST]"

    logger.info(f"Subject     : {subject}")
    logger.info(f"Plain-text size: {len(plain_body):,} characters")

    # ── Send ───────────────────────────────────────────────────────────────────
    accounts = settings.get_smtp_accounts()
    if not accounts:
        logger.error("No SMTP accounts configured in .env (SMTP_SENDERS is empty).")
        print("\n  ❌  SMTP not configured. Check backend/.env → SMTP_SENDERS.")
        return

    account = accounts[0]
    logger.info(f"Sending via : {account['email']} @ {account['smtp_host']}:{account['smtp_port']}")

    # Override To: address to the test recipient
    success, error = _send_email_sync(account, TO_EMAIL, subject, html_body, plain_body=plain_body)

    if success:
        logger.info("Test email sent OK to %s", TO_EMAIL)
        print(f"\n  [OK]  Test email sent to {TO_EMAIL}")
        print(f"      Subject : {subject}")
        print(f"      Lead    : {lead.business_name} ({lead.website})")
        print(f"      Sent via: {account['email']}")
        print()
        print("  If it landed in Spam, your domain reputation may need")
        print("  warming up or SPF/DKIM tuning.")
    else:
        logger.error("Send failed: %s", error)
        print(f"\n  [FAIL]  Send failed: {error}")
        print("  Check SMTP credentials in backend/.env and Hostinger SMTP settings.")


if __name__ == "__main__":
    import selectors
    # Windows Python 3.8+ defaults to ProactorEventLoop which psycopg (async) cannot use.
    # Force SelectorEventLoop for compatibility.
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
