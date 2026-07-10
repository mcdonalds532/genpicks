from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file.

    All variables are prefixed with GENPICKS_, e.g. GENPICKS_DATABASE_URL.
    """

    model_config = SettingsConfigDict(env_prefix="GENPICKS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/genpicks.db"
    # the-odds-api.com key (free Starter tier); scrape --source oddsapi
    odds_api_key: str | None = None
    # comma-separated origins allowed to call the API from a browser;
    # the deployed frontend's domain goes here
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # shared secret between the Next.js server and the API: authorizes the
    # internal user-sync endpoint and unlocks gated markets for subscribed
    # users. Unset (the default) fails closed: sync is unavailable and try
    # markets stay locked for everyone.
    internal_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
