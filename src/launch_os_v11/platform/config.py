from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LAUNCH_OS_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "staging", "production"] = Field(
        default="local", alias="LAUNCH_OS_ENV"
    )
    database_url: str = Field(
        default=(
            "postgresql+psycopg://launch_os_v11:launch_os_v11@localhost:5432/"
            "launch_os_v11"
        ),
        alias="LAUNCH_OS_DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="LAUNCH_OS_REDIS_URL")
    log_level: str = Field(default="INFO", alias="LAUNCH_OS_LOG_LEVEL")
    launch_workflow_enabled: bool = Field(
        default=False,
        alias="LAUNCH_OS_FEATURE_V11_LAUNCH_WORKFLOW",
    )
    ai_team_enabled: bool = Field(default=False, alias="LAUNCH_OS_FEATURE_V11_AI_TEAM")
    max_decision_revision_rounds: int = Field(
        default=2,
        alias="LAUNCH_OS_MAX_DECISION_REVISION_ROUNDS",
    )
    max_asset_revision_rounds: int = Field(
        default=2,
        alias="LAUNCH_OS_MAX_ASSET_REVISION_ROUNDS",
    )
    ai_model_provider: str | None = Field(default=None, alias="LAUNCH_OS_AI_MODEL_PROVIDER")
    ai_openai_text_model: str | None = Field(
        default=None,
        alias="LAUNCH_OS_AI_OPENAI_TEXT_MODEL",
    )
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        alias="TELEGRAM_BOT_TOKEN",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
