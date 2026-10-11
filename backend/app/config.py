from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SentinelChain AI"
    environment: str = "development"
    database_url: str = "sqlite:///./sentinelchain.db"
    jwt_secret: str = Field(default="development-jwt-secret", repr=False)
    jwt_ttl_minutes: int = Field(default=30, ge=5, le=120)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=50)
    database_pool_timeout: int = Field(default=10, ge=1, le=60)
    import_hmac_secret: str = Field(default="development-import-secret", repr=False)
    field_encryption_key: str = Field(default="development-field-key", repr=False)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174"
    demo_mode: bool = True
    seed_demo_data: bool = True
    rate_limit_per_minute: int = 180
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = Field(default=None, repr=False)
    ai_provider: Literal["deterministic", "azure-ai-foundry", "gemini", "groq"] | None = None
    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str | None = Field(default=None, repr=False)
    groq_model: str = "llama-3.3-70b-versatile"
    ai_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ai_max_tokens: int = Field(default=1200, ge=1, le=8192)
    azure_ai_foundry_enabled: bool = False
    azure_ai_foundry_endpoint: str | None = None
    azure_ai_foundry_api_key: str | None = Field(default=None, repr=False)
    azure_ai_foundry_model: str | None = None
    azure_ai_foundry_timeout_seconds: int = 30
    azure_ai_foundry_max_tokens: int = 1200
    monitoring_interval_seconds: int = 3600
    notification_interval_seconds: int = Field(default=30, ge=10, le=3600)
    integration_profiles_json: str = Field(default="{}", repr=False)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def guidance_provider(self) -> str:
        return self.ai_provider or ("azure-ai-foundry" if self.azure_ai_foundry_enabled else "deterministic")

    @model_validator(mode="after")
    def reject_unsafe_production_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            values = (self.jwt_secret, self.import_hmac_secret, self.field_encryption_key)
            if any(len(value) < 32 or value.startswith("development") for value in values):
                raise ValueError("Production secrets must each be at least 32 characters")
            if not self.database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
                raise ValueError('Production requires PostgreSQL')
            if self.seed_demo_data:
                raise ValueError('SEED_DEMO_DATA must be false in production')
            if any(not origin.startswith('https://') or '*' in origin for origin in self.cors_origin_list):
                raise ValueError('Production CORS origins must be explicit HTTPS origins')
            if len(set(values)) != len(values):
                raise ValueError('Production secrets must be distinct')
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be false in production")
            if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
                raise ValueError("Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD")
            if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 12:
                raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
        if self.guidance_provider == "azure-ai-foundry":
            required = (
                self.azure_ai_foundry_endpoint,
                self.azure_ai_foundry_api_key,
                self.azure_ai_foundry_model,
            )
            if not all(required):
                raise ValueError("Azure AI Foundry requires endpoint, API key, and model deployment name")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
