import asyncio
import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=20,        # base connections kept open
    max_overflow=40,     # extra connections allowed under load (total cap: 60)
    pool_timeout=30,     # seconds to wait for a connection before raising
    pool_recycle=1800,   # recycle connections every 30 min to avoid stale sockets
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency: yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Protected databases that must NEVER receive startup schema mutations or DDL
PROTECTED_DATABASES = frozenset({
    "leadgen",
    "leadgen_test",
    "leads_db",
    "linkgen",
    "offpage",
    "leadgen_release_sandbox",
    "postgres",
    "template0",
    "template1",
})


async def create_tables():
    """Called at startup to create tables and apply small idempotent schema updates."""
    if not settings.INIT_SCHEMA:
        logger.info("Schema initialization skipped (INIT_SCHEMA=False).")
        return

    async with engine.begin() as conn:
        # Safeguard: ensure startup schema initialization never runs against protected or ordinary business databases
        res = await conn.execute(text("SELECT current_database(), current_user"))
        curr_db = None
        if hasattr(res, "fetchone"):
            row = res.fetchone()
            if not asyncio.iscoroutine(row) and row:
                curr_db = row[0]
        elif hasattr(res, "scalar"):
            val = res.scalar()
            if not asyncio.iscoroutine(val):
                curr_db = val

        if curr_db and curr_db in PROTECTED_DATABASES:
            logger.error(
                "SCHEMA MUTATION BLOCKED: Target database '%s' is protected or contains ordinary business data. Refusing startup schema mutation.",
                curr_db,
            )
            raise RuntimeError(
                f"SCHEMA MUTATION BLOCKED: Refusing to run create_tables against protected or business database '{curr_db}'. "
                f"Use versioned migrations for monitored schema changes."
            )

        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_canonical BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_page_title BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_meta_desc BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_og_tags BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_lazy_load BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_contact BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_whatsapp BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS has_trust BOOLEAN"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS country_code VARCHAR(10)"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS currency_code VARCHAR(10)"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS currency_symbol VARCHAR(10)"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS detected_via VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS seo_score INTEGER"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS audited_url VARCHAR(500)"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS audit_results JSON"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS site_summary JSON"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS page_audits JSON"))
        await conn.execute(text("ALTER TABLE audits ADD COLUMN IF NOT EXISTS audit_lifecycle VARCHAR(20) NOT NULL DEFAULT 'PENDING'"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source_url VARCHAR(500)"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_source_type VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_extraction_method VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_domain VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_domain VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_domain_match BOOLEAN"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_business_association_status VARCHAR(50) DEFAULT 'unverified_association'"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_association_reason TEXT"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_association_status VARCHAR(50) DEFAULT 'unverified'"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS website_candidates JSON"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS email_candidates JSON"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS is_quarantined BOOLEAN NOT NULL DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS quarantine_reason TEXT"))
        await conn.execute(text("ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS campaign_type VARCHAR(50) DEFAULT 'generic_first_contact'"))


async def verify_runtime_database_role():
    """Verify that the active runtime database connection does not execute as PostgreSQL superuser."""
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT rolname, rolsuper FROM pg_roles WHERE rolname = current_user;"))
            if hasattr(res, "fetchone"):
                row = res.fetchone()
                if not asyncio.iscoroutine(row) and row:
                    user, is_super = row[0], row[1]
                    if is_super:
                        logger.warning(
                            "SECURITY WARNING: Runtime application is connected as PostgreSQL superuser '%s'. "
                            "A restricted application role (e.g. leadgen_release_app) must be used for ordinary operations.",
                            user,
                        )
                    else:
                        logger.info("Runtime database connection verified with restricted role '%s' (superuser=False).", user)
    except Exception as e:
        logger.warning("Runtime database role verification notice: %s", e)

