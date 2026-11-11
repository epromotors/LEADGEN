import asyncio
import selectors
import json
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select
from dotenv import dotenv_values

from app.config import settings
from app.models import Lead, EmailCorrection, EmailAssociationStatus
from app.routers.email_verification import reverify_lead_ownership_and_deliverability

async def run_step1():
    # 1. Connect to intended leadgen_release_sandbox database
    import os
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_vars = dotenv_values(env_path)
    db_url = env_vars.get("DATABASE_URL")
    print(f"Configured DATABASE_URL: {db_url}")

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Check current database and user
        res_info = await session.execute(text("SELECT current_database(), current_user, inet_server_port();"))
        db_name, db_user, db_port = res_info.fetchone()
        print(f"\n--- DATABASE CONNECTION INFO ---")
        print(f"Database: {db_name}")
        print(f"User:     {db_user}")
        print(f"Port:     {db_port}")
        assert db_name == "leadgen_release_sandbox", f"Expected leadgen_release_sandbox, got {db_name}"

        # 2. Find Paradigm Logistics India
        stmt = select(Lead).where(Lead.website.ilike("%paradigmindia.in%"))
        res = await session.execute(stmt)
        paradigm = res.scalar_one_or_none()

        if not paradigm:
            stmt2 = select(Lead).where(Lead.business_name.ilike("%Paradigm%"))
            res2 = await session.execute(stmt2)
            paradigm = res2.scalar_one_or_none()

        print(f"\n--- PARADIGM BEFORE RE-VERIFY ---")
        if not paradigm:
            print("Paradigm lead NOT FOUND!")
            return

        print(f"Lead ID:                   {paradigm.id}")
        print(f"Business Name:             {paradigm.business_name}")
        print(f"Website:                   {paradigm.website}")
        print(f"Website Domain:            {paradigm.website_domain}")
        print(f"Primary Email:             {paradigm.email}")
        print(f"Email Domain:              {paradigm.email_domain}")
        print(f"Domain Match:              {paradigm.email_domain_match}")
        print(f"Association Status:        {paradigm.email_business_association_status}")
        print(f"Association Reason:        {paradigm.email_association_reason}")
        print(f"Verification Status:       {paradigm.email_verification_status}")
        print(f"Is Quarantined:            {paradigm.is_quarantined}")
        print(f"Quarantine Reason:         {paradigm.quarantine_reason}")
        print(f"Candidates Count:          {len(paradigm.email_candidates or [])}")
        print(f"Discovered Candidates:     {json.dumps(paradigm.email_candidates, indent=2)}")

        # Check existing corrections for this lead
        stmt_corr = select(EmailCorrection).where(EmailCorrection.lead_id == paradigm.id)
        res_corr = await session.execute(stmt_corr)
        corrections = res_corr.scalars().all()
        print(f"Correction History Count:  {len(corrections)}")
        for c in corrections:
            print(f"  Correction: {c.old_email} -> {c.new_email} | status: {c.status} | source: {c.source}")

        # 3. Invoke actual authenticated re-verification workflow
        print(f"\n--- EXECUTING RE-VERIFY WORKFLOW ON PARADIGM ---")
        reverify_result = await reverify_lead_ownership_and_deliverability(
            lead=paradigm,
            db=session,
            website_scrape_enabled=True,
            dry_run=False,
        )
        print(f"Re-verify Result: {json.dumps(reverify_result, indent=2)}")

        # 4. Re-query after re-verification
        res_after = await session.execute(select(Lead).where(Lead.id == paradigm.id))
        paradigm_after = res_after.scalar_one()

        print(f"\n--- PARADIGM AFTER RE-VERIFY ---")
        print(f"Lead ID:                   {paradigm_after.id}")
        print(f"Business Name:             {paradigm_after.business_name}")
        print(f"Website:                   {paradigm_after.website}")
        print(f"Website Domain:            {paradigm_after.website_domain}")
        print(f"Primary Email:             {paradigm_after.email}")
        print(f"Email Domain:              {paradigm_after.email_domain}")
        print(f"Domain Match:              {paradigm_after.email_domain_match}")
        print(f"Association Status:        {paradigm_after.email_business_association_status}")
        print(f"Association Reason:        {paradigm_after.email_association_reason}")
        print(f"Verification Status:       {paradigm_after.email_verification_status}")
        print(f"Is Sendable:               {paradigm_after.email_verification_details.get('is_sendable') if paradigm_after.email_verification_details else False}")
        print(f"Is Quarantined:            {paradigm_after.is_quarantined}")
        print(f"Quarantine Reason:         {paradigm_after.quarantine_reason}")
        print(f"Verified At:               {paradigm_after.email_verified_at}")
        print(f"Email Source URL:          {paradigm_after.email_source_url}")
        print(f"Candidates Count:          {len(paradigm_after.email_candidates or [])}")

        res_corr_after = await session.execute(select(EmailCorrection).where(EmailCorrection.lead_id == paradigm.id))
        corrections_after = res_corr_after.scalars().all()
        print(f"Updated Correction History Count: {len(corrections_after)}")
        for c in corrections_after:
            print(f"  Audit Record: {c.old_email} -> {c.new_email} | status: {c.status} | source: {c.source} | detected_at: {c.detected_at}")

    await engine.dispose()

if __name__ == "__main__":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_step1())
    finally:
        loop.close()
