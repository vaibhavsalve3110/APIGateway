"""Configuration, validated at import time.

A service that starts without a database URL or a signing secret only looks healthy until someone
tries to sign in, so these fail the boot rather than the first request.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Same fallback as TokenService.signingKey in backend-java, so a token minted by either service is
# accepted by the other on a developer machine.
DEV_JWT_SECRET = "apigw-local-development-jwt-signing-secret-32b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", alias="ENVIRONMENT")
    port: int = Field(default=8090, alias="PORT")

    # postgresql+asyncpg://user:pass@host:5432/apigw — the same database backend-java migrates.
    database_url: str = Field(alias="DATABASE_URL")
    # Which schema holds the tables: 'apim' under the Java service's local profile, 'public' by
    # default. Set as the connection's search_path so no SQL in this service names a schema.
    db_schema: str = Field(default="apim", alias="DB_SCHEMA")

    auth_jwt_secret: str = Field(default="", alias="AUTH_JWT_SECRET")

    # Shared with the APISIX gateways, which present it on every usage batch. Not a session token.
    usage_ingest_token: str = Field(default="change-me-ingest-token", alias="USAGE_INGEST_TOKEN")

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value:
            raise ValueError("DATABASE_URL must be set")
        # A psycopg-style URL silently selects a blocking driver, which stalls the event loop.
        if value.startswith("postgresql://"):
            value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must be a postgresql+asyncpg:// URL")
        # asyncpg rejects libpq query parameters such as ?schema=; the schema travels in DB_SCHEMA.
        return value.split("?", 1)[0]

    @field_validator("auth_jwt_secret")
    @classmethod
    def _require_secret(cls, value: str, info) -> str:  # type: ignore[no-untyped-def]
        if not value:
            if info.data.get("environment") == "production":
                raise ValueError("AUTH_JWT_SECRET must be set in production: it verifies session tokens")
            value = DEV_JWT_SECRET
        if len(value) < 32:
            raise ValueError("AUTH_JWT_SECRET must be at least 32 characters (HS256 needs 256 bits)")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
