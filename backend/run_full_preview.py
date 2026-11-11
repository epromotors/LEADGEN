import asyncio
import selectors
import json
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text, select, and_
from dotenv import dotenv_values

from app.models import Lead, EmailCorrection, EmailAssociationStatus
from app.routers.email_verification import reverify_lead_ownership_and_deliverability, BulkReverifyRequest
from app.services.lead_discovery_service import clean_website, extract_domain_from_url, extract_email_domain

async def run_full_dry_run_preview():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    env_vars = dotenv_values(env_path)
    db_url = env_vars.get("DATABASE_URL")

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print("=================================================================", flush=True)
    print("      LEADGEN — FULL EMAIL OWNERSHIP CLEANUP DRY RUN PREVIEW      ", flush=True)
    print("=================================================================", flush=True)

    async with async_session() as session:
        # Step 1: Verify Database Identity
        res_info = await session.execute(text("SELECT current_database(), current_user, inet_server_port();"))
        db_name, db_user, db_port = res_info.fetchone()
        print(f"Database: {db_name}", flush=True)
        print(f"User:     {db_user}", flush=True)
        print(f"Port:     {db_port}", flush=True)
        assert db_name == "leadgen_release_sandbox", f"Wrong database {db_name}"

        # Fetch population
        stmt = select(Lead).order_by(Lead.created_at.desc())
        res = await session.execute(stmt)
        all_leads = res.scalars().all()
        total_leads = len(all_leads)
        print(f"Total leads in database: {total_leads}", flush=True)

        # Count initially quarantined vs active
        initially_quarantined = [l for l in all_leads if l.is_quarantined]
        initially_active = [l for l in all_leads if not l.is_quarantined]
        print(f"Initially Quarantined: {len(initially_quarantined)}", flush=True)
        print(f"Initially Active:      {len(initially_active)}", flush=True)

        # Track before state hashes/counts to prove zero writes
        pre_correction_count = await session.scalar(text("SELECT count(*) FROM email_corrections;"))
        pre_activity_count = await session.scalar(text("SELECT count(*) FROM activity_log;"))
        print(f"Pre-run email_corrections count: {pre_correction_count}", flush=True)
        print(f"Pre-run activity_log count:      {pre_activity_count}", flush=True)

        # Metrics accumulator
        total_examined = 0
        emails_matching_website = 0
        website_replacements_available = 0
        mismatched_no_replacement = 0
        external_domain_manual_review = 0
        no_usable_email = 0
        inaccessible_or_blocked = 0
        inconclusive_retryable = 0
        already_quarantined = 0
        proposed_reversible_exclusion = 0

        # Representative examples dictionary
        representative_examples = {
            "corrected": [],
            "revalidated": [],
            "manual_review": [],
            "no_email_found": [],
            "scrape_inconclusive": [],
        }

        # Process with bounded concurrency in chunks of 50
        CONCURRENCY = 20
        sem = asyncio.Semaphore(CONCURRENCY)
        CHUNK_SIZE = 50
        print(f"\nProcessing {total_leads} leads in bounded batches of {CHUNK_SIZE} with concurrency {CONCURRENCY} (Dry-Run Mode: dry_run=True)...", flush=True)

        async def reverify_worker(ld):
            async with sem:
                site_url = clean_website(ld.website)
                res_rec = await reverify_lead_ownership_and_deliverability(
                    lead=ld,
                    db=session,
                    website_scrape_enabled=bool(site_url),
                    dry_run=True,
                )
                return ld, res_rec

        for b_idx in range(0, total_leads, CHUNK_SIZE):
            chunk = all_leads[b_idx:b_idx + CHUNK_SIZE]
            tasks = [reverify_worker(ld) for ld in chunk]
            batch_results = await asyncio.gather(*tasks)

            for lead, rec_result in batch_results:
                total_examined += 1

                was_quarantined = bool(lead.is_quarantined)
                if was_quarantined:
                    already_quarantined += 1

                old_em = lead.email or ""
                old_em_dom = extract_email_domain(old_em)
                site = clean_website(lead.website)
                site_dom = extract_domain_from_url(site)

                status = rec_result["outcome_status"]
                new_em = rec_result.get("new_email") or old_em

                if status == "corrected":
                    website_replacements_available += 1
                    if len(representative_examples["corrected"]) < 5:
                        representative_examples["corrected"].append({
                            "lead_id": str(lead.id),
                            "business_name": lead.business_name,
                            "website": site,
                            "old_email": old_em,
                            "new_email": new_em,
                            "source_url": rec_result.get("evidence_url"),
                            "reason": rec_result.get("outcome_reason"),
                            "was_quarantined": was_quarantined,
                            "proposed_action": "Correct primary email to domain-matched replacement & clear quarantine if sendable",
                        })

                elif status == "revalidated":
                    emails_matching_website += 1
                    if len(representative_examples["revalidated"]) < 5:
                        representative_examples["revalidated"].append({
                            "lead_id": str(lead.id),
                            "business_name": lead.business_name,
                            "website": site,
                            "email": old_em,
                            "reason": rec_result.get("outcome_reason"),
                            "was_quarantined": was_quarantined,
                            "proposed_action": "Retain verified company email and confirm domain match",
                        })

                elif status == "manual_review":
                    external_domain_manual_review += 1
                    mismatched_no_replacement += 1
                    if not was_quarantined:
                        proposed_reversible_exclusion += 1
                    if len(representative_examples["manual_review"]) < 5:
                        representative_examples["manual_review"].append({
                            "lead_id": str(lead.id),
                            "business_name": lead.business_name,
                            "website": site,
                            "email": old_em,
                            "source_url": rec_result.get("evidence_url"),
                            "reason": rec_result.get("outcome_reason"),
                            "was_quarantined": was_quarantined,
                            "proposed_action": "Place in operator review queue under external_domain_review; do not auto-approve",
                        })

                elif status == "no_email_found":
                    no_usable_email += 1
                    if not was_quarantined:
                        proposed_reversible_exclusion += 1
                    if old_em and site_dom and old_em_dom != site_dom:
                        mismatched_no_replacement += 1
                    if len(representative_examples["no_email_found"]) < 5:
                        representative_examples["no_email_found"].append({
                            "lead_id": str(lead.id),
                            "business_name": lead.business_name,
                            "website": site,
                            "email": old_em,
                            "reason": rec_result.get("outcome_reason"),
                            "was_quarantined": was_quarantined,
                            "proposed_action": "Reversibly exclude from active outreach pool to prevent bounce risk",
                        })

                elif status == "scrape_inconclusive":
                    inconclusive_retryable += 1
                    inaccessible_or_blocked += 1
                    if len(representative_examples["scrape_inconclusive"]) < 5:
                        representative_examples["scrape_inconclusive"].append({
                            "lead_id": str(lead.id),
                            "business_name": lead.business_name,
                            "website": site,
                            "email": old_em,
                            "reason": rec_result.get("outcome_reason"),
                            "was_quarantined": was_quarantined,
                            "proposed_action": "Retain lead without deletion; schedule for retry when site recovers",
                        })

            print(f"  ... examined {min(b_idx + CHUNK_SIZE, total_leads)}/{total_leads} leads ...", flush=True)

        # Confirm zero writes were performed during dry run
        post_correction_count = await session.scalar(text("SELECT count(*) FROM email_corrections;"))
        post_activity_count = await session.scalar(text("SELECT count(*) FROM activity_log;"))
        print(f"\nPost-run email_corrections count: {post_correction_count} (Delta: {post_correction_count - pre_correction_count})")
        print(f"Post-run activity_log count:      {post_activity_count} (Delta: {post_activity_count - pre_activity_count})")
        assert post_correction_count == pre_correction_count, "DRY RUN MUTATED email_corrections!"
        assert post_activity_count == pre_activity_count, "DRY RUN MUTATED activity_log!"
        print("VERIFIED: Zero database writes occurred during dry-run preview.")

        # Print Final Counts
        print("\n=================================================================")
        print("                  DRY RUN PREVIEW REPORT COUNTS                  ")
        print("=================================================================")
        print(f"Total leads examined:                         {total_examined}")
        print(f"Emails matching website domain:               {emails_matching_website}")
        print(f"Website-confirmed replacements available:     {website_replacements_available}")
        print(f"Mismatched emails with no confirmed replace:  {mismatched_no_replacement}")
        print(f"External-domain emails requiring review:      {external_domain_manual_review}")
        print(f"Leads with no usable email:                   {no_usable_email}")
        print(f"Leads with inaccessible or blocked websites:  {inaccessible_or_blocked}")
        print(f"Inconclusive cases and retryable failures:    {inconclusive_retryable}")
        print(f"Records already quarantined:                  {already_quarantined}")
        print(f"Records proposed for reversible exclusion:    {proposed_reversible_exclusion}")

        # Save results to json for detailed reporting
        report_data = {
            "total_examined": total_examined,
            "emails_matching_website": emails_matching_website,
            "website_replacements_available": website_replacements_available,
            "mismatched_no_replacement": mismatched_no_replacement,
            "external_domain_manual_review": external_domain_manual_review,
            "no_usable_email": no_usable_email,
            "inaccessible_or_blocked": inaccessible_or_blocked,
            "inconclusive_retryable": inconclusive_retryable,
            "already_quarantined": already_quarantined,
            "proposed_reversible_exclusion": proposed_reversible_exclusion,
            "representative_examples": representative_examples,
        }
        with open("dry_run_preview_report.json", "w") as f:
            json.dump(report_data, f, indent=2)
        print("\nDetailed summary written to dry_run_preview_report.json")

    await engine.dispose()

if __name__ == "__main__":
    selector = selectors.SelectSelector()
    loop = asyncio.SelectorEventLoop(selector)
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_full_dry_run_preview())
    finally:
        loop.close()
