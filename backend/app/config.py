from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SentinelChain AI"
    environment: str = "development"
    database_url: str = "sqlite:///./sentinelchain.db"
    jwt_secret: str = "development-jwt-secret"
    jwt_ttl_minutes: int = 30
    import_hmac_secret: str = "development-import-secret"
    field_encryption_key: str = "development-field-key"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    demo_mode: bool = True
    seed_demo_data: bool = True
    rate_limit_per_minute: int = 180
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @model_validator(mode="after")
    def reject_unsafe_production_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            values = (self.jwt_secret, self.import_hmac_secret, self.field_encryption_key)
            if any(len(value) < 32 or value.startswith("development") for value in values):
                raise ValueError("Production secrets must each be at least 32 characters")
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be false in production")
            if bool(self.bootstrap_admin_email) != bool(self.bootstrap_admin_password):
                raise ValueError("Set both BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD")
            if self.bootstrap_admin_password and len(self.bootstrap_admin_password) < 12:
                raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
