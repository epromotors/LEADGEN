import asyncio
import selectors
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select, func
from dotenv import dotenv_values
import os

from app.models import Lead, EmailAssociationStatus
from app.services.lead_discovery_service import clean_website, extract_domain_from_url, extract_email_domain

async def inspect_pool():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_vars = dotenv_values(env_path)
    db_url = env_vars.get("DATABASE_URL")
    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # DB confirmation
        res_info = await session.execute(text("SELECT current_database(), current_user;"))
        db_name, db_user = res_info.fetchone()
        print(f"Connected to: {db_name} as {db_user}")

        # Total leads
        total = await session.scalar(select(func.count(Lead.id)))
        has_web = await session.scalar(select(func.count(Lead.id)).where(Lead.website.isnot(None), Lead.website != ""))
        no_web = await session.scalar(select(func.count(Lead.id)).where((Lead.website.is_(None)) | (Lead.website == "")))
        quarantined = await session.scalar(select(func.count(Lead.id)).where(Lead.is_quarantined == True))
        active = await session.scalar(select(func.count(Lead.id)).where(Lead.is_quarantined == False))

        print(f"Total leads:                {total}")
        print(f"Leads with website:         {has_web}")
        print(f"Leads without website:      {no_web}")
        print(f"Currently Quarantined:      {quarantined}")
        print(f"Currently Active:           {active}")

        # Domain mismatch breakdown in memory
        res = await session.execute(select(Lead))
        all_leads = res.scalars().all()

        mismatched = []
        matched = []
        no_email = []
        for l in all_leads:
            em = (l.email or "").strip().lower()
            if not em or "@" not in em:
                no_email.append(l)
                continue
            e_dom = extract_email_domain(em)
            w_dom = extract_domain_from_url(clean_website(l.website))
            if w_dom and (e_dom == w_dom or e_dom.endswith("." + w_dom) or w_dom.endswith("." + e_dom)):
                matched.append(l)
            else:
                mismatched.append(l)

        print(f"Email matches website domain: {len(matched)}")
        print(f"Domain mismatches / external: {len(mismatched)}")
        print(f"No valid email syntax:       {len(no_email)}")

    await engine.dispose()

if __name__ == "__main__":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(inspect_pool())
    finally:
        loop.close()
