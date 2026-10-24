from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Any, List
import json
import os

DEFAULT_CRAWL_MAX_PAGES: int = 10
MIN_CRAWL_PAGES: int = 1
HARD_MAX_CRAWL_PAGES: int = 25


def sanitize_crawl_max_pages(val: Any) -> int:
    """
    Sanitize crawl max pages configuration:
    - Default: 10 pages
    - Minimum accepted value: 1
    - Hard maximum: 25 pages
    - For empty, malformed, non-integer, zero, or negative values: safely fall back to 10
    - Clamp values above 25 to 25
    """
    if val is None or val == "":
        return DEFAULT_CRAWL_MAX_PAGES
    try:
        parsed = int(val)
        if parsed < MIN_CRAWL_PAGES:
            return DEFAULT_CRAWL_MAX_PAGES
        if parsed > HARD_MAX_CRAWL_PAGES:
            return HARD_MAX_CRAWL_PAGES
        return parsed
    except (ValueError, TypeError):
        return DEFAULT_CRAWL_MAX_PAGES


class Settings(BaseSettings):
    # App
    APP_NAME: str = "TEB Solutions LeadGen"
    FRONTEND_URL: str = "http://localhost:5174"
    REPORTS_DIR: str = "reports"

    # Database
    DATABASE_URL: str
    INIT_SCHEMA: bool = False

    # Campaign Scheduler & Distributed Worker Coordination
    CAMPAIGN_SCHEDULER_ENABLED: bool = True
    CAMPAIGN_SCHEDULER_POLL_INTERVAL_SECONDS: float = 30.0
    CAMPAIGN_SCHEDULER_BATCH_SIZE: int = 5
    CAMPAIGN_SCHEDULER_MAX_CONCURRENT_WORKERS: int = 3

    # Security
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Admin credentials (single-user v1) — must be explicitly configured; fallbacks prohibited
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""

    # Audit / Crawler & Freshness Policy
    CRAWL_MAX_PAGES: int = DEFAULT_CRAWL_MAX_PAGES
    AUDIT_FRESHNESS_MAX_DAYS: int = 14

    @field_validator("CRAWL_MAX_PAGES", mode="before")
    @classmethod
    def _validate_crawl_max_pages(cls, v: Any) -> int:
        return sanitize_crawl_max_pages(v)

    # SMTP Senders — JSON array stored in .env
    # Each entry: {email, smtp_host, smtp_port, password, daily_limit}
    SMTP_SENDERS: str = "[]"

    # WhatsApp (optional v2)
    WHATSAPP_API_TOKEN: str = ""
    WHATSAPP_PHONE_ID: str = ""

    # Google Search Console (OAuth 2.0 & Token Persistence)
    GSC_CLIENT_ID: str = ""
    GSC_CLIENT_SECRET: str = ""
    GSC_REDIRECT_URI: str = "http://localhost:8001/gsc/oauth/callback"
    GSC_ENCRYPTION_KEY: str = ""
    GSC_CREDENTIALS_FILE: str = "reports/.gsc_credentials.enc"

    # AI-Search Providers (Perplexity, OpenRouter, Google Gemini)
    AI_SEARCH_PROVIDER: str = "gemini"
    AI_SEARCH_PROVIDER_KEY: str = ""
    AI_SEARCH_MODEL: str = "sonar"
    AI_SEARCH_TIMEOUT_SECONDS: int = 20
    AI_SEARCH_MAX_QUERIES: int = 10
    AI_SEARCH_STORAGE_FILE: str = "reports/.ai_search_runs.json"

    # OpenRouter
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "nvidia/nemotron-3.5-lightning:free"
    OPENROUTER_ENABLE_WEB_SEARCH: bool = False

    # Google Gemini API
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_ENABLE_SEARCH_GROUNDING: bool = True

    # Groq API (AI Inference & Visibility)
    GROQ_API_KEY_1: str = ""
    GROQ_API_KEY_2: str = ""
    GROQ_API_KEY: str = ""
    GROQ_QUOTA_SCOPE_1: str = ""
    GROQ_QUOTA_SCOPE_2: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Lead Discovery & Search Providers
    SERPER_API_KEY_1: str = ""
    SERPER_API_KEY_2: str = ""
    SERPER_API_KEY: str = ""
    SERPER_QUOTA_SCOPE_1: str = ""
    SERPER_QUOTA_SCOPE_2: str = ""
    SERPAPI_API_KEY: str = ""
    HASDATA_API_KEY: str = ""
    OUTSCRAPER_API_KEY: str = ""
    HUNTER_API_KEY: str = ""
    TREG_API_KEY_1: str = ""
    TREG_API_KEY_2: str = ""
    TREG_API_KEY: str = ""
    TREG_API_TOKEN: str = ""
    TREG_QUOTA_SCOPE_1: str = ""
    TREG_QUOTA_SCOPE_2: str = ""
    TREG_ENABLE_PAID_ENDPOINTS: bool = False
    DISCOVERY_MAX_FILE_SIZE_BYTES: int = 1_048_576
    DISCOVERY_MAX_ENTRIES_PER_FILE: int = 1000
    DISCOVERY_MAX_COMBINATIONS_LIMIT: int = 500
    DISCOVERY_STORAGE_FILE: str = "reports/.lead_discovery_jobs.json"

    class Config:
        env_file = ".env"
        extra = "ignore"

    def get_smtp_accounts(self) -> List[dict]:
        """
        Parse SMTP_SENDERS JSON string into list of validated account dicts.
        Each valid account requires: email, smtp_host, password.
        Optional fields: smtp_port (default 465), daily_limit (default 1000),
        sender_name (default Ashish), login_email (default email), reply_to.
        """
        try:
            raw = json.loads(self.SMTP_SENDERS)
            if not isinstance(raw, list):
                return []
            validated = []
            for item in raw:
                if not isinstance(item, dict):
                    continue
                email = str(item.get("email", "")).strip()
                smtp_host = str(item.get("smtp_host", "")).strip()
                password = str(item.get("password", ""))
                if not email or not smtp_host or not password:
                    continue
                try:
                    port = int(item.get("smtp_port", 465))
                except (ValueError, TypeError):
                    port = 465
                try:
                    daily_limit = int(item.get("daily_limit", 1000))
                except (ValueError, TypeError):
                    daily_limit = 1000
                account = {
                    "email": email,
                    "smtp_host": smtp_host,
                    "smtp_port": port,
                    "password": password,
                    "daily_limit": daily_limit,
                    "sender_name": str(item.get("sender_name", "Ashish")).strip() or "Ashish",
                    "login_email": str(item.get("login_email", email)).strip() or email,
                }
                if "reply_to" in item and item["reply_to"]:
                    account["reply_to"] = str(item["reply_to"]).strip()
                validated.append(account)
            return validated
        except (json.JSONDecodeError, TypeError):
            return []


settings = Settings()

# Ensure reports directory exists
os.makedirs(settings.REPORTS_DIR, exist_ok=True)
