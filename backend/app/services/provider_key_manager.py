"""
backend/app/services/provider_key_manager.py

Account-Aware Provider Key Rotation & Independent Quota Management System:
- Independent multi-key pools for Groq, Treg, Serper, and discovery/AI providers.
- Internal Credential Registry associating each configured key with:
    * provider (e.g. 'groq', 'treg', 'serper')
    * credential_slot (1, 2, ...)
    * quota_scope (e.g. 'groq_account_1', 'groq_account_2')
- Non-secret identifiers (e.g. 'groq_account_1') used in logs, provenance, and UI. Never exposes raw keys.
- Supports both numbered configuration (PROVIDER_KEY_1, PROVIDER_KEY_2) and legacy aliases (PROVIDER_KEY).
- Independent Account Quotas:
    * Exhausting account 1 does NOT disable account 2 if they belong to different quota scopes.
    * Multiple keys sharing the same quota scope correctly share that quota boundary.
- Failure classification distinguishing:
    * 'credential_invalid' (401/403: auth failure, disables key only)
    * 'quota_exhausted' (402: payment/quota exhausted, disables quota scope)
    * 'rate_limited' (429: temporary RPM/RPS rate limit, cooldown applied)
    * 'transient_failure' (5xx / timeouts: brief backoff)
    * 'available' (healthy, eligible)
- Concurrency-safe round-robin selection (async and thread locks).
- Cooldown and Retry-After handling.
- Bounded retries and strict secret redaction across all surfaces.
"""

import asyncio
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

# Substrings identifying placeholder credentials
PLACEHOLDER_SUBSTRINGS = (
    "paste_",
    "your_",
    "changeme",
    "replace_with_",
    "trg_live_paste_",
    "example",
)


class QuotaScope:
    """
    Represents an independent account/project quota boundary for a provider.
    Associated with a non-secret identifier (e.g. 'groq_account_1', 'groq_account_2').
    Never stores or exposes secrets.
    """

    def __init__(self, scope_id: str, provider: str):
        self.scope_id: str = scope_id.strip()
        self.provider: str = provider.lower().strip()
        self.is_exhausted: bool = False
        self.cooldown_until: float = 0.0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_status_code: Optional[int] = None
        self.last_error_category: Optional[str] = None
        self.last_used_timestamp: Optional[float] = None
        self.remaining_quota: Optional[int] = None
        self.quota_reset_at: Optional[float] = None

    def is_available(self) -> bool:
        """True if scope is not exhausted and not currently cooling down."""
        return not self.is_exhausted and time.time() >= self.cooldown_until

    def is_in_cooldown(self) -> bool:
        """True if scope is currently in a temporary rate-limit cooldown window."""
        return time.time() < self.cooldown_until

    def set_cooldown(self, seconds: float):
        """Set temporary cooldown window."""
        self.cooldown_until = max(self.cooldown_until, time.time() + max(1.0, seconds))

    def reset(self):
        """Reset state for tests."""
        self.is_exhausted = False
        self.cooldown_until = 0.0
        self.success_count = 0
        self.failure_count = 0
        self.last_status_code = None
        self.last_error_category = None
        self.last_used_timestamp = None
        self.remaining_quota = None
        self.quota_reset_at = None

    def __repr__(self) -> str:
        return (
            f"<QuotaScope id={self.scope_id} provider={self.provider} "
            f"exhausted={self.is_exhausted} in_cooldown={self.is_in_cooldown()}>"
        )


