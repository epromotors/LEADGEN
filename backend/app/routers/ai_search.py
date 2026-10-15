"""
backend/app/routers/ai_search.py

FastAPI router for AI-Search Readiness and Visibility Monitoring.
"""

import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Audit, Lead
from app.services.ai_search_service import AiSearchMonitoringService

router = APIRouter(prefix="/ai-search", tags=["ai_search"])
_ai_search_service = AiSearchMonitoringService()


class QueryCorpusRequest(BaseModel):
    brand_name: str
    domain: str
    city: Optional[str] = None
    services: Optional[List[str]] = None


@router.get("/status", summary="Get AI-Search visibility monitoring status")
async def get_monitoring_status():
    return _ai_search_service.get_visibility_monitoring_status()


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
