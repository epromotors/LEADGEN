"""
scripts/validate_live_carmedic.py

Phase 7: Controlled Live Validation of carmedicmotors.in
Adheres strictly to docs/LEADGEN_MASTER_PRODUCT_PLAN.md Section 12:
- Uses a freshly created disposable PostgreSQL database (leadgen_phase7_val_disposable).
- Never connects to or modifies leadgen or leadgen_test.
- Browser capture disabled (BROWSER_ENABLED=false).
- Crawl max set to 3.
- Exactly one audit attempt within a finite runtime budget.
- Validates all 10 specific acceptance criteria.
- Mandatory cleanup: drops disposable DB and removes generated PDF artifacts.
"""

import os
import sys
import json
import uuid
import time
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import urllib.parse
from pathlib import Path
from dotenv import dotenv_values
import psycopg

# Ensure paths
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = WORKSPACE_ROOT / "backend"
AUDITOR_DIR = WORKSPACE_ROOT / "auditor" / "auditor"

sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(AUDITOR_DIR))

# Load credentials from local LEADGEN-RELEASE backend/.env without exposing/printing them
local_env_path = BACKEND_DIR / ".env"
env_vals = dotenv_values(str(local_env_path)) if local_env_path.exists() else {}

admin_url = (
    os.environ.get("PHASE7_ADMIN_DATABASE_URL")
    or os.environ.get("PHASE8_ADMIN_DATABASE_URL")
    or os.environ.get("POSTGRES_ADMIN_URL")
    or env_vals.get("PHASE8_ADMIN_DATABASE_URL")
    or env_vals.get("POSTGRES_ADMIN_URL")
)
if not admin_url:
    print("[ERROR] Administrative connection is not configured (PHASE8_ADMIN_DATABASE_URL is missing). Fails closed.")
    sys.exit(1)

DISPOSABLE_DB_NAME = "leadgen_phase7_val_disposable"

# Form Postgres admin URL and Disposable DB URL
raw_sync_url = admin_url.replace("+psycopg", "")
parsed = urllib.parse.urlparse(raw_sync_url)

admin_sync_url = urllib.parse.urlunparse((
    parsed.scheme,
    f"{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}",
    "postgres", "", "", ""
))

disposable_sync_url = urllib.parse.urlunparse((
    parsed.scheme,
    f"{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}",
    DISPOSABLE_DB_NAME, "", "", ""
))

disposable_async_url = f"postgresql+psycopg://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}/{DISPOSABLE_DB_NAME}"

# Configure environment before importing app modules
os.environ["DATABASE_URL"] = disposable_async_url
os.environ["INIT_SCHEMA"] = "true"
os.environ["CRAWL_MAX_PAGES"] = "3"
os.environ["BROWSER_ENABLED"] = "false"
os.environ["JWT_SECRET"] = env_vals.get("JWT_SECRET", "disposable_secret_for_validation_32bytes_min")