class ProviderKey:
    """Represents a single API key slot within a provider's key pool."""

    def __init__(
        self,
        slot_id: int,
        secret: str,
        provider: str,
        quota_scope: QuotaScope,
    ):
        self.slot_id: int = slot_id
        self._secret: str = secret.strip()
        self.provider: str = provider.lower().strip()
        self.quota_scope: QuotaScope = quota_scope
        self.account_id: str = quota_scope.scope_id  # Non-secret identifier, e.g. "groq_account_1"
        self.is_healthy: bool = True
        self.is_auth_failed: bool = False  # Set on credential-specific failure (401/403)
        self.cooldown_until: float = 0.0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_status_code: Optional[int] = None
        self.last_error_category: Optional[str] = None
        self.last_used_timestamp: Optional[float] = None

    @property
    def secret(self) -> str:
        """Access raw key secret. Protected and never printed."""
        return self._secret

    @property
    def is_exhausted(self) -> bool:
        """True if credential auth failed or its account quota scope is exhausted."""
        return self.is_auth_failed or self.quota_scope.is_exhausted

    @is_exhausted.setter
    def is_exhausted(self, val: bool):
        self.is_auth_failed = val

    def is_in_cooldown(self) -> bool:
        """Check if key or its quota scope is temporarily cooling down."""
        return time.time() < self.cooldown_until or self.quota_scope.is_in_cooldown()

    def is_available(self) -> bool:
        """True if key is healthy, auth is valid, not cooling down, and scope is available."""
        return (
            self.is_healthy
            and not self.is_auth_failed
            and time.time() >= self.cooldown_until
            and self.quota_scope.is_available()
        )

    def set_cooldown(self, seconds: float):
        """Set temporary cooldown on both key slot and its quota scope."""
        cd = max(1.0, seconds)
        self.cooldown_until = max(self.cooldown_until, time.time() + cd)
        self.quota_scope.set_cooldown(cd)

    def reset(self):
        """Reset state for tests."""
        self.is_healthy = True
        self.is_auth_failed = False
        self.cooldown_until = 0.0
        self.success_count = 0
        self.failure_count = 0
        self.last_status_code = None
        self.last_error_category = None
        self.last_used_timestamp = None
        self.quota_scope.reset()

    def __repr__(self) -> str:
        # Strictly sanitized — never prints the secret
        return (
            f"<ProviderKey slot={self.slot_id} account={self.account_id} "
            f"healthy={self.is_healthy} auth_failed={self.is_auth_failed} "
            f"scope_exhausted={self.quota_scope.is_exhausted}>"
        )

    def __str__(self) -> str:
        return f"ProviderKey(slot={self.slot_id}, account={self.account_id})"


