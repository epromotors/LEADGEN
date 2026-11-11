"""
backend/app/routers/api_usage.py

API Usage, Credit Visibility & Quota Diagnostics Router:
- Returns unified visibility for all scraping, discovery, AI inference, and audit engine services.
- Exposes safe, read-only refresh without consuming paid credits.
- Completely redacts all secrets (API keys, passwords, bearer tokens).
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers.auth import require_authorized_operator
from app.services.api_usage_service import ApiUsageService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_authorized_operator)],
)

_service = ApiUsageService()


@router.get("/api-usage", summary="Get comprehensive API usage, credit balances, and quota status")
async def get_api_usage(
    force_refresh: bool = Query(False, description="Bypass cache for read-only balance endpoints"),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns unified diagnostic information across:
    1. Scraping & Lead Discovery Providers (Serper, Treg, Hunter, etc.)
    2. AI Inference & Search Visibility Providers (Groq, Gemini, OpenRouter)
    3. SEO Audit Engine Activity (Local crawler, Playwright, Lighthouse, external audit APIs)
    4. Outbound Email Global Cap (1,000/day in Asia/Kolkata across all SMTP accounts)
    
    Guarantees:
    - Never prints or exposes secret API keys.
    - Never executes paid search or audit queries to check health.
    - Distinguishes authoritative provider-reported balances from local request counters.
    """
    return await _service.get_overview(db, force_refresh=force_refresh)
