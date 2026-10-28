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

    # The deployment profile, mirroring SPRING_PROFILES_ACTIVE on backend-java: only "production"
    # makes a missing signing secret or master key fatal. Naming a release build "production" here
    # while the Java service runs another profile makes the two disagree about the same database.
    environment: str = Field(default="development", alias="ENVIRONMENT")
    port: int = Field(default=8090, alias="PORT")

    # postgresql+asyncpg://user:pass@host:5432/apigw — the same database backend-java migrates.
    database_url: str = Field(alias="DATABASE_URL")
    # Which schema holds the tables: 'apim' under the Java service's local profile, 'public' by
    # default. Set as the connection's search_path so no SQL in this service names a schema.
    db_schema: str = Field(default="apim", alias="DB_SCHEMA")

    # Apply pending schema migrations at startup, which is what Flyway did inside backend-java
    # before this service took them over. Turn it off where migrations are run as a separate step
    # before the rollout; the service then assumes the schema is already at the right version.
    run_migrations: bool = Field(default=True, alias="RUN_MIGRATIONS")

    auth_jwt_secret: str = Field(default="", alias="AUTH_JWT_SECRET")

    # 32 random bytes, base64. Empty outside production falls back to the same built-in development
    # key backend-java uses, which is what lets either service read the other's stored secrets.
    crypto_master_key: str = Field(default="", alias="CRYPTO_MASTER_KEY")

    # Shared with the APISIX gateways, which present it on every usage batch. Not a session token.
    usage_ingest_token: str = Field(default="change-me-ingest-token", alias="USAGE_INGEST_TOKEN")

    # Shown to partners on an API's page as the base URL to call, and whether Try-it-live is simulated.
    public_sandbox_url: str = Field(
        default="http://sandbox-api.apigw.com:9080", alias="PUBLIC_SANDBOX_URL"
    )
    try_it_mode: str = Field(default="GATEWAY", alias="TRY_IT_MODE")

    # Opens the API to any origin, so the local console works when opened straight off disk rather
    # than from /ui. Off by default, and ignored under the production profile.
    local_ui_cors: bool = Field(default=False, alias="LOCAL_UI_CORS")

    # --- payload encryption (VAPT). The RSA private key that unwraps the AES key on every encrypted
    # portal payload. **backend-java must hold the same one**, because nginx may route a request the
    # portal encrypted to either service. Empty outside production falls back to the development
    # keypair in common/payload_crypto.py, which both services carry; in production a missing key is
    # fatal, since falling back to a published keypair would make the whole mechanism pointless.
    payload_private_key: str = Field(default="", alias="PAYLOAD_PRIVATE_KEY")
    # True rejects an unencrypted portal request outright. Off on a developer machine so Swagger UI,
    # the local console, curl, the parity harness and the gates keep working; on in production, where
    # a tester dropping the header must not be answered in plaintext. Defaults to on under the
    # production profile regardless of this value — see payload_encryption_required.
    payload_encryption_enforced: bool = Field(default=False, alias="PAYLOAD_ENCRYPTION_ENFORCED")

    @property
    def payload_encryption_required(self) -> bool:
        """Production always enforces; elsewhere it is opt-in.

        Deriving it rather than reading the flag directly means a production deployment cannot end up
        accepting plaintext because someone left the flag at its default.
        """
        return self.payload_encryption_enforced or self.environment == "production"

    # --- security keys. CP-SEC-04: the previous key stays valid this long after a rotation.
    key_overlap_minutes: int = Field(default=20, alias="KEY_OVERLAP_MINUTES")
    # Sends the new key itself to the Partner Admins. False sends only the change notice.
    email_key_to_admin: bool = Field(default=True, alias="EMAIL_KEY_TO_ADMIN")
    # The background jobs: key expiry, sign-in code cleanup and error-log retention. This service
    # owns all three now; backend-java's are switched off. Exactly one service must run them —
    # both running them expires every key twice, neither running them leaves replaced keys live
    # forever. Within this service, two instances are safe: each tick takes an advisory lock.
    #
    # Turn off only where the jobs are run some other way. Off means keys never stop working.
    scheduler_enabled: bool = Field(default=True, alias="SCHEDULER_ENABLED")

    # --- mail. No host means notices are logged instead of sent, which is how a developer machine
    # behaves and how this network behaves while outbound SMTP is blocked.
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    mail_from: str = Field(default="no-reply@apigw.local", alias="MAIL_FROM")

    # --- sign-in. Mirrors apigw.auth on the Java side; both services must agree, because a code
    # issued by one is verified by whichever happens to serve the next request.
    token_ttl_hours: int = Field(default=8, alias="TOKEN_TTL_HOURS")
    otp_ttl_minutes: int = Field(default=5, alias="OTP_TTL_MINUTES")
    otp_length: int = Field(default=6, alias="OTP_LENGTH")
    otp_max_attempts: int = Field(default=5, alias="OTP_MAX_ATTEMPTS")
    otp_resend_cooldown_seconds: int = Field(default=30, alias="OTP_RESEND_COOLDOWN_SECONDS")
    otp_max_requests_per_window: int = Field(default=5, alias="OTP_MAX_REQUESTS_PER_WINDOW")
    otp_request_window_minutes: int = Field(default=15, alias="OTP_REQUEST_WINDOW_MINUTES")
    # True tells an unregistered address so ("Invalid user"), which is what operators expect. False
    # gives it the same answer as a registered one, so nobody can discover who holds an account.
    reveal_unknown_email: bool = Field(default=True, alias="REVEAL_UNKNOWN_EMAIL")

    # --- the APISIX gateways. Sync off means the service runs without one, which is how a developer
    # machine works; everything else about an API behaves identically.
    gateway_sync_enabled: bool = Field(default=True, alias="GATEWAY_SYNC_ENABLED")
    apisix_sandbox_admin_url: str = Field(
        default="http://localhost:9180", alias="APISIX_SANDBOX_ADMIN_URL"
    )
    apisix_sandbox_admin_key: str = Field(
        default="change-me-sandbox-admin-key", alias="APISIX_SANDBOX_ADMIN_KEY"
    )
    apisix_production_admin_url: str = Field(
        default="http://localhost:9181", alias="APISIX_PRODUCTION_ADMIN_URL"
    )
    apisix_production_admin_key: str = Field(
        default="change-me-production-admin-key", alias="APISIX_PRODUCTION_ADMIN_KEY"
    )
    gateway_redis_host: str = Field(default="valkey", alias="GATEWAY_REDIS_HOST")
    gateway_redis_port: int = Field(default=6379, alias="GATEWAY_REDIS_PORT")
    # Comma-separated; the hostnames each gateway answers on.
    gateway_sandbox_hosts_raw: str = Field(
        default="sandbox-api.apigw.com", alias="GATEWAY_SANDBOX_HOSTS"
    )
    gateway_production_hosts_raw: str = Field(
        default="api.apigw.com", alias="GATEWAY_PRODUCTION_HOSTS"
    )

    @property
    def gateway_sandbox_hosts(self) -> list[str]:
        return [h.strip() for h in self.gateway_sandbox_hosts_raw.split(",") if h.strip()]

    @property
    def gateway_production_hosts(self) -> list[str]:
        return [h.strip() for h in self.gateway_production_hosts_raw.split(",") if h.strip()]

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
