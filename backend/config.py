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
    # Whether the poller evaluates alert rules after each successful collection.
    alerts_enabled: bool = True
    # Master switch for authentication. Defaults true so the insecure state is
    # the one you opt into; false restores the anonymous API of Sprint 8 and is
    # meant for local development against a throwaway database.
    auth_enabled: bool = True
    # HMAC key for session-token hashing. No default on purpose: a shipped one
    # would be a published key. Startup enforcement lands with the rest of the
    # security hardening; until then an empty value only breaks sessions.
    session_secret: str = ""
    # How long a session lives from login. Absolute, not sliding: activity
    # updates last_seen_at but does not extend this.
    session_ttl_seconds: int = 28800  # 8 hours
    # Relaxes what production must not relax — currently the session cookie's
    # Secure flag, so the dashboard works over plain HTTP in development.
    # Defaults false so the insecure state is the one you opt into.
    dev_mode: bool = False
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

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origin(cls, value):
        """Refuse "*" outright, rather than letting it reach the middleware.

        The session travels in a cookie, so CORS runs with allow_credentials.
        Starlette answers a wildcard in that mode by echoing back whatever
        Origin asked, which does not mean "this data is public" — it means any
        site a logged-in user visits can call this API as them. There is no
        configuration where that is what someone wanted, so it fails at startup
        instead of silently becoming the most permissive setting available.
        """
        if any(origin == "*" for origin in value):
            raise ValueError(
                "SYSWATCH_CORS_ORIGINS must name explicit origins; "
                '"*" cannot be combined with cookie authentication'
            )
        return value


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
