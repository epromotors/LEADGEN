from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import settings

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


async def create_tables():
    """Called at startup to create tables and apply small idempotent schema updates."""
    async with engine.begin() as conn:
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