class ProviderKeyPool:
    """
    Manages an independent pool of keys for a specific provider.
    Enforces account-aware round-robin rotation, concurrency safety,
    independent quota scopes, and detailed health tracking.
    """

    def __init__(
        self,
        provider_name: str,
        raw_keys: Optional[List[str]] = None,
        quota_scopes: Optional[List[str]] = None,
    ):
        self.provider_name: str = provider_name.lower().strip()
        self.keys: List[ProviderKey] = []
        self.quota_scopes: Dict[str, QuotaScope] = {}
        self._manual_shared_exhausted: bool = False
        self._cursor: int = 0
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.Lock()

        if raw_keys:
            self.configure_keys(raw_keys, quota_scopes=quota_scopes)

    @property
    def shared_quota_exhausted(self) -> bool:
        """True if ALL configured quota scopes for this provider are exhausted."""
        if self._manual_shared_exhausted:
            return True
        if not self.quota_scopes:
            return False
        return all(scope.is_exhausted for scope in self.quota_scopes.values())

    @shared_quota_exhausted.setter
    def shared_quota_exhausted(self, val: bool):
        self._manual_shared_exhausted = val
        if val:
            for scope in self.quota_scopes.values():
                scope.is_exhausted = True

    @property
    def shared_cooldown_until(self) -> float:
        """Max cooldown timestamp among cooling quota scopes."""
        if not self.quota_scopes:
            return 0.0
        return max((scope.cooldown_until for scope in self.quota_scopes.values()), default=0.0)

    def is_shared_cooling_down(self) -> bool:
        """True only if ALL non-exhausted quota scopes are currently cooling down."""
        active_scopes = [s for s in self.quota_scopes.values() if not s.is_exhausted]
        if not active_scopes:
            return False
        return all(s.is_in_cooldown() for s in active_scopes)

    def get_or_create_scope(self, scope_id: str) -> QuotaScope:
        """Get or register an account quota scope by non-secret identifier."""
        clean_id = scope_id.strip() if scope_id else f"{self.provider_name}_account_1"
        if clean_id not in self.quota_scopes:
            self.quota_scopes[clean_id] = QuotaScope(clean_id, self.provider_name)
        return self.quota_scopes[clean_id]

    def configure_keys(
        self,
        raw_keys: List[str],
        quota_scopes: Optional[List[str]] = None,
    ):
        """
        Configure pool keys with account-aware quota scopes:
        - Filters empty, whitespace, and placeholder keys.
        - Deduplicates identical keys while preserving first-seen slot ordering.
        - Assigns 1-indexed slot IDs.
        - Associates each key with its account quota scope (default: {provider}_account_{slot}).
        """
        self.keys.clear()
        self.quota_scopes.clear()
        self._manual_shared_exhausted = False
        self._cursor = 0

        seen_secrets: Set[str] = set()
        slot = 1

        for idx, raw in enumerate(raw_keys):
            if not raw or not isinstance(raw, str):
                continue
            cleaned = raw.strip()
            if not cleaned or len(cleaned) < 8:
                continue
            lower_val = cleaned.lower()
            if any(ph in lower_val for ph in PLACEHOLDER_SUBSTRINGS):
                continue
            if cleaned in seen_secrets:
                continue

            seen_secrets.add(cleaned)

            # Determine quota scope for this key slot
            if quota_scopes and idx < len(quota_scopes) and quota_scopes[idx]:
                scope_id = quota_scopes[idx].strip()
            else:
                scope_id = f"{self.provider_name}_account_{slot}"

            scope = self.get_or_create_scope(scope_id)
            self.keys.append(
                ProviderKey(
                    slot_id=slot,
                    secret=cleaned,
                    provider=self.provider_name,
                    quota_scope=scope,
                )
            )
            slot += 1

        logger.info(
            "[ProviderKeyPool:%s] Initialized with %d configured key slot(s) across %d quota scope(s)",
            self.provider_name,
            len(self.keys),
            len(self.quota_scopes),
        )

    def is_configured(self) -> bool:
        return len(self.keys) > 0

    async def get_next_key(self) -> Optional[Tuple[ProviderKey, int]]:
        """
        Concurrency-safe asynchronous round-robin key selection.
        Returns (ProviderKey, slot_id) or None if no eligible keys are available.
        """
        async with self._async_lock:
            return self._select_candidate_key()

    def get_next_key_sync(self) -> Optional[Tuple[ProviderKey, int]]:
        """
        Concurrency-safe synchronous round-robin key selection.
        Returns (ProviderKey, slot_id) or None if no eligible keys are available.
        """
        with self._thread_lock:
            return self._select_candidate_key()

    def _select_candidate_key(self) -> Optional[Tuple[ProviderKey, int]]:
        """
        Internal key selection logic:
        1. Filters strictly eligible keys (valid auth, key not cooling, quota scope not exhausted/cooling).
        2. Applies fair round-robin rotation among eligible keys.
        3. Updates last_used_timestamp on chosen key and its quota scope.
        """
        if not self.keys:
            return None

        # Stop if all quota scopes are exhausted
        if self.shared_quota_exhausted:
            logger.debug(
                "[ProviderKeyPool:%s] All quota scopes are exhausted; skipping requests.",
                self.provider_name,
            )
            return None

        # Find eligible keys: key is available and its quota scope is available
        eligible = [k for k in self.keys if k.is_available()]
        if not eligible:
            logger.debug(
                "[ProviderKeyPool:%s] No eligible keys currently available. Total slots: %d",
                self.provider_name,
                len(self.keys),
            )
            return None

        # Round-robin selection among eligible keys
        idx = self._cursor % len(eligible)
        self._cursor += 1
        chosen = eligible[idx]

        now = time.time()
        chosen.last_used_timestamp = now
        chosen.quota_scope.last_used_timestamp = now

        return chosen, chosen.slot_id

    def report_result(
        self,
        key: ProviderKey,
        status_code: int,
        retry_after: Optional[float] = None,
        is_shared_quota: bool = False,
        error_message: Optional[str] = None,
        quota_exhausted: bool = False,
    ):
        """
        Update key and account quota scope state based on HTTP status code.
        Distinguishes:
        - 2xx: Success
        - 401/403: 'credential_invalid' (disables specific key only)
        - 402 / quota_exhausted: 'quota_exhausted' (disables account quota scope)
        - 429: 'rate_limited' (sets cooldown on account and key)
        - 5xx / 0: 'transient_failure' (brief bounded backoff)
        Never logs or exposes secret keys.
        """
        key.last_status_code = status_code
        key.quota_scope.last_status_code = status_code

        # 2xx Success
        if 200 <= status_code < 300:
            key.success_count += 1
            key.quota_scope.success_count += 1
            key.is_healthy = True
            key.last_error_category = None
            key.quota_scope.last_error_category = None
            return

        key.failure_count += 1
        key.quota_scope.failure_count += 1

        # 1. Account quota exhausted / Payment required (HTTP 402 or explicit quota exhausted)
        err_lower = (error_message or "").lower()
        has_quota_hint = quota_exhausted or (status_code == 402) or any(
            q in err_lower for q in (
                "insufficient_quota",
                "not enough credits",
                "quota exceeded",
                "quota_exhausted",
                "credit balance",
                "payment required",
                "billing",
            )
        )
        if has_quota_hint:
            key.quota_scope.is_exhausted = True
            key.quota_scope.last_error_category = "quota_exhausted"
            key.last_error_category = "quota_exhausted"
            # Do NOT mark auth failed because the key secret itself is valid
            key.is_auth_failed = False
            remaining_scopes = sum(1 for s in self.quota_scopes.values() if not s.is_exhausted)
            logger.warning(
                "[ProviderKeyPool:%s] Account quota exhausted for scope '%s' (HTTP %d). "
                "Account scope disabled. Remaining eligible quota scopes: %d.",
                self.provider_name,
                key.account_id,
                status_code,
                remaining_scopes,
            )
            return

        # 2. Definitive credential-specific authentication failure
        # HTTP 401 Unauthorized is ALWAYS credential invalid.
        # HTTP 403 Forbidden is ONLY credential invalid if provider message explicitly confirms invalid key/token.
        is_definitive_bad_key = (status_code == 401) or (
            status_code == 403 and any(
                b in err_lower for b in (
                    "invalid_api_key",
                    "invalid api key",
                    "invalid api_key",
                    "invalid token",
                    "authentication failed",
                    "unauthorized",
                    "unauthenticated",
                    "wrong api key",
                )
            )
        )
        if is_definitive_bad_key:
            key.is_auth_failed = True
            key.is_healthy = False
            key.last_error_category = "credential_invalid"
            key.quota_scope.last_error_category = "credential_invalid"
            remaining = sum(1 for k in self.keys if not k.is_auth_failed)
            logger.warning(
                "[ProviderKeyPool:%s] Key slot %d (%s) hit definitive auth failure (HTTP %d). "
                "Credential disabled. Remaining usable slots: %d.",
                self.provider_name,
                key.slot_id,
                key.account_id,
                status_code,
                remaining,
            )
            return

        # 3. HTTP 403 Forbidden without confirmed invalid credentials:
        # Distinguish permission restrictions, plan restrictions, unavailable endpoints,
        # or record a non-definitive failure. Never permanently disable the credential!
        if status_code == 403:
            cd = retry_after if retry_after and retry_after > 0 else 15.0
            if any(p in err_lower for p in ("plan", "tier", "subscription", "upgrade")):
                cat = "plan_restricted"
            elif any(p in err_lower for p in ("endpoint", "not available", "unsupported", "unknown")):
                cat = "endpoint_unavailable"
            elif any(p in err_lower for p in ("permission", "forbidden", "access denied", "not allowed", "scope")):
                cat = "permission_denied"
            else:
                cat = "permission_restricted"

            key.is_auth_failed = False  # NEVER permanently destroy/disable solely due to 403
            key.last_error_category = cat
            key.quota_scope.last_error_category = cat
            key.set_cooldown(cd)  # Bounded cooldown to allow rotation/failover without destroying credential
            logger.warning(
                "[ProviderKeyPool:%s] Key slot %d (%s) hit 403 (%s). "
                "Recorded non-definitive failure without disabling credential. Cooldown: %.1fs.",
                self.provider_name,
                key.slot_id,
                key.account_id,
                cat,
                cd,
            )
            return

        # 4. HTTP 429: Rate limited (Temporary RPM / RPS or concurrency limit)
        if status_code == 429:
            cooldown_secs = retry_after if retry_after and retry_after > 0 else 20.0
            key.last_error_category = "rate_limited"
            key.quota_scope.last_error_category = "rate_limited"
            key.set_cooldown(cooldown_secs)
            key.quota_scope.set_cooldown(cooldown_secs)
            logger.warning(
                "[ProviderKeyPool:%s] Rate limit hit on scope '%s' (HTTP 429). "
                "Account cooldown set for %.1f seconds.",
                self.provider_name,
                key.account_id,
                cooldown_secs,
            )
            return

        # 5. 5xx Server Errors or Timeouts (status 0)
        if 500 <= status_code <= 599 or status_code == 0:
            key.set_cooldown(2.0)
            key.quota_scope.set_cooldown(2.0)
            cat = "transient_failure"
            key.last_error_category = cat
            key.quota_scope.last_error_category = cat
            logger.warning(
                "[ProviderKeyPool:%s] Key slot %d (%s) hit transient failure (HTTP %d). "
                "Brief cooldown applied.",
                self.provider_name,
                key.slot_id,
                key.account_id,
                status_code,
            )
            return

        # 6. Other non-2xx codes
        cat = f"http_{status_code}"
        key.last_error_category = cat
        key.quota_scope.last_error_category = cat

    def get_status(self) -> Dict[str, Any]:
        """
        Generate sanitized diagnostics for provider, quota scopes, and slots.
        Distinguishes:
        - 'credential_invalid'
        - 'quota_exhausted'
        - 'rate_limited'
        - 'transient_failure'
        - 'available'
        Guaranteed to contain zero secrets.
        """
        if not self.keys:
            top_status = "disabled"
        elif self.shared_quota_exhausted:
            top_status = "quota_exhausted"
        elif all(k.is_auth_failed for k in self.keys):
            top_status = "credential_invalid"
        elif any(k.is_available() for k in self.keys):
            top_status = "available"
        elif any(k.quota_scope.is_in_cooldown() or k.is_in_cooldown() for k in self.keys):
            top_status = "rate_limited"
        elif any(k.last_error_category == "transient_failure" for k in self.keys):
            top_status = "transient_failure"
        else:
            top_status = "temporarily_unavailable"

        scopes_diag = []
        for s_id, s in self.quota_scopes.items():
            in_cd = s.is_in_cooldown()
            cd_rem = max(0, int(s.cooldown_until - time.time())) if in_cd else 0
            if s.is_exhausted:
                s_status = "quota_exhausted"
            elif in_cd:
                s_status = "rate_limited"
            elif s.is_available():
                s_status = "available"
            else:
                s_status = s.last_error_category or "unknown"

            scopes_diag.append({
                "scope_id": s_id,
                "status": s_status,
                "exhausted": s.is_exhausted,
                "in_cooldown": in_cd,
                "cooldown_remaining_seconds": cd_rem,
                "success_count": s.success_count,
                "failure_count": s.failure_count,
                "last_status_code": s.last_status_code,
                "last_error_category": s.last_error_category,
                "last_used_timestamp": s.last_used_timestamp,
                "remaining_quota": s.remaining_quota,
                "quota_reset_at": s.quota_reset_at,
            })

        slots_diag = []
        for k in self.keys:
            in_cd = k.is_in_cooldown()
            cd_rem = max(0, int(k.cooldown_until - time.time())) if in_cd else 0
            if k.is_auth_failed:
                k_status = "credential_invalid"
            elif k.quota_scope.is_exhausted:
                k_status = "quota_exhausted"
            elif in_cd:
                k_status = k.last_error_category or "rate_limited"
            elif k.is_available():
                k_status = "available"
            elif k.last_error_category == "transient_failure":
                k_status = "transient_failure"
            else:
                k_status = k.last_error_category or "unknown"

            slots_diag.append({
                "slot_id": k.slot_id,
                "account_id": k.account_id,
                "quota_scope": k.quota_scope.scope_id,
                "status": k_status,
                "healthy": k.is_healthy,
                "auth_failed": k.is_auth_failed,
                "exhausted": k.is_exhausted,
                "in_cooldown": in_cd,
                "cooldown_remaining_seconds": cd_rem,
                "success_count": k.success_count,
                "failure_count": k.failure_count,
                "last_status_code": k.last_status_code,
                "last_error_category": k.last_error_category,
                "last_used_timestamp": k.last_used_timestamp,
            })

        return {
            "provider": self.provider_name,
            "status": top_status,
            "configured": len(self.keys) > 0,
            "total_slots": len(self.keys),
            "available_slots": sum(1 for k in self.keys if k.is_available()),
            "total_quota_scopes": len(self.quota_scopes),
            "available_quota_scopes": sum(1 for s in self.quota_scopes.values() if s.is_available()),
            "shared_quota_exhausted": self.shared_quota_exhausted,
            "quota_scopes": scopes_diag,
            "slots": slots_diag,
        }

    def reset_all(self):
        """Reset state for tests."""
        self._manual_shared_exhausted = False
        self._cursor = 0
        for scope in self.quota_scopes.values():
            scope.reset()
        for k in self.keys:
            k.reset()


