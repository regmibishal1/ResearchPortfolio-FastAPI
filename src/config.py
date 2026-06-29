"""Application configuration loaded from environment variables.

Centralised here so individual modules can `from src.config import settings`
without each one re-reading os.environ. Validates types on startup so a
missing or malformed value fails fast instead of breaking at first use.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — runtime read connection.
    # Use the worldcup_reader role in production. Format:
    #   postgresql+asyncpg://user:password@host:port/dbname
    # Left as an empty string by default so endpoints that don't need the DB
    # (e.g. /health, /stats/sample) still work in environments where Postgres
    # is not configured.
    database_url: str = Field(default="", alias="DATABASE_URL")

    # CORS allowlist — comma-separated origins permitted to call the API.
    cors_allowed_origins: str = Field(
        default="http://localhost:4200", alias="CORS_ALLOWED_ORIGINS"
    )

    # Debug toggle — any non-empty value flips logging to DEBUG.
    debug: str = Field(default="", alias="DEBUG")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


settings = Settings()
