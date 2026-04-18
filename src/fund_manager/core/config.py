"""Central application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "fund-manager"
    app_env: Literal["local", "test", "staging", "production"] = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = Field(default="sqlite:///./data/fund_manager.db")
    default_portfolio_name: str = "main"


@lru_cache
def get_settings() -> Settings:
    """Return cached runtime settings."""
    return Settings()
