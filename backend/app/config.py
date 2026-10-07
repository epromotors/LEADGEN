from pydantic_settings import BaseSettings
from typing import List
import json
import os


class Settings(BaseSettings):
    # App
    APP_NAME: str = "TEB Solutions LeadGen"
    FRONTEND_URL: str = "http://localhost:5174"
    REPORTS_DIR: str = "reports"

    # Database
    DATABASE_URL: str

    # Security
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # Admin credentials (single-user v1)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "changeme123"

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
