"""Application configuration loaded from environment variables.

Uses ``pydantic-settings`` to read values from the process environment and
an optional ``.env`` file. All required variables are validated at import
time so the application fails fast if secrets are missing.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SafeRoute API runtime settings.

    Attributes:
        SUPABASE_URL: Supabase project URL.
        SUPABASE_KEY: Supabase anon / public key for client-side queries.
        SUPABASE_SERVICE_ROLE_KEY: Supabase service-role key for server-side
            operations that bypass Row Level Security.
        WEBHOOK_SECRET: Shared secret used for webhook signature verification.
            Not yet consumed by the proxy engine but reserved for future use.
        ENVIRONMENT: Deployment environment. Affects CORS, logging, and
            error detail. Defaults to ``development``.
        is_production: Computed property that returns ``True`` when
            ``ENVIRONMENT`` is ``"production"``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    WEBHOOK_SECRET: str
    API_KEY_SALT: str
    FRONTEND_URL: str = "http://localhost:8000"
    ENVIRONMENT: str = "development"

    @property
    def is_production(self) -> bool:
        """Return ``True`` if the app is running in production mode.

        Returns:
            ``True`` when ``ENVIRONMENT`` equals ``"production"``.
        """
        return self.ENVIRONMENT == "production"


settings = Settings()
