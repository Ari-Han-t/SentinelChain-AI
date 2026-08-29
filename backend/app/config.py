from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SentinelChain AI"
    environment: str = "development"
    database_url: str = "sqlite:///./sentinelchain.db"
    jwt_secret: str = "development-jwt-secret"
    jwt_ttl_minutes: int = 30
    import_hmac_secret: str = "development-import-secret"
    field_encryption_key: str = "development-field-key"
    cors_origins: list[str] = ["http://localhost:5173"]
    demo_mode: bool = True
    seed_demo_data: bool = True
    rate_limit_per_minute: int = 180

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def reject_unsafe_production_secrets(self) -> "Settings":
        if self.environment.lower() == "production":
            values = (self.jwt_secret, self.import_hmac_secret, self.field_encryption_key)
            if any(len(value) < 32 or value.startswith("development") for value in values):
                raise ValueError("Production secrets must each be at least 32 characters")
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be false in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

