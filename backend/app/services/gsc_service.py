"""
backend/app/services/gsc_service.py

Google Search Console (GSC) Integration Service.
Implements Domain C of docs/LEADGEN_MASTER_PRODUCT_PLAN.md:
- Optional OAuth-authorized read-only integration (scope: webmasters.readonly).
- Secure token handling: never logs or leaks tokens; masks credentials in status outputs.
- Authenticated-encryption token persistence across process restarts using Fernet (AES-128-CBC + HMAC).
- Secure OAuth state nonce generation, server-side store, exact validation, and one-time consumption.
- Configurable redirect URI aligning with backend host and port 8001.
- Property selection: enumerates verified site URLs.
- Real search performance retrieval: clicks, impressions, CTR, position by query/page/country/device/date.
- Strict disconnected state: returns clear unconfigured/disconnected status without fabricating data.
- Handles authorization denial, token revocation, expired tokens, and API errors truthfully.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import requests
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

GSC_READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
GSC_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GSC_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
DEFAULT_GSC_REDIRECT_URI = "http://localhost:8001/gsc/oauth/callback"


class GSCService:
    """Manages Google Search Console authentication, property discovery, and performance metrics."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        storage_path: Optional[str] = None,
        encryption_key: Optional[str] = None,
    ):
        self.client_id = client_id or os.environ.get("GSC_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("GSC_CLIENT_SECRET", "")
        self.redirect_uri = (
            redirect_uri
            or os.environ.get("GSC_REDIRECT_URI", "")
            or DEFAULT_GSC_REDIRECT_URI
        )
        self.storage_path = (
            storage_path
            or os.environ.get("GSC_CREDENTIALS_FILE", "")
            or "reports/.gsc_credentials.enc"
        )
        self.encryption_key = (
            encryption_key
            or os.environ.get("GSC_ENCRYPTION_KEY", "")
            or os.environ.get("JWT_SECRET", "")
        )

        # In-memory storage for authorized session tokens (keyed by property_key)
        self._token_store: Dict[str, Dict[str, Any]] = {}
        # Short-lived server-side storage for OAuth state nonces
        self._state_store: Dict[str, Dict[str, Any]] = {}

        # Restore persisted credentials if present
        self._load_from_disk()

    def is_configured(self) -> bool:
        """Returns True only if OAuth client credentials are configured."""
        return bool(self.client_id and self.client_secret)

    def _get_fernet(self) -> Fernet:
        """
        Derive an authenticated-encryption Fernet key from the configured secret.
        Prefers dedicated GSC_ENCRYPTION_KEY.
        Falls back to JWT_SECRET if GSC_ENCRYPTION_KEY is unset (with documented rotation implications:
        rotating JWT_SECRET will invalidate persisted GSC tokens unless GSC_ENCRYPTION_KEY is preserved).
        Prohibits any silent fallback to an insecure or hardcoded default secret.
        """
        raw_key = (self.encryption_key or "").strip()
        if not raw_key:
            raw_key = os.environ.get("GSC_ENCRYPTION_KEY", "").strip()
        if not raw_key:
            raw_key = os.environ.get("JWT_SECRET", "").strip()

        if not raw_key:
            raise ValueError(
                "GSC token encryption requires GSC_ENCRYPTION_KEY or JWT_SECRET to be configured. "
                "Insecure default secret fallbacks are prohibited."
            )

        derived_32 = hashlib.sha256(raw_key.encode("utf-8")).digest()
        urlsafe_key = base64.urlsafe_b64encode(derived_32)
        return Fernet(urlsafe_key)

    def _save_to_disk(self) -> None:
        """Safely encrypt and persist all authorized tokens to disk with restrictive owner permissions."""
        if not self.storage_path:
            return
        try:
            fernet = self._get_fernet()
        except ValueError as e:
            logger.warning("GSC token persistence skipped: %s", e)
            return

        try:
            target_dir = os.path.dirname(os.path.abspath(self.storage_path))
            os.makedirs(target_dir, exist_ok=True)

            serialized: Dict[str, Any] = {}
            for k, v in self._token_store.items():
                exp = v.get("expires_at")
                if isinstance(exp, datetime):
                    exp_str = exp.isoformat()
                else:
                    exp_str = exp
                serialized[k] = {
                    "access_token": v.get("access_token"),
                    "refresh_token": v.get("refresh_token"),
                    "scope": v.get("scope", GSC_READONLY_SCOPE),
                    "status": v.get("status", "active"),
                    "expires_at": exp_str,
                    "created_at": v.get("created_at"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            plaintext_bytes = json.dumps(serialized).encode("utf-8")
            encrypted_bytes = fernet.encrypt(plaintext_bytes)

            tmp_path = f"{self.storage_path}.tmp"
            # Write with owner-only restrictive permissions (0o600)
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            fd = os.open(tmp_path, flags, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(encrypted_bytes)
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.storage_path)
            logger.debug("Encrypted GSC tokens persisted to %s", self.storage_path)
        except Exception as e:
            logger.error("Failed to persist encrypted GSC tokens: %s", type(e).__name__)

    def _load_from_disk(self) -> None:
        """Load and decrypt persisted tokens from storage_path."""
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        try:
            fernet = self._get_fernet()
        except ValueError as e:
            logger.warning("GSC token restoration skipped: %s", e)
            return

        try:
            with open(self.storage_path, "rb") as f:
                encrypted_bytes = f.read()
            if not encrypted_bytes:
                return
            plaintext_bytes = fernet.decrypt(encrypted_bytes)
            data = json.loads(plaintext_bytes.decode("utf-8"))
            for k, v in data.items():
                exp_str = v.get("expires_at")
                exp_dt = None
                if exp_str:
                    try:
                        exp_dt = datetime.fromisoformat(exp_str)
                    except Exception:
                        exp_dt = None
                self._token_store[k] = {
                    "access_token": v.get("access_token"),
                    "refresh_token": v.get("refresh_token"),
                    "scope": v.get("scope", GSC_READONLY_SCOPE),
                    "status": v.get("status", "active"),
                    "expires_at": exp_dt,
                    "created_at": v.get("created_at"),
                }
            logger.info("Restored %d GSC token profiles from encrypted store.", len(data))
        except InvalidToken:
            logger.warning("Failed to decrypt GSC tokens: invalid or changed encryption key.")
        except Exception as e:
            logger.warning("Failed to load encrypted GSC tokens: %s", type(e).__name__)

    def generate_state(self, property_key: str = "default", ttl_seconds: int = 600) -> str:
        """Generate a cryptographically secure random state nonce bound to a property_key."""
        self._cleanup_expired_states()
        nonce = secrets.token_urlsafe(32)
        self._state_store[nonce] = {
            "property_key": property_key,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        }
        return nonce

    def validate_and_consume_state(self, state: Optional[str]) -> Dict[str, Any]:
        """
        Validate and consume state nonce (one-time use to prevent replay).
        Returns {'valid': True, 'property_key': ...} or {'valid': False, 'reason': ...}.
        """
        if not state or not isinstance(state, str):
            return {"valid": False, "reason": "Missing or invalid OAuth state parameter."}
        if state not in self._state_store:
            return {"valid": False, "reason": "Invalid, replayed, or unrecognized OAuth state nonce."}
        entry = self._state_store.pop(state)  # One-time consumption
        self._cleanup_expired_states()
        if datetime.now(timezone.utc) > entry["expires_at"]:
            return {"valid": False, "reason": "OAuth state nonce has expired."}
        return {"valid": True, "property_key": entry["property_key"]}

    def _cleanup_expired_states(self) -> None:
        """Prune expired nonces from memory."""
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._state_store.items() if now > v["expires_at"]]
        for k in expired:
            self._state_store.pop(k, None)

    def get_authorization_url(self, property_key: str = "default", state: Optional[str] = None) -> Dict[str, Any]:
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

        # If caller passed explicit state, register it; otherwise generate secure random nonce
        if state:
            self._state_store[state] = {
                "property_key": property_key,
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=600),
            }
            nonce = state
        else:
            nonce = self.generate_state(property_key=property_key)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": GSC_READONLY_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": nonce,
        }
        auth_url = f"{GSC_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
        return {
            "configured": True,
            "authorization_url": auth_url,
            "scope": GSC_READONLY_SCOPE,
            "state": nonce,
            "redirect_uri": self.redirect_uri,
            "message": "Authorization URL generated for read-only Search Console access.",
        }

    def handle_oauth_denial(self, error: str, error_description: Optional[str] = None) -> Dict[str, Any]:
        """Handle user authorization denial cleanly without exposing credentials."""
        logger.warning("GSC authorization denied: %s (%s)", error, error_description or "")
        return {
            "success": False,
            "status": "denied",
            "error": error,
            "message": error_description or "Google Search Console authorization was cancelled or denied by user.",
        }

    def exchange_code_for_tokens(
        self,
        code: str,
        property_key: str = "default",
        state: Optional[str] = None,
        validate_state: bool = False,
    ) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if validate_state or state:
            validation = self.validate_and_consume_state(state)
            if not validation["valid"]:
                return {"success": False, "error": validation["reason"]}
            property_key = validation.get("property_key") or property_key

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

            # Store token securely without printing in logs
            self._token_store[property_key] = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "scope": data.get("scope", GSC_READONLY_SCOPE),
                "status": "active",
                "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_to_disk()
            logger.info("GSC token exchange succeeded for property key: %s", property_key)
            return {
                "success": True,
                "property_key": property_key,
                "has_token": bool(access_token),
                "token_type": "Bearer",
                "scope": data.get("scope", GSC_READONLY_SCOPE),
            }
        except Exception as e:
            logger.error("GSC token exchange exception: %s", type(e).__name__)
            return {"success": False, "error": str(e)}

    def store_token(
        self,
        property_key: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: int = 3600,
    ) -> None:
        """Directly store an authorized token and persist encrypted."""
        self._token_store[property_key] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "scope": GSC_READONLY_SCOPE,
            "status": "active",
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_to_disk()

    def refresh_token_if_needed(self, property_key: str) -> bool:
        """Refresh access token if expired or near expiry using refresh token."""
        token_data = self._token_store.get(property_key)
        if not token_data or not token_data.get("refresh_token"):
            return False

        exp = token_data.get("expires_at")
        now = datetime.now(timezone.utc)
        if exp and (exp - now).total_seconds() > 60:
            return True  # Still valid

        if not self.is_configured():
            return False

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(GSC_TOKEN_ENDPOINT, data=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                new_access = data.get("access_token")
                expires_in = data.get("expires_in", 3600)
                token_data["access_token"] = new_access
                token_data["expires_at"] = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                token_data["status"] = "active"
                self._save_to_disk()
                logger.info("Successfully refreshed GSC access token for property: %s", property_key)
                return True
            elif resp.status_code in (400, 401):
                logger.warning("GSC refresh token revoked or invalid (HTTP %s) for property: %s", resp.status_code, property_key)
                token_data["status"] = "revoked"
                self._save_to_disk()
                return False
            else:
                logger.warning("GSC token refresh error HTTP %s for property: %s", resp.status_code, property_key)
                return False
        except Exception as e:
            logger.error("GSC token refresh exception: %s", type(e).__name__)
            return False

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
                "available_properties": list(self._token_store.keys()),
            }

        token_data = self._token_store.get(property_key)
        if not token_data or not token_data.get("access_token"):
            return {
                "connected": False,
                "status": "disconnected",
                "reason": "Search Console is not connected for this property. Authorization required.",
                "property": None,
                "available_properties": list(self._token_store.keys()),
            }

        status_val = token_data.get("status", "active")
        if status_val == "revoked":
            return {
                "connected": False,
                "status": "revoked",
                "reason": "Search Console authorization has been revoked or refresh failed.",
                "property": property_key,
                "available_properties": list(self._token_store.keys()),
            }

        exp = token_data.get("expires_at")
        if exp and datetime.now(timezone.utc) > exp and not token_data.get("refresh_token"):
            return {
                "connected": False,
                "status": "expired",
                "reason": "Search Console access token has expired and no refresh token is available.",
                "property": property_key,
                "available_properties": list(self._token_store.keys()),
            }

        return {
            "connected": True,
            "status": "connected",
            "reason": "Connected with authorized read-only OAuth credentials.",
            "property": property_key,
            "has_token": True,
            "token_type": "Bearer",
            "scope": token_data.get("scope", GSC_READONLY_SCOPE),
            "available_properties": list(self._token_store.keys()),
        }

    def list_properties(self, property_key: str = "default") -> Dict[str, Any]:
        """List verified sites/properties in Google Search Console for the authorized user."""
        self.refresh_token_if_needed(property_key)
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
        self.refresh_token_if_needed(property_key)
        status = self.get_connection_status(property_key)
        if not status["connected"]:
            return {
                "connected": False,
                "site_url": site_url,
                "status": status.get("status", "disconnected"),
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
            logger.error("GSC query exception for %s: %s", site_url, type(e).__name__)
            return {
                "connected": False,
                "site_url": site_url,
                "status": "exception",
                "reason": str(e),
                "summary": None,
                "rows": [],
            }
