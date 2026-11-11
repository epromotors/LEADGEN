"""
send_test_email.py  —  LeadGen OS test email sender
=====================================================
Fetches a lead with an audit from the DB, renders the 260-template
niche copy (Batches 1-3), and sends it to a specified address.

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
from app.models import Lead, Audit, ActivityLog
from app.services.email_limit_service import claim_global_email_capacity_atomic, GLOBAL_DAILY_EMAIL_CAP
from app.engines.outreach_engine import _send_email_sync, classify_smtp_error
from app.services.template_renderer import TemplateRenderer
from app.services.niche_router import classify_lead_niche
from app.config import settings
from app.logger import setup_logging
import logging

setup_logging()
logger = logging.getLogger("test_email")

TO_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "epromotors@gmail.com"


async def fetch_best_lead():
    """
    Pick the best lead for the test:
    1. Prefer leads with an audit record (so segment audit evidence is populated)
    2. Has an email address
    3. Auto-classifies niche on the fly if unclassified
    """
    async with AsyncSessionLocal() as db:
        # 1. First try: lead with audit and email
        result = await db.execute(
            select(Lead, Audit)
            .join(Audit, Audit.lead_id == Lead.id)
            .where(Lead.email.isnot(None))
            .where(Lead.email != "")
            .where(Lead.website.isnot(None))
            .where(Lead.website != "")
            .order_by(Lead.niche_id.desc().nullslast())
            .limit(1)
        )
        row = result.first()
        if row:
            lead, audit = row
        else:
            # 2. Fallback: any lead with an email
            result2 = await db.execute(
                select(Lead)
                .where(Lead.email.isnot(None))
                .where(Lead.email != "")
                .order_by(Lead.niche_id.desc().nullslast())
                .limit(1)
            )
            lead = result2.scalar_one_or_none()
            audit = None

        if lead and not lead.niche_id and lead.business_name:
            nid, kw, conf = classify_lead_niche(lead.business_name, getattr(lead, "category", None))
            if nid and conf >= 2:
                lead.niche_id = nid
                lead.niche_keyword = kw
                lead.niche_confidence = conf
                lead_to_update = await db.get(Lead, lead.id)
                if lead_to_update:
                    lead_to_update.niche_id = nid
                    lead_to_update.niche_keyword = kw
                    lead_to_update.niche_confidence = conf
                    await db.commit()

        return lead, audit


async def main():
    logger.info("=" * 55)
    logger.info("LeadGen OS — Niche Template Test Send")
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
    logger.info(f"Niche ID    : {getattr(lead, 'niche_id', None)} ({getattr(lead, 'niche_keyword', 'n/a')})")

    # ── Fetch sender account ──────────────────────────────────────────────────
    accounts = settings.get_smtp_accounts()
    if not accounts:
        logger.error("No SMTP accounts configured in .env (SMTP_SENDERS is empty).")
        print("\n  ❌  SMTP not configured. Check backend/.env → SMTP_SENDERS.")
        return

    account = accounts[0]
    logger.info(f"Sending via : {account['email']} @ {account['smtp_host']}:{account['smtp_port']}")

    # ── Build email using TemplateRenderer (Batches 1-3 Niche Library) ─────────
    try:
        rendered = TemplateRenderer.render_campaign_email(
            template=None,
            subject_template=None,
            lead=lead,
            audit=audit,
            campaign_type="niche_outreach",
            sender_account=account,
        )
    except Exception as exc:
        logger.error("Failed to render email via TemplateRenderer: %s", exc)
        return

    subject = f"{rendered['subject']} [TEST]"
    plain_body = rendered["plain_body"]
    html_body = rendered["html_body"]
    strategy = rendered.get("content_strategy", "niche_rendered")

    logger.info(f"Strategy    : {strategy}")
    logger.info(f"Subject     : {subject}")
    logger.info(f"Plain-text size: {len(plain_body):,} characters")

    # ── Send ───────────────────────────────────────────────────────────────────
    # Enforce global daily email limit (1,000/day in Asia/Kolkata) across all accounts
    async with AsyncSessionLocal() as db:
        can_send, current_sent, remaining = await claim_global_email_capacity_atomic(db, 1)
        if not can_send:
            logger.error(
                "Global daily email limit (%d/day in Asia/Kolkata) reached across all sender accounts. "
                "Sent today: %d, remaining: 0.",
                GLOBAL_DAILY_EMAIL_CAP,
                current_sent,
            )
            print(f"\n  ❌  Daily email limit reached ({current_sent}/{GLOBAL_DAILY_EMAIL_CAP} sent today). Resets at IST midnight.")
            return

    # Override To: address to the test recipient
    success, error = _send_email_sync(account, TO_EMAIL, subject, html_body, plain_body=plain_body)

    if success:
        logger.info("Test email sent OK to %s", TO_EMAIL)
        # Durable audit logging of test email send
        try:
            async with AsyncSessionLocal() as db:
                test_log = ActivityLog(
                    event_type="test_email_sent",
                    lead_id=lead.id if lead else None,
                    message=f"Test email sent to {TO_EMAIL} via {account['email']} | Subject: {subject}",
                )
                db.add(test_log)
                await db.commit()
        except Exception as log_err:
            logger.warning("Could not log test email to ActivityLog: %s", log_err)

        print(f"\n  [OK]  Test email sent to {TO_EMAIL}")
        print(f"      Strategy: {strategy}")
        print(f"      Subject : {subject}")
        print(f"      Lead    : {lead.business_name} ({lead.website})")
        print(f"      Sent via: {account['email']}")
        print()
        print("  If it landed in Spam, your domain reputation may need")
        print("  warming up or SPF/DKIM tuning.")
    else:
        err_info = classify_smtp_error(error)
        logger.error("Send failed [%s]: %s", err_info["category"], err_info["sanitized_message"])
        print(f"\n  [FAIL]  Send failed: {err_info['sanitized_message']}")
        if err_info["category"] == "sender_configuration":
            print(f"          Sender account: {account['email']}")
            print("          Operator Action: Check Hostinger hPanel -> Emails for tebsolutions.in.")
            print("          Verify that this mailbox is active, its email plan is not expired,")
            print("          and that sender ownership or aliases are configured.")
        elif err_info["category"] == "authentication":
            print("          Operator Action: Verify SMTP password in backend/.env matches the Hostinger mailbox.")
        print()


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
