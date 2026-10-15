"""
backend/app/routers/ai_search.py

FastAPI router for AI-Search Readiness and Visibility Monitoring.
Supports:
- Truthful connection and monitoring status
- On-demand visibility runs via the Perplexity Agent API
- Historical runs inspection and latest result retrieval
- Readiness heuristics and standardized query corpus generation
"""

import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Audit, Lead
from app.services.ai_search_service import AiSearchMonitoringService
from app.services.ai_search_provider import normalize_domain

router = APIRouter(prefix="/ai-search", tags=["ai_search"])
_ai_search_service = AiSearchMonitoringService()


class QueryCorpusRequest(BaseModel):
    brand_name: str
    domain: str
    city: Optional[str] = None
    services: Optional[List[str]] = None


class RunVisibilityCheckRequest(BaseModel):
    lead_id: Optional[str] = None
    domain: Optional[str] = None
    brand_name: Optional[str] = None
    city: Optional[str] = None
    services: Optional[List[str]] = None
    brand_aliases: Optional[List[str]] = None
    competitors: Optional[List[Dict[str, str]]] = None
    query_budget: Optional[int] = 10


@router.get("/status", summary="Get AI-Search visibility monitoring status")
async def get_monitoring_status():
    """
    Return connection status, active provider, model, query cap, and monitoring statistics.
    Never exposes API keys or secrets.
    """
    return _ai_search_service.get_visibility_monitoring_status()


@router.post("/run", summary="Trigger an on-demand AI-search visibility check")
async def run_visibility_check(
    payload: RunVisibilityCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Execute an on-demand AI visibility check using the Perplexity Agent API.
    Enforces a strict query budget cap and returns verifiable citation/mention evidence.
    """
    if not _ai_search_service.is_provider_configured():
        raise HTTPException(
            status_code=400,
            detail=(
                "AI-Search provider is not configured. "
                "Set AI_SEARCH_PROVIDER_KEY in the server environment to enable live visibility monitoring."
            ),
        )

    brand_name = payload.brand_name
    domain = payload.domain
    city = payload.city
    services = payload.services

    if payload.lead_id:
        try:
            lead_uuid = uuid.UUID(payload.lead_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid lead_id format.")

        result = await db.execute(select(Lead).where(Lead.id == lead_uuid))
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found.")

        if not brand_name:
            brand_name = lead.business_name
        if not domain:
            domain = lead.website

    if not domain:
        raise HTTPException(status_code=400, detail="Domain or valid lead_id is required.")

    if not brand_name:
        brand_name = normalize_domain(domain).split(".")[0].capitalize()

    try:
        run_record = await _ai_search_service.execute_visibility_run(
            lead_id=payload.lead_id,
            brand_name=brand_name,
            domain=domain,
            city=city,
            services=services,
            brand_aliases=payload.brand_aliases,
            competitors=payload.competitors,
            query_budget=payload.query_budget or 10,
        )
        return run_record
    except RuntimeError as ex:
        raise HTTPException(status_code=409, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Visibility check failed: {str(ex)}")


@router.get("/history/{lead_id}", summary="Get historical visibility check runs for a lead")
async def get_visibility_history(lead_id: str):
    """
    Retrieve historical visibility check runs for a specific lead.
    """
    history = _ai_search_service.get_history(lead_id)
    return {"lead_id": lead_id, "total_runs": len(history), "runs": history}


@router.get("/latest/{lead_id}", summary="Get the latest visibility check run for a lead")
async def get_latest_visibility_run(lead_id: str):
    """
    Retrieve the most recent visibility check run with full evidence.
    """
    latest = _ai_search_service.get_latest_run(lead_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No visibility check runs found for this lead.")
    return latest


@router.get("/readiness/{lead_id}", summary="Get AI-Search readiness evaluation for an audited lead")
async def get_readiness_evaluation(lead_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Audit).where(Audit.lead_id == lead_id))
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found for this lead.")

    audit_results = audit.audit_results or {}
    robots_factor = audit_results.get("technical", {}).get("robots", {})
    robots_text = robots_factor.get("message", "")

    return AiSearchMonitoringService.evaluate_ai_readiness_heuristics(
        audit_results=audit_results,
        robots_text=robots_text,
        has_llms_txt=False,
    )


@router.post("/query-corpus", summary="Generate standard query corpus for AI search monitoring")
async def generate_query_corpus(payload: QueryCorpusRequest):
    corpus = _ai_search_service.build_standard_query_corpus(
        brand_name=payload.brand_name,
        domain=payload.domain,
        city=payload.city,
        services=payload.services,
    )
    return {"queries": corpus, "count": len(corpus)}
