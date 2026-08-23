"""Central configuration management for Drishti.

All settings are sourced from environment variables (12-factor style) with
sensible development defaults so the stack boots even before a `.env` exists.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_name: str = "Drishti"
    app_description: str = "AI Revenue Recovery agent system"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "*"  # comma-separated origins

    # ---- Security ----
    secret_key: str = Field(default="dev-secret-key-change-me", description="JWT signing secret")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    api_key_header: str = "X-API-Key"
    drishti_api_keys: str = Field(default="dev-key-1,dev-key-2", description="Comma-separated valid API keys")

    # ---- Database ----
    database_url: str = "sqlite:///./drishti.db"  # zero-dep fallback; Postgres in compose
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---- Cache ----
    redis_url: Optional[str] = None  # None -> in-memory cache fallback
    cache_ttl_seconds: int = 300

    # ---- Encryption ----
    encryption_key: Optional[str] = None  # Fernet key; ephemeral key generated if absent

    # ---- Logging / audit ----
    log_level: str = "INFO"
    log_json: bool = False
    audit_log_file: str = "logs/audit.jsonl"

    # ---- Razorpay ----
    razorpay_key_id: Optional[str] = None
    razorpay_key_secret: Optional[str] = None
    razorpay_test_key_id: Optional[str] = None
    razorpay_test_key_secret: Optional[str] = None
    razorpay_live_key_id: Optional[str] = None
    razorpay_live_key_secret: Optional[str] = None
    razorpay_webhook_secret: Optional[str] = None
    razorpay_base_url: str = "https://api.razorpay.com/v1"
    razorpay_environment: str = "test"  # test keys by default; set production explicitly

    # ---- Groq reasoning model ----
    groq_api_key: Optional[str] = None
    groq_model: str = "openai/gpt-oss-120b"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.0

    # ---- SMS provider: twilio | sns | mock ----
    sms_provider: str = "mock"
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None
    aws_region: str = "ap-south-1"
    sns_sender_id: str = "DRISHTI"

    # ---- Email provider: sendgrid | ses | mock ----
    email_provider: str = "mock"
    sendgrid_api_key: Optional[str] = None
    sendgrid_from_email: str = "recovery@drishti.ai"
    ses_from_email: str = "recovery@drishti.ai"

    # ---- Voice / IVR provider: exotel | mock ----
    voice_provider: str = "mock"
    exotel_api_key: Optional[str] = None
    exotel_api_token: Optional[str] = None
    exotel_from_number: Optional[str] = None

    # ---- CRM integration: webhook | salesforce | freshsales | mock ----
    crm_provider: str = "mock"
    crm_webhook_url: Optional[str] = None
    crm_api_key: Optional[str] = None

    # ---- ML models ----
    model_dir: str = "models"
    risk_model_path: Optional[str] = None
    classifier_model_path: Optional[str] = None
    drift_threshold: float = 0.2  # PSI threshold

    # ---- Business rules ----
    high_value_threshold_inr: float = 25000.0
    nudge_window_hours: int = 72
    max_recovery_attempts: int = 4
    human_review_confidence_threshold: float = 0.7
    merchant_daily_spend_limit_usd: float = 5000.0
    blacklisted_merchant_ids: str = ""
    invalid_phone_numbers: str = ""
    verity_checkpoint_path: str = "logs/verity_checkpoints.db"

    # ------------------------------------------------------------------
    @field_validator("debug", mode="before")
    @classmethod
    def _normalise_debug(cls, value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def valid_api_keys(self) -> List[str]:
        return [key.strip() for key in self.drishti_api_keys.split(",") if key.strip()]

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}

    @property
    def llm_enabled(self) -> bool:
        """True when Groq reasoning is available; rule engine used otherwise."""
        return bool(self.groq_api_key)

    @property
    def invalid_phone_number_set(self) -> set[str]:
        return {
            phone.strip()
            for phone in self.invalid_phone_numbers.split(",")
            if phone.strip()
        }

    @property
    def blacklisted_merchant_id_set(self) -> set[str]:
        return {
            merchant.strip()
            for merchant in self.blacklisted_merchant_ids.split(",")
            if merchant.strip()
        }

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.razorpay_key_pair[0] and self.razorpay_key_pair[1])

    @property
    def razorpay_key_pair(self) -> tuple[Optional[str], Optional[str]]:
        """Select test or live credentials based on RAZORPAY_ENVIRONMENT."""
        if self.razorpay_environment.lower() in {"production", "live", "prod"}:
            return (
                self.razorpay_live_key_id or self.razorpay_key_id,
                self.razorpay_live_key_secret or self.razorpay_key_secret,
            )
        return (
            self.razorpay_test_key_id or self.razorpay_key_id,
            self.razorpay_test_key_secret or self.razorpay_key_secret,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()
