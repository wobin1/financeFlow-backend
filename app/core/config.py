from functools import cached_property
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings

# Documented / historically copied placeholders — never accept these as JWT keys.
_WEAK_SECRET_KEYS = frozenset(
    {
        "",
        "your-secret-key-here",
        "changeme",
        "change-me",
        "secret",
        "dev",
        "development",
        "test",
    }
)


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Database
    DATABASE_URL: str

    # AI Services
    GEMINI_API_KEY: str

    # Banking - Plaid (Global)
    PLAID_CLIENT_ID: Optional[str] = None
    PLAID_SECRET: Optional[str] = None
    PLAID_ENV: str = "sandbox"

    # Banking - Mono (Nigeria)
    MONO_SECRET_KEY: Optional[str] = None
    MONO_PUBLIC_KEY: Optional[str] = None
    MONO_ENV: str = "test"  # test or live
    MONO_WEBHOOK_SECRET: Optional[str] = None
    USE_MOCK_MONO: bool = False

    # Messaging
    TWILIO_SID: Optional[str] = None
    TWILIO_TOKEN: Optional[str] = None
    TWILIO_PHONE_NUMBER: Optional[str] = None

    # Termii (Alternative messaging for Nigeria)
    TERMII_API_KEY: Optional[str] = None
    TERMII_SENDER_ID: Optional[str] = None
    TERMII_CHANNEL: Optional[str] = None

    # Billing - Paystack
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None
    # Optional recurring plan codes from Paystack dashboard (monthly)
    PAYSTACK_PLAN_STARTER: Optional[str] = None
    PAYSTACK_PLAN_GROWTH: Optional[str] = None
    PAYSTACK_PLAN_BUSINESS: Optional[str] = None

    # Legacy setting retained for ops docs only — registration/login never auto-promote.
    # Grant admin via admin API or a one-off DB update.
    ADMIN_EMAILS: str = ""

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    CORS_ORIGINS: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "https://finance-flow-frontend-nine.vercel.app,"
        "https://financeflow.crimax.ng"
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def reject_weak_secret_key(cls, value: str) -> str:
        key = (value or "").strip()
        if key.lower() in _WEAK_SECRET_KEYS or len(key) < 32:
            raise ValueError(
                "SECRET_KEY is missing, too short, or a documented placeholder. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return key

    @cached_property
    def cors_origins(self) -> list[str]:
        origins = {origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()}
        origins.add(self.FRONTEND_URL)
        return sorted(origins)

    @cached_property
    def admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.ADMIN_EMAILS.split(",")
            if email.strip()
        }

    class Config:
        env_file = ".env"


settings = Settings()
