"""
backend/app/routers/gsc.py

FastAPI router for Google Search Console integration, OAuth2 lifecycle, and performance reporting.
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
    state: Optional[str] = None


@router.get("/status", summary="Get Google Search Console connection status")
async def get_gsc_status(property_key: str = Query("default")):
    return _gsc_service.get_connection_status(property_key=property_key)


@router.get("/auth-url", summary="Get GSC OAuth authorization URL")
async def get_auth_url(
    property_key: str = Query("default", description="Domain or account identifier"),
    state: Optional[str] = Query(None, description="Optional custom state nonce"),
):
    return _gsc_service.get_authorization_url(property_key=property_key, state=state)


@router.get("/oauth/callback", summary="Google OAuth2 redirect callback endpoint")
async def gsc_oauth_callback(
    code: Optional[str] = Query(None, description="Google OAuth authorization code"),
    state: Optional[str] = Query(None, description="OAuth state nonce"),
    error: Optional[str] = Query(None, description="Google OAuth error (e.g. access_denied)"),
    error_description: Optional[str] = Query(None, description="Google OAuth error description"),
):
    """
    Handles user redirect from Google OAuth consent flow:
    - Verifies user denial or error and returns honest failure without leaking secrets.
    - Validates and consumes the single-use state nonce to guard against CSRF and replay attacks.
    - Exchanges authorization code for read-only Search Console tokens.
    """
    if error:
        denial = _gsc_service.handle_oauth_denial(error, error_description)
        raise HTTPException(
            status_code=400,
            detail=denial["message"],
        )

    if not state:
        raise HTTPException(status_code=400, detail="Missing required OAuth state parameter.")

    validation = _gsc_service.validate_and_consume_state(state)
    if not validation["valid"]:
        raise HTTPException(status_code=400, detail=validation["reason"])

    if not code:
        raise HTTPException(status_code=400, detail="Missing required authorization code.")

    property_key = validation.get("property_key", "default")
    res = _gsc_service.exchange_code_for_tokens(
        code=code,
        property_key=property_key,
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Token exchange failed."))

    return {
        "success": True,
        "property_key": property_key,
        "token_masked": res.get("token_masked"),
        "scope": res.get("scope"),
        "message": "Google Search Console connected successfully.",
    }


@router.post("/oauth/exchange", summary="Exchange authorization code for tokens")
async def exchange_token(payload: GSCTokenExchangeRequest):
    if payload.state:
        validation = _gsc_service.validate_and_consume_state(payload.state)
        if not validation["valid"]:
            raise HTTPException(status_code=400, detail=validation["reason"])
        property_key = validation.get("property_key", payload.property_key)
    else:
        property_key = payload.property_key

    res = _gsc_service.exchange_code_for_tokens(
        code=payload.code,
        property_key=property_key,
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
