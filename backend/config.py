from pydantic import BaseSettings


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    agent_base_url: str = "http://127.0.0.1:8080"

    class Config:
        env_prefix = "SYSWATCH_"
        case_sensitive = False


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
