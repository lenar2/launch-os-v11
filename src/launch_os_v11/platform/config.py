from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAUNCH_OS_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = Field(
        default="local", alias="LAUNCH_OS_ENV"
    )
    database_url: str = Field(
        default="sqlite:///./.local/launch_os_v11.db", alias="LAUNCH_OS_DATABASE_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="LAUNCH_OS_REDIS_URL")
    log_level: str = Field(default="INFO", alias="LAUNCH_OS_LOG_LEVEL")
    enable_db_healthcheck: bool = Field(
        default=False, alias="LAUNCH_OS_ENABLE_DB_HEALTHCHECK"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
