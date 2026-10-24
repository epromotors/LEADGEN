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

from app.routers.auth import require_authorized_operator

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
    provider: Optional[str] = None


class AiObservationCreateRequest(BaseModel):
    domain: str
    query: str
    mention_status: str = "unknown"
    source_type: str = "manual"
    provider: Optional[str] = None
    engine: Optional[str] = None
    lead_id: Optional[str] = None
    brand_name: Optional[str] = None
    locale: Optional[str] = None
    observed_at: Optional[str] = None
    citation_urls: Optional[List[str]] = None
    evidence_snippet: Optional[str] = None
    notes: Optional[str] = None


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
    Execute an on-demand AI visibility check using the selected provider (Gemini, OpenRouter, or Perplexity).
    Enforces a strict query budget cap and returns verifiable citation/mention evidence.
    """
    selected_provider_id = payload.provider or _ai_search_service.get_active_provider_id()

    if not _ai_search_service.is_provider_configured(selected_provider_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"AI-Search provider '{selected_provider_id}' is not configured. "
                "Set GEMINI_API_KEY, OPENROUTER_API_KEY, or AI_SEARCH_PROVIDER_KEY in the server environment to enable live visibility monitoring."
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
            provider_name=selected_provider_id,
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


@router.post("/observations", status_code=201, summary="Record a dated AI visibility observation")
async def record_observation(
    payload: AiObservationCreateRequest,
    current_operator: dict = Depends(require_authorized_operator),
):
    try:
        record = _ai_search_service.record_observation(
            target_domain=payload.domain,
            search_query=payload.query,
            mention_status=payload.mention_status,
            source_type=payload.source_type,
            provider=payload.provider,
            engine=payload.engine,
            lead_id=payload.lead_id,
            brand_name=payload.brand_name,
            locale=payload.locale,
            observed_at=payload.observed_at,
            citation_urls=payload.citation_urls,
            evidence_snippet=payload.evidence_snippet,
            notes=payload.notes,
            created_by=current_operator.get("sub", "operator"),
        )
        return record
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/observations", summary="List dated AI visibility observations")
async def list_observations(
    lead_id: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    mention_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return _ai_search_service.get_observations(
        lead_id=lead_id,
        domain=domain,
        source_type=source_type,
        mention_status=mention_status,
        limit=limit,
        offset=offset,
    )


@router.get("/observations/compare", summary="Compare two dated AI visibility observations")
async def compare_observations(
    base_id: str = Query(..., description="Baseline observation ID"),
    target_id: str = Query(..., description="Target observation ID to compare against baseline"),
):
    try:
        return _ai_search_service.compare_observations(base_id=base_id, target_id=target_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/observations/{observation_id}", summary="Get observation by ID")
async def get_observation(observation_id: str):
    obs = _ai_search_service.get_observation_by_id(observation_id)
    if not obs:
        raise HTTPException(status_code=404, detail="Observation not found.")
    return obs


@router.get("/coverage", summary="Get AI search observation coverage summary")
async def get_coverage_summary(
    lead_id: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
):
    return _ai_search_service.get_coverage_summary(lead_id=lead_id, domain=domain)