class ProviderKeyManager:
    """
    Central manager for multi-provider API key pools.
    Maintains internal credential registry associating keys with:
    - provider
    - credential_slot
    - quota_scope
    """

    def __init__(self, settings_obj: Optional[Any] = None):
        self._settings = settings_obj
        self.settings = settings_obj
        self.pools: Dict[str, ProviderKeyPool] = {}
        self._initialize_pools()

    def _get_setting(self, name: str, default: str = "") -> str:
        """Fetch setting from settings object or environment variable."""
        if self._settings and hasattr(self._settings, name):
            val = getattr(self._settings, name)
            if val is not None:
                return str(val)
        return os.environ.get(name, default)

    def _initialize_pools(self):
        """Initialize independent pools for Groq, Treg, Serper, and others."""
        # 1. Groq (AI Inference & Visibility)
        groq_keys, groq_scopes = self._collect_keys_and_scopes(
            provider="groq",
            numbered_names=["GROQ_API_KEY_1", "GROQ_API_KEY_2"],
            legacy_aliases=["GROQ_API_KEY"],
            numbered_scope_names=["GROQ_QUOTA_SCOPE_1", "GROQ_QUOTA_SCOPE_2"],
        )
        self.pools["groq"] = ProviderKeyPool("groq", groq_keys, quota_scopes=groq_scopes)

        # 2. Treg (Proxied Search & Enrichment)
        treg_keys, treg_scopes = self._collect_keys_and_scopes(
            provider="treg",
            numbered_names=["TREG_API_KEY_1", "TREG_API_KEY_2"],
            legacy_aliases=["TREG_API_KEY", "TREG_API_TOKEN"],
            numbered_scope_names=["TREG_QUOTA_SCOPE_1", "TREG_QUOTA_SCOPE_2"],
        )
        self.pools["treg"] = ProviderKeyPool("treg", treg_keys, quota_scopes=treg_scopes)

        # 3. Serper (Google Maps & Search Snippets)
        serper_keys, serper_scopes = self._collect_keys_and_scopes(
            provider="serper",
            numbered_names=["SERPER_API_KEY_1", "SERPER_API_KEY_2"],
            legacy_aliases=["SERPER_API_KEY"],
            numbered_scope_names=["SERPER_QUOTA_SCOPE_1", "SERPER_QUOTA_SCOPE_2"],
        )
        self.pools["serper"] = ProviderKeyPool("serper", serper_keys, quota_scopes=serper_scopes)

        # 4. Optional discovery providers (SerpApi, HasData, Outscraper, Hunter, etc.)
        for prov, prefix in [
            ("serpapi", "SERPAPI_API_KEY"),
            ("hasdata", "HASDATA_API_KEY"),
            ("outscraper", "OUTSCRAPER_API_KEY"),
            ("hunter", "HUNTER_API_KEY"),
            ("openrouter", "OPENROUTER_API_KEY"),
            ("gemini", "GEMINI_API_KEY"),
        ]:
            keys, scopes = self._collect_keys_and_scopes(
                provider=prov,
                numbered_names=[f"{prefix}_1", f"{prefix}_2"],
                legacy_aliases=[prefix],
            )
            self.pools[prov] = ProviderKeyPool(prov, keys, quota_scopes=scopes)

    def _collect_keys_and_scopes(
        self,
        provider: str,
        numbered_names: List[str],
        legacy_aliases: List[str],
        numbered_scope_names: Optional[List[str]] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Collect keys and their associated quota scope IDs:
        - If numbered keys are present, reads their custom quota scope name or defaults to '{provider}_account_{i}'.
        - If numbered keys are absent, falls back to legacy aliases with scope '{provider}_account_1'.
        - Deduplicates identical keys safely while preserving correct scope associations.
        """
        keys: List[str] = []
        scopes: List[str] = []

        seen_secrets: Set[str] = set()

        # Try numbered keys first
        for i, name in enumerate(numbered_names):
            val = self._get_setting(name, "").strip()
            if val and len(val) >= 8 and not any(ph in val.lower() for ph in PLACEHOLDER_SUBSTRINGS):
                if val not in seen_secrets:
                    seen_secrets.add(val)
                    keys.append(val)
                    # Quota scope lookup
                    scope_val = ""
                    if numbered_scope_names and i < len(numbered_scope_names):
                        scope_val = self._get_setting(numbered_scope_names[i], "").strip()
                    if not scope_val:
                        scope_val = f"{provider}_account_{i + 1}"
                    scopes.append(scope_val)

        # Fallback to legacy single key aliases if no numbered keys found
        if not keys:
            for alias in legacy_aliases:
                val = self._get_setting(alias, "").strip()
                if val and len(val) >= 8 and not any(ph in val.lower() for ph in PLACEHOLDER_SUBSTRINGS):
                    if val not in seen_secrets:
                        seen_secrets.add(val)
                        keys.append(val)
                        scopes.append(f"{provider}_account_1")
                        break

        return keys, scopes

    def get_pool(self, provider_name: str) -> Optional[ProviderKeyPool]:
        """Retrieve key pool for a provider."""
        return self.pools.get(provider_name.lower().strip())

    def get_or_create_pool(
        self,
        provider_name: str,
        keys: Optional[List[str]] = None,
        quota_scopes: Optional[List[str]] = None,
    ) -> ProviderKeyPool:
        """Retrieve or dynamically create/configure a key pool."""
        p_name = provider_name.lower().strip()
        if p_name not in self.pools:
            self.pools[p_name] = ProviderKeyPool(p_name, keys or [], quota_scopes=quota_scopes)
        elif keys is not None:
            self.pools[p_name].configure_keys(keys, quota_scopes=quota_scopes)
        return self.pools[p_name]

    def reload(self, settings_obj: Optional[Any] = None):
        """Reload keys from updated settings or environment."""
        if settings_obj is not None:
            self._settings = settings_obj
            self.settings = settings_obj
        self._initialize_pools()

    def get_all_diagnostics(self) -> Dict[str, Any]:
        """Return sanitized diagnostics across all configured pools."""
        return {p_name: pool.get_status() for p_name, pool in self.pools.items()}

    def get_all_secrets(self) -> Set[str]:
        """Internal helper to get raw secret values for redaction."""
        secrets: Set[str] = set()
        for pool in self.pools.values():
            for k in pool.keys:
                if k.secret and len(k.secret) >= 4:
                    secrets.add(k.secret)
        return secrets

    def redact_all_secrets(self, text: str) -> str:
        """
        Sanitize any string by redacting known API keys and common auth header patterns.
        """
        if not text:
            return ""
        redacted = str(text)
        for s in self.get_all_secrets():
            redacted = redacted.replace(s, "[REDACTED_API_KEY]")

        # Redact Authorization: Bearer <key>
        redacted = re.sub(
            r'(Bearer\s+)[A-Za-z0-9_\-\.]{8,}',
            r'\1[REDACTED_API_KEY]',
            redacted,
            flags=re.IGNORECASE,
        )
        # Redact X-API-KEY: <key>
        redacted = re.sub(
            r'(X-API-KEY["\']?\s*:\s*["\']?)[A-Za-z0-9_\-\.]{8,}',
            r'\1[REDACTED_API_KEY]',
            redacted,
            flags=re.IGNORECASE,
        )
        # Redact X-Treg-Token: <token>
        redacted = re.sub(
            r'(X-Treg-Token["\']?\s*:\s*["\']?)[A-Za-z0-9_\-\.]{8,}',
            r'\1[REDACTED_API_KEY]',
            redacted,
            flags=re.IGNORECASE,
        )
        # Redact key=... query parameters
        redacted = re.sub(
            r'([?&]key=)[^&\s"\']+',
            r'\1[REDACTED_API_KEY]',
            redacted,
            flags=re.IGNORECASE,
        )
        return redacted

    def reset_all(self):
        """Reset state across all pools (for test suites)."""
        for pool in self.pools.values():
            pool.reset_all()


# Global Singleton Instance
_global_key_manager: Optional[ProviderKeyManager] = None
_global_lock = threading.Lock()


def get_key_manager(settings_obj: Optional[Any] = None) -> ProviderKeyManager:
    """Get or initialize the global ProviderKeyManager instance."""
    global _global_key_manager
    if _global_key_manager is None:
        with _global_lock:
            if _global_key_manager is None:
                _global_key_manager = ProviderKeyManager(settings_obj)
    return _global_key_manager
