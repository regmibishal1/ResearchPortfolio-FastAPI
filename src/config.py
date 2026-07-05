"""Application configuration loaded from environment variables.

Centralised here so individual modules can `from src.config import settings`
without each one re-reading os.environ. Validates types on startup so a
missing or malformed value fails fast instead of breaking at first use.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database, runtime read connection.
    # Use the worldcup_reader role in production. Format:
    #   postgresql+asyncpg://user:password@host:port/dbname
    # Left as an empty string by default so endpoints that don't need the DB
    # (e.g. /health, /stats/sample) still work in environments where Postgres
    # is not configured.
    database_url: str = Field(default="", alias="DATABASE_URL")

    # Optional: separate writer connection used only by the admin-gated
    # /worldcup/ingest endpoint. When set, the worldcup_writer role is
    # carried by a distinct engine so the read-side engine remains
    # SELECT-only at the DB layer regardless of any code-level bug. When
    # unset, the ingest endpoint returns 503 and write traffic must come
    # via the standalone db_writer.py script in the WC repo.
    worldcup_db_writer_url: str = Field(default="", alias="WORLDCUP_DB_WRITER_URL")

    # Read connection for the stocks schema, uses the stocks_reader role in
    # production. Separate from DATABASE_URL so each schema keeps its own
    # least-privilege login. Falls back to DATABASE_URL (see stocks_reader_url)
    # for single-connection local dev.
    stocks_db_reader_url: str = Field(default="", alias="STOCKS_DB_READER_URL")

    # Optional writer connection used only by the admin-gated /stocks/ingest
    # endpoint. Carries the stocks_writer role on a distinct engine so the
    # read-side engine stays SELECT-only at the DB layer. When unset, ingest
    # returns 503.
    stocks_db_writer_url: str = Field(default="", alias="STOCKS_DB_WRITER_URL")

    # CORS allowlist, comma-separated origins permitted to call the API.
    cors_allowed_origins: str = Field(
        default="http://localhost:4200", alias="CORS_ALLOWED_ORIGINS"
    )

    # Debug toggle, any non-empty value flips logging to DEBUG.
    debug: str = Field(default="", alias="DEBUG")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def stocks_reader_url(self) -> str:
        """Reader connection for the stocks schema, falling back to the shared
        DATABASE_URL when a dedicated stocks reader is not configured.
        """
        return self.stocks_db_reader_url or self.database_url


settings = Settings()