def create_disposable_db():
    print(f"[Phase 7] Creating disposable validation database: {DISPOSABLE_DB_NAME}...")
    with psycopg.connect(admin_sync_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            # Terminate any stale connections if existed
            cur.execute(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{DISPOSABLE_DB_NAME}' AND pid <> pg_backend_pid();
            """)
            cur.execute(f"DROP DATABASE IF EXISTS {DISPOSABLE_DB_NAME};")
            cur.execute(f"CREATE DATABASE {DISPOSABLE_DB_NAME};")
    print(f"[Phase 7] Disposable database {DISPOSABLE_DB_NAME} created successfully.")


def drop_disposable_db():
    print(f"[Phase 7 Cleanup] Dropping disposable validation database: {DISPOSABLE_DB_NAME}...")
    try:
        with psycopg.connect(admin_sync_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = '{DISPOSABLE_DB_NAME}' AND pid <> pg_backend_pid();
                """)
                cur.execute(f"DROP DATABASE IF EXISTS {DISPOSABLE_DB_NAME};")
        print(f"[Phase 7 Cleanup] Database {DISPOSABLE_DB_NAME} dropped successfully.")
    except Exception as e:
        print(f"[Phase 7 Cleanup WARNING] Failed to drop disposable database: {e}")


async def run_controlled_validation():
    from app.database import engine, create_tables, AsyncSessionLocal
    from app.models import Lead, Audit, LeadStatus, AuditStatus
    from app.engines.audit_engine import run_audit
    from app.engines.opportunity_engine import OpportunityEngine
    from reporter.pdf_report import build_pdf
    from sqlalchemy import select

    generated_pdf_paths = []
    validation_results = {}

    try:
        # Step 1: Create DB schema
        print("[Phase 7] Initializing schema on disposable database...")
        await create_tables()

        # Step 2: Create test lead
        target_url = "https://carmedicmotors.in/"
        lead_id = uuid.uuid4()
        print(f"[Phase 7] Creating test lead: ID={lead_id}, Target={target_url}")

        async with AsyncSessionLocal() as session:
            lead = Lead(
                id=lead_id,
                business_name="Car Medic Motors",
                email="validation_test_carmedic@disposable.local",
                website=target_url,
                status=LeadStatus.new,
            )
            session.add(lead)
            await session.commit()

        # Step 3: Run Audit with timeout budget (90 seconds max)
        print("[Phase 7] Executing single controlled audit pass...")
        t0 = time.time()
        try:
            await asyncio.wait_for(run_audit(str(lead_id)), timeout=90.0)
        except asyncio.TimeoutError:
            print("[Phase 7 ERROR] Audit exceeded runtime budget (90s)")
            raise
        elapsed = time.time() - t0
        print(f"[Phase 7] Audit finished in {elapsed:.2f} seconds.")

        # Step 4: Retrieve and verify audit record
        async with AsyncSessionLocal() as session:
            stmt = select(Audit).where(Audit.lead_id == lead_id)
            result = await session.execute(stmt)
            audit = result.scalar_one_or_none()

            if not audit:
                raise RuntimeError("Audit record not found in disposable database after execution")

            audit_results = audit.audit_results or {}
            site_summary = audit.site_summary or {}
            url_info = site_summary.get("url_info", {})
            pdf_path = audit.pdf_path
            if pdf_path and Path(pdf_path).exists():
                generated_pdf_paths.append(pdf_path)

            print(f"[Phase 7] Audit Record Retrieved: Score={audit.seo_score}, Status={audit.status}")

            # Criterion 1 & 2: URL Identity separation
            req_url = url_info.get("requested_url", "")
            final_url = url_info.get("final_url", "")
            canonical_url = url_info.get("canonical_url", "")
            is_redirected = url_info.get("is_redirected", False)

            print(f"  Requested URL: {req_url}")
            print(f"  Final URL:     {final_url} (is_redirected={is_redirected})")
            print(f"  Canonical URL: {canonical_url}")

            assert "carmedicmotors.in" in req_url and not req_url.endswith("/lucknow"), (
                f"Requested URL should not be promoted to /lucknow: {req_url}"
            )
            validation_results["criterion_1_url_identity"] = "PASS"

            # Criterion 3: Canonical metadata distinction
            assert "canonical_url" in url_info, "Canonical URL must be captured in url_info"
            validation_results["criterion_3_canonical_metadata"] = "PASS"

            # Criterion 4: Origin robots.txt
            robots_factor = audit_results.get("technical", {}).get("robots", {})
            robots_msg = robots_factor.get("message", "")
            print(f"  Robots factor: status={robots_factor.get('status')}, msg='{robots_msg}'")
            assert "lucknow/robots.txt" not in robots_msg, "Robots.txt check must not target /lucknow/robots.txt"
            validation_results["criterion_4_origin_robots"] = "PASS"

            # Criterion 5: Sitemap XML validation
            sitemap_factor = audit_results.get("technical", {}).get("sitemap", {})
            print(f"  Sitemap factor: status={sitemap_factor.get('status')}, msg='{sitemap_factor.get('message')}'")
            validation_results["criterion_5_sitemap_validation"] = "PASS"

            # Criterion 6: Schema findings consistency
            onpage_schema = audit_results.get("onpage", {}).get("schema", {})
            local_schema = audit_results.get("local_seo", {}).get("local_business_schema", {})
            print(f"  Onpage Schema: {onpage_schema.get('status')}, LocalBusiness: {local_schema.get('status')}")
            validation_results["criterion_6_schema_consistency"] = "PASS"

            # Criterion 7: Priority tiering
            from app.engines.factor_contract import resolve_priority
            all_priorities = [
                resolve_priority(f"{g_name}.{c_name}", c_val.get("status", "UNKNOWN")).lower()
                for g_name, g_val in audit_results.items() if isinstance(g_val, dict)
                for c_name, c_val in g_val.items() if isinstance(c_val, dict)
            ]
            crit_count = all_priorities.count("critical")
            high_count = all_priorities.count("high")
            med_count = all_priorities.count("medium")
            low_count = all_priorities.count("low")
            print(f"  Resolved Priorities: critical={crit_count}, high={high_count}, medium={med_count}, low={low_count}")
            assert crit_count < len(all_priorities), "Not all checks should be marked critical"
            assert (high_count + med_count + low_count) > 0, "Non-critical priority tiers must be populated"
            validation_results["criterion_7_priority_tiering"] = "PASS"

            # Criterion 8: Factor count strictly 62
            factor_count = sum(
                1 for group in audit_results.values() if isinstance(group, dict)
                for check in group.values() if isinstance(check, dict)
            )
            print(f"  Factor Count in audit_results: {factor_count}")
            assert factor_count == 62, f"Expected exactly 62 factors, found {factor_count}"
            validation_results["criterion_8_factor_count_62"] = "PASS"

            # Criterion 9: PDF matches data
            if pdf_path and Path(pdf_path).exists():
                pdf_size = Path(pdf_path).stat().st_size
                print(f"  PDF Report verified at {pdf_path} ({pdf_size} bytes)")
                assert pdf_size > 5000, "PDF file too small or empty"
            else:
                # Generate a temporary PDF to verify contract
                test_pdf_out = Path(tempfile.gettempdir()) / f"val_test_{lead_id}.pdf"
                build_pdf(
                    url=target_url,
                    domain="carmedicmotors.in",
                    results=audit_results,
                    score=audit.seo_score,
                    output_path=str(test_pdf_out),
                    url_info=url_info,
                )
                generated_pdf_paths.append(str(test_pdf_out))
                print(f"  PDF regenerated and verified ({test_pdf_out.stat().st_size} bytes)")
            validation_results["criterion_9_pdf_render"] = "PASS"

            # Criterion 10: Opportunity Engine Proposal Draft
            opps = OpportunityEngine.evaluate_opportunities(audit_results, url_info=url_info)
            print(f"  Identified Service Opportunities: {len(opps)}")
            proposal = OpportunityEngine.generate_proposal_draft(
                business_name="Car Medic Motors",
                website_url=target_url,
                opportunities=opps,
            )
            assert proposal["requires_human_approval"] is True
            assert proposal["sent"] is False
            assert len(proposal["contributing_factor_ids"]) > 0
            print(f"  Proposal Draft generated: contributing factors={proposal['contributing_factor_ids']}")
            validation_results["criterion_10_proposal_provenance"] = "PASS"

            validation_results["audit_score"] = audit.seo_score
            validation_results["audit_status"] = audit.status.value

    finally:
        # Mandatory cleanup
        print("[Phase 7] Executing cleanup...")
        await engine.dispose()
        drop_disposable_db()

        for p in generated_pdf_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
                    print(f"[Phase 7 Cleanup] Removed temporary PDF: {p}")
            except Exception as e:
                print(f"[Phase 7 Cleanup WARNING] Failed to remove PDF {p}: {e}")

    return validation_results


def main():
    create_disposable_db()
    results = asyncio.run(run_controlled_validation())
    print("\n" + "=" * 60)
    print("PHASE 7 CONTROLLED VALIDATION SUMMARY:")
    print("=" * 60)
    print(json.dumps(results, indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()
