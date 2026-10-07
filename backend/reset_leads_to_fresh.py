"""
reset_leads_to_fresh.py  —  LeadGen OS complete reset utility
=============================================================
Follows the exact system rules and lifecycle documented in:
- AGENT_MASTER.md (Guardrail #27: Fresh requires audit.status == done)
- ARCHITECTURE.md (Fresh = never emailed [last_emailed_at is NULL] + audit.status == done)
- SYSTEM.md (lead.status = audited for audit.status=done; new otherwise; clean stale running audits)

Actions performed safely:
1. Clears last_emailed_at, replied_at, reply_snippet, reply_type on all leads.
2. Cleans stale audits stuck in 'running' state (> 30 min old) -> marks them 'failed'.
3. Sets lead.status = 'audited' for all leads where audit.status == 'done'.
4. Sets lead.status = 'new' for all other leads (no completed audit).
5. Resets any paused/sending campaigns back to 'draft' with clean counts (0 sent, 0 skipped, 0 failed).

Usage (from LEADGEN/backend/):
    python reset_leads_to_fresh.py
"""

import asyncio
import selectors
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select, update, func
from app.database import AsyncSessionLocal
from app.models import Lead, Audit, AuditStatus, LeadStatus, Campaign, CampaignStatus, ActivityLog
from app.logger import setup_logging
import logging

setup_logging()
logger = logging.getLogger("reset_leads")


async def main():
    print("=" * 65)
    print("LeadGen OS — Reset All Leads & Campaigns to Fresh (Never Sent)")
    print("=" * 65)

    async with AsyncSessionLocal() as db:
        # ── 1. Check current lead distribution ─────────────────────────────────
        res_before = await db.execute(
            select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
        )
        before_counts = dict(res_before.all())
        emailed_res = await db.execute(
            select(func.count(Lead.id)).where(Lead.last_emailed_at.isnot(None))
        )
        before_emailed = emailed_res.scalar_one()

        print("\nCurrent Lead States:")
        for status, count in before_counts.items():
            name = status.value if hasattr(status, "value") else str(status)
            print(f"  - {name}: {count:,}")
        print(f"  - Leads with last_emailed_at set: {before_emailed:,}")

        # ── 2. Clean stale audits stuck in 'running' (>30 min) per SYSTEM.md ──
        thirty_mins_ago = datetime.utcnow() - timedelta(minutes=30)
        stale_audits_res = await db.execute(
            update(Audit)
            .where(Audit.status == AuditStatus.running, Audit.created_at < thirty_mins_ago)
            .values(status=AuditStatus.failed, error_message="Audit timed out (stale recovery)")
        )
        if stale_audits_res.rowcount:
            print(f"  - Cleaned {stale_audits_res.rowcount} stale running audits -> marked 'failed'")

        # ── 3. Reset email & reply tracking on ALL leads ──────────────────────
        # ARCHITECTURE.md: Fresh = never emailed (last_emailed_at is NULL)
        await db.execute(
            update(Lead).values(
                last_emailed_at=None,
                replied_at=None,
                reply_snippet=None,
                reply_type=None,
            )
        )

        # ── 4. Set lead.status based on audit completion (Guardrail #27) ──────
        # Leads with a successfully completed audit -> 'audited' (campaign-ready)
        audited_lead_ids = select(Audit.lead_id).where(Audit.status == AuditStatus.done)
        res_audited = await db.execute(
            update(Lead)
            .where(Lead.id.in_(audited_lead_ids))
            .values(status=LeadStatus.audited)
        )

        # Leads without a completed audit -> 'new'
        res_new = await db.execute(
            update(Lead)
            .where(~Lead.id.in_(audited_lead_ids))
            .values(status=LeadStatus.new)
        )

        # ── 5. Reset any active/paused campaigns to clean draft state ─────────
        res_camps = await db.execute(
            select(Campaign).where(Campaign.status.in_([CampaignStatus.paused, CampaignStatus.sending]))
        )
        active_campaigns = res_camps.scalars().all()
        for camp in active_campaigns:
            camp.status = CampaignStatus.draft
            camp.sent_count = 0
            camp.skipped_count = 0
            camp.failed_count = 0
            camp.pending_lead_ids = []
            camp.next_email_at = None
            camp.paused_at = None
            print(f"  - Reset campaign '{camp.name}' to 'draft' (all counts cleared)")

        # ── 6. Log system activity ────────────────────────────────────────────
        db.add(ActivityLog(
            event_type="leads_reset_to_fresh",
            message=f"Reset all leads to fresh never-sent state. {res_audited.rowcount} audited (ready), {res_new.rowcount} new.",
        ))
        await db.commit()

        # ── 7. Verify and display results ─────────────────────────────────────
        res_after = await db.execute(
            select(Lead.status, func.count(Lead.id)).group_by(Lead.status)
        )
        after_counts = dict(res_after.all())
        emailed_after = await db.execute(
            select(func.count(Lead.id)).where(Lead.last_emailed_at.isnot(None))
        )

        print("\n" + "=" * 65)
        print("RESET SUCCESSFUL — Safe System Verification:")
        print("=" * 65)
        for status, count in after_counts.items():
            name = status.value if hasattr(status, "value") else str(status)
            print(f"  • {name.upper()}: {count:,}")
        print(f"  • Leads with last_emailed_at set: {emailed_after.scalar_one():,} (MUST BE 0)")
        print(f"  • Ready-to-send Fresh leads: {after_counts.get(LeadStatus.audited, 0):,}")
        print("=" * 65)
        print("All leads are now fresh, never-sent, and ready for outreach.\n")


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
