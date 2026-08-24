from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    agent_base_url: str = "http://127.0.0.1:8080"
    database_url: str = "sqlite:///./syswatch.db"
    polling_enabled: bool = True
    poll_interval_seconds: float = 10.0
    # Snapshots older than this are pruned. 0 keeps them forever.
    retention_days: int = 30
    # Browser origins allowed to call this API. Both spellings of the Vite dev
    # server are listed because a browser treats them as different origins.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_prefix="SYSWATCH_",
        case_sensitive=False,
    )

    # NoDecode above turns off the JSON decoding pydantic-settings applies to
    # list fields, which would reject the comma-separated spelling anyone would
    # reach for in a shell. Without it, SYSWATCH_CORS_ORIGINS has to be valid
    # JSON or the process fails to start.
    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
