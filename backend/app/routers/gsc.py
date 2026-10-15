"""
backend/app/routers/gsc.py

FastAPI router for Google Search Console integration and status reporting.
"""

from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from app.services.gsc_service import GSCService

router = APIRouter(prefix="/gsc", tags=["gsc"])
_gsc_service = GSCService()


class GSCTokenExchangeRequest(BaseModel):
    code: str
    property_key: str = "default"


@router.get("/status", summary="Get Google Search Console connection status")
async def get_gsc_status(property_key: str = Query("default")):
    return _gsc_service.get_connection_status(property_key=property_key)


@router.get("/auth-url", summary="Get GSC OAuth authorization URL")
async def get_auth_url(state: str = Query("default")):
    return _gsc_service.get_authorization_url(state=state)


@router.post("/oauth/exchange", summary="Exchange authorization code for tokens")
async def exchange_token(payload: GSCTokenExchangeRequest):
    res = _gsc_service.exchange_code_for_tokens(
        code=payload.code,
        property_key=payload.property_key,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Token exchange failed"))
    return res


@router.get("/properties", summary="List verified properties in Search Console")
async def list_properties(property_key: str = Query("default")):
    res = _gsc_service.list_properties(property_key=property_key)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to list properties"))
    return res


@router.get("/performance", summary="Get search performance analytics")
async def get_search_performance(
    site_url: str = Query(..., description="Target site URL"),
    property_key: str = Query("default"),
    days: int = Query(28, ge=1, le=90),
):
    return _gsc_service.get_search_performance(
        site_url=site_url,
        property_key=property_key,
        days=days,
    )
