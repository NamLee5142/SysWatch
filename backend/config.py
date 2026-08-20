from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    agent_base_url: str = "http://127.0.0.1:8080"
    database_url: str = "sqlite:///./syswatch.db"
    polling_enabled: bool = True
    poll_interval_seconds: float = 10.0
    # Snapshots older than this are pruned. 0 keeps them forever.
    retention_days: int = 30

    model_config = SettingsConfigDict(
        env_prefix="SYSWATCH_",
        case_sensitive=False,
    )


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
