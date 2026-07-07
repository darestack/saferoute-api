"""Application configuration loaded from environment variables.

Uses ``pydantic-settings`` to read values from the process environment and
an optional ``.env`` file. All required variables are validated at import
time so the application fails fast if secrets are missing.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator


class Settings(BaseSettings):
    """SafeRoute API runtime settings.

    Attributes:
        SUPABASE_URL: Supabase project URL.
        SUPABASE_KEY: Supabase anon / public key for client-side queries.
        SUPABASE_SERVICE_ROLE_KEY: Supabase service-role key for server-side
            operations that bypass Row Level Security.
        WEBHOOK_SECRET: Shared secret used for webhook signature verification.
        API_KEY_SALT: Salt used for HMAC hashing of API keys.
        RETRY_ENDPOINT_SECRET: Shared secret for the internal retry endpoint.
        FRONTEND_URL: Frontend origin for CORS and OAuth redirects.
        ENVIRONMENT: Deployment environment. Affects CORS, logging, and
            error detail. Defaults to ``development``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    WEBHOOK_SECRET: str = ""
    API_KEY_SALT: str
    RETRY_ENDPOINT_SECRET: str = ""
    ENCRYPTION_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"
    TRUSTED_PROXIES: str = ""
    ALLOWED_HOSTS: str = ""

    @property
    def is_production(self) -> bool:
        """Return ``True`` if the app is running in production mode.

        Returns:
            ``True`` when ``ENVIRONMENT`` equals ``"production"``.
        """
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Return ``True`` if the app is running in local development."""
        return self.ENVIRONMENT == "development"

    def get_allowed_hosts(self) -> list[str]:
        """Return the list of allowed hosts for TrustedHostMiddleware.

        In production, respects the ``ALLOWED_HOSTS`` setting.
        In development, allows all hosts.
        """
        if self.is_production and self.ALLOWED_HOSTS:
            return [
                host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()
            ]
        return ["*"]

    @model_validator(mode="after")
    def validate_production_encryption(self) -> "Settings":
        """Ensure encryption is configured in production."""
        if not self.is_development and not self.ENCRYPTION_KEY:
            raise ValueError("ENCRYPTION_KEY must be set outside development")
        return self


settings = Settings()  # type: ignore[call-arg]
