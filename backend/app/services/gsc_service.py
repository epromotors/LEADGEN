"""
backend/app/services/gsc_service.py

Google Search Console (GSC) Integration Service.
Implements Domain C of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Optional OAuth-authorized read-only integration (scope: webmasters.readonly).
- Secure token handling: never logs or leaks tokens; masks credentials in status outputs.
- Property selection: enumerates verified site URLs.
- Real search performance retrieval: clicks, impressions, CTR, position by query/page/country/device/date.
- Strict disconnected state: returns clear unconfigured/disconnected status without fabricating data.
- Handles empty data, missing permissions, and disconnected states truthfully.
"""

import os
import json
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GSC_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"


class GSCService:
    """Manages Google Search Console authentication, property discovery, and performance metrics."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("GSC_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("GSC_CLIENT_SECRET", "")
        self.redirect_uri = redirect_uri or os.environ.get(
            "GSC_REDIRECT_URI", "http://localhost:8000/api/gsc/oauth/callback"
        )
        # In-memory storage for authorized session tokens (keyed by user/lead/domain)
        self._token_store: Dict[str, Dict[str, Any]] = {}

    def is_configured(self) -> bool:
        """Returns True only if OAuth client credentials are configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: str = "default") -> Dict[str, Any]:
        """
        Generate standard Google OAuth2 authorization URL with read-only scope.
        Returns disconnected status if client credentials are not configured.
        """
        if not self.is_configured():
            return {
                "configured": False,
                "authorization_url": None,
                "message": "GSC client credentials (GSC_CLIENT_ID, GSC_CLIENT_SECRET) are not configured.",
            }

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GSC_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{GSC_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
        return {
            "configured": True,
            "authorization_url": auth_url,
            "scope": GSC_READONLY_SCOPE,
            "message": "Authorization URL generated for read-only Search Console access.",
        }

    def exchange_code_for_tokens(self, code: str, property_key: str = "default") -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.is_configured():
            return {"success": False, "error": "GSC credentials not configured."}

        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            resp = requests.post(GSC_TOKEN_ENDPOINT, data=payload, timeout=10)
            if resp.status_code != 200:
                logger.error("GSC token exchange failed: HTTP %s", resp.status_code)
                return {"success": False, "error": f"Token exchange failed: HTTP {resp.status_code}"}

            data = resp.json()
            access_token = data.get("access_token")
            refresh_token = data.get("refresh_token")
            expires_in = data.get("expires_in", 3600)

            # Store token securely without printing to logs
            self._token_store[property_key] = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info("GSC token exchange succeeded for property key: %s", property_key)
            return {
                "success": True,
                "property_key": property_key,
                "token_masked": access_token[:8] + "..." if access_token else "none",
                "scope": data.get("scope", GSC_READONLY_SCOPE),
            }
        except Exception as e:
            logger.error("GSC token exchange exception: %s", e)
            return {"success": False, "error": str(e)}

    def store_token(self, property_key: str, access_token: str, refresh_token: Optional[str] = None) -> None:
        """Directly store an authorized token (e.g. from tests or secure database store)."""
        self._token_store[property_key] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_connection_status(self, property_key: str = "default") -> Dict[str, Any]:
        """
        Return the truthful connection status for the given property key.
        Returns disconnected state if unconfigured or no active token.
        """
        if not self.is_configured():
            return {
                "connected": False,
                "status": "unconfigured",
                "reason": "Search Console integration requires GSC_CLIENT_ID and GSC_CLIENT_SECRET environment settings.",
                "property": None,
                "available_properties": [],
            }

        token_data = self._token_store.get(property_key)
        if not token_data or not token_data.get("access_token"):
            return {
                "connected": False,
                "status": "disconnected",
                "reason": "Search Console is not connected for this property. Authorization required.",
                "property": None,
                "available_properties": [],
            }

        return {
            "connected": True,
            "status": "connected",
            "reason": "Connected with authorized read-only OAuth credentials.",
            "property": property_key,
            "token_masked": token_data["access_token"][:8] + "...",
        }

    def list_properties(self, property_key: str = "default") -> Dict[str, Any]:
        """List verified sites/properties in Google Search Console for the authorized user."""
        status = self.get_connection_status(property_key)
        if not status["connected"]:
            return {
                "success": False,
                "properties": [],
                "error": status["reason"],
            }

        access_token = self._token_store[property_key]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(f"{GSC_API_BASE}/sites", headers=headers, timeout=10)
            if resp.status_code != 200:
                return {
                    "success": False,
                    "properties": [],
                    "error": f"Failed to list properties: HTTP {resp.status_code}",
                }
            sites_data = resp.json().get("siteEntry", [])
            properties = [
                {
                    "site_url": s.get("siteUrl"),
                    "permission_level": s.get("permissionLevel"),
                }
                for s in sites_data
            ]
            return {"success": True, "properties": properties}
        except Exception as e:
            return {"success": False, "properties": [], "error": str(e)}

    def get_search_performance(
        self,
        site_url: str,
        property_key: str = "default",
        days: int = 28,
        dimensions: Optional[List[str]] = None,
        row_limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Query real search performance metrics (clicks, impressions, CTR, position)
        via the Search Analytics API.
        Never fabricates data; returns explicit disconnected status if not authorized.
        """
        status = self.get_connection_status(property_key)
        if not status["connected"]:
            return {
                "connected": False,
                "site_url": site_url,
                "status": "disconnected",
                "reason": status["reason"],
                "summary": None,
                "rows": [],
            }

        access_token = self._token_store[property_key]["access_token"]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days)

        body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions or ["query", "page"],
            "rowLimit": row_limit,
        }

        # URL encode siteUrl for API endpoint path
        encoded_site = urllib.parse.quote(site_url, safe="")
        endpoint = f"{GSC_API_BASE}/sites/{encoded_site}/searchAnalytics/query"

        try:
            resp = requests.post(endpoint, headers=headers, json=body, timeout=12)
            if resp.status_code == 403:
                return {
                    "connected": False,
                    "site_url": site_url,
                    "status": "forbidden",
                    "reason": f"Permission denied for property '{site_url}'. Ensure the account has verified access.",
                    "summary": None,
                    "rows": [],
                }
            if resp.status_code != 200:
                return {
                    "connected": False,
                    "site_url": site_url,
                    "status": "api_error",
                    "reason": f"Search Console API error: HTTP {resp.status_code}",
                    "summary": None,
                    "rows": [],
                }

            data = resp.json()
            raw_rows = data.get("rows", [])
            total_clicks = 0
            total_impressions = 0
            weighted_position_sum = 0.0

            formatted_rows = []
            for r in raw_rows:
                keys = r.get("keys", [])
                clicks = int(r.get("clicks", 0))
                impressions = int(r.get("impressions", 0))
                ctr = float(r.get("ctr", 0.0))
                pos = float(r.get("position", 0.0))

                total_clicks += clicks
                total_impressions += impressions
                weighted_position_sum += pos * impressions

                formatted_rows.append({
                    "keys": keys,
                    "query": keys[0] if len(keys) > 0 else None,
                    "page": keys[1] if len(keys) > 1 else None,
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": round(ctr, 4),
                    "position": round(pos, 2),
                })

            avg_ctr = round(total_clicks / total_impressions, 4) if total_impressions > 0 else 0.0
            avg_pos = round(weighted_position_sum / total_impressions, 2) if total_impressions > 0 else 0.0

            return {
                "connected": True,
                "site_url": site_url,
                "status": "active",
                "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
                "summary": {
                    "total_clicks": total_clicks,
                    "total_impressions": total_impressions,
                    "average_ctr": avg_ctr,
                    "average_position": avg_pos,
                    "row_count": len(formatted_rows),
                },
                "rows": formatted_rows,
            }
        except Exception as e:
            logger.error("GSC query exception for %s: %s", site_url, e)
            return {
                "connected": False,
                "site_url": site_url,
                "status": "exception",
                "reason": str(e),
                "summary": None,
                "rows": [],
            }
