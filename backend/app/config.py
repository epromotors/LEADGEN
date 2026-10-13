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

    # Security
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Admin credentials (single-user v1)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme123"

    # Audit / Crawler
    CRAWL_MAX_PAGES: int = DEFAULT_CRAWL_MAX_PAGES

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

    class Config:
        env_file = ".env"
        extra = "ignore"

    def get_smtp_accounts(self) -> List[dict]:
        """
        Parse SMTP_SENDERS JSON string into list of account dicts.
        Each account has: email, smtp_host, smtp_port, password, daily_limit
        """
        try:
            accounts = json.loads(self.SMTP_SENDERS)
            if isinstance(accounts, list):
                return accounts
        except (json.JSONDecodeError, TypeError):
            pass
        return []


settings = Settings()

# Ensure reports directory exists
os.makedirs(settings.REPORTS_DIR, exist_ok=True)
