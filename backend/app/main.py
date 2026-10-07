import sys
import asyncio
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_tables
from app.logger import setup_logging          # ← IST rotating file logger
from app.routers import auth, leads, audits, campaigns, activity, replies, email_review

# ── Logging must be configured FIRST, before anything writes a log line ───────
setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create DB tables on startup."""
    logger.info("=" * 60)
    logger.info("TEB Solutions LeadGen OS starting up (v4.1.0)")
    logger.info("=" * 60)
    await create_tables()
    logger.info("Database tables ready.")
    yield
    logger.info("LeadGen OS shutting down.")


app = FastAPI(
    title="TEB Solutions LeadGen API",
    description=(
        "Lead Generation, Automated SEO Audit & Outreach SaaS — "
        "Internal Use Only"
    ),
    version="4.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5174", "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Logger Middleware ──────────────────────────────────────
@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Log every API request with method, path, status, and elapsed time (IST)."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Skip noisy health-check and static asset paths
    skip_paths = {"/", "/health", "/favicon.ico"}
    if request.url.path not in skip_paths:
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "HTTP %s %s → %d  (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(audits.router)
app.include_router(campaigns.router)
app.include_router(activity.router)
app.include_router(replies.router)
app.include_router(email_review.router)


# ── Frontend client-side error sink ─────────────────────────────────────────
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))
_fe_logger = logging.getLogger("frontend")


class FrontendLogEntry(BaseModel):
    level:   str            # "error" | "warn" | "info"
    message: str
    context: Optional[str] = None   # URL, component name, etc.


@app.post("/api/logs/frontend", tags=["logs"], summary="Frontend error sink")
async def receive_frontend_log(entry: FrontendLogEntry):
    """
    Accepts structured log entries from the React frontend and writes them
    into the same rotating IST log file as the backend.
    """
    ist_ts = datetime.now(tz=IST).strftime("%Y-%m-%d %H:%M:%S IST")
    level_map = {"error": logging.ERROR, "warn": logging.WARNING, "info": logging.INFO}
    lvl = level_map.get(entry.level.lower(), logging.INFO)

    ctx = f" [{entry.context}]" if entry.context else ""
    _fe_logger.log(lvl, "[BROWSER]%s %s", ctx, entry.message)
    return {"ok": True}


@app.get("/", tags=["health"])
async def root():
    return {
        "app": settings.APP_NAME,
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
