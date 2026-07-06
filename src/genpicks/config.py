from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file.

    All variables are prefixed with GENPICKS_, e.g. GENPICKS_DATABASE_URL.
    """

    model_config = SettingsConfigDict(env_prefix="GENPICKS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/genpicks.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
