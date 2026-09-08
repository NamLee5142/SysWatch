import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# A file, because a Windows Service has no shell to export from and an
# operator needs somewhere to put a secret that survives a reboot. Environment
# variables still win over it — pydantic-settings resolves init args, then the
# environment, then this file, then the defaults — so a one-off override on the
# command line does not need the file edited.
CONFIG_FILE_VAR = "SYSWATCH_CONFIG_FILE"
DATA_DIR_VAR = "SYSWATCH_DATA_DIR"
CONFIG_FILE_NAME = "syswatch.env"
DATABASE_FILE_NAME = "syswatch.db"
LOG_DIR_NAME = "logs"


def default_data_dir(dev_mode: bool = False) -> str:
    r"""Where the database and logs live when nothing says otherwise.

    ProgramData rather than the working directory, because a Windows Service
    starts in C:\Windows\System32 — a relative default would either fail on
    permissions or leave a database somewhere nobody thinks to look.
    Development keeps a directory beside the checkout, since scattering a
    laptop's test data through ProgramData helps no one.
    """
    if dev_mode or os.name != "nt":
        return "data"

    return str(Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SysWatch")


def config_file_path() -> str:
    """Where settings are read from, if it exists. Absent is not an error.

    Resolved from the environment alone: it is needed to build Settings, so
    it cannot be one of them.
    """
    explicit = os.environ.get(CONFIG_FILE_VAR)
    if explicit:
        return explicit

    data_dir = os.environ.get(DATA_DIR_VAR)
    if data_dir:
        return str(Path(data_dir) / CONFIG_FILE_NAME)

    # No data dir named either, so fall back to the file beside whatever
    # started the process. dev_mode lives in the file we are trying to
    # find, so it cannot be consulted here.
    return CONFIG_FILE_NAME


class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8000
    agent_base_url: str = "http://127.0.0.1:8080"
    # All three derive from data_dir when left empty — see _derive_paths.
    data_dir: str = ""
    database_url: str = ""
    log_dir: str = ""
    log_level: str = "INFO"
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
    # Directory holding the built dashboard (dashboard/dist). Empty disables
    # static serving entirely, which is what a developer running Vite wants:
    # the backend then answers the API and nothing else.
    dashboard_dir: str = ""
    # Relaxes what production must not relax — currently the session cookie's
    # Secure flag, so the dashboard works over plain HTTP in development.
    # Defaults false so the insecure state is the one you opt into.
    dev_mode: bool = False
    # Browser origins allowed to call this API cross-origin. Empty by default,
    # because the backend now serves the dashboard itself and the Vite dev
    # proxy makes development same-origin too — so neither deployment needs a
    # grant, and the one that does should have to say so.
    cors_origins: Annotated[list[str], NoDecode] = []

    # --- alert delivery ------------------------------------------------------
    #
    # Every transport is off until configured. An alerting system that starts
    # mailing strangers because a default pointed somewhere is worse than one
    # that says nothing, and the log notifier means "nothing configured" still
    # leaves a record.
    # Below this, an alert is recorded and logged but not sent outward. An
    # operator who does not want mail about warnings still wants warnings in
    # the log, so this governs the transports rather than the record.
    notify_min_severity: Literal["info", "warning", "critical"] = "warning"
    # Remind about an alert that is still firing, every this many hours. Zero
    # is off, and off is the default: an alerting system that starts mailing
    # every four hours because nobody chose to is worse than one that says a
    # thing once. Acknowledging an alert, or silencing its rule, stops the
    # reminders for it.
    notify_repeat_hours: int = 0
    # How long a metric must stay under its threshold before the alert closes.
    #
    # Not zero, because zero is what produced the problem: a rule at 90% and a
    # metric hovering at 90.2 and 89.9 opened and resolved five times in three
    # minutes on a real run - ten messages about one condition that never
    # really changed. Two minutes is long enough to ride out that oscillation
    # and short enough that a genuine recovery is reported while somebody still
    # cares. Set it to 0 for the old behaviour.
    alert_resolve_after_seconds: int = 120
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    # Never logged, never repr'd. See app/alerts/smtp.py.
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: Annotated[list[str], NoDecode] = []
    # Usually a credential rather than an address: Slack, Discord and Teams all
    # embed a token in the path. Treated like one - never logged, never repr'd.
    webhook_url: str = ""

    model_config = SettingsConfigDict(
        env_prefix="SYSWATCH_",
        case_sensitive=False,
        env_file_encoding="utf-8",
        # A stale key left in the file should not stop the process starting.
        extra="ignore",
    )

    @model_validator(mode="after")
    def _derive_paths(self):
        """Fill the paths that hang off data_dir, unless they were set outright.

        Derived rather than defaulted so that setting SYSWATCH_DATA_DIR alone
        moves the database and the logs together, which is what someone
        relocating an installation means by it.
        """
        if not self.data_dir:
            self.data_dir = default_data_dir(self.dev_mode)

        root = Path(self.data_dir)

        if not self.database_url:
            # as_posix, because a Windows path in a sqlite:/// URL has to use
            # forward slashes or SQLAlchemy reads the backslashes as escapes.
            self.database_url = f"sqlite:///{(root / DATABASE_FILE_NAME).as_posix()}"

        if not self.log_dir:
            self.log_dir = str(root / LOG_DIR_NAME)

        return self

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

    # Recipients take the same comma-separated spelling, for the same reason:
    # a shell variable that has to be valid JSON is a shell variable people get
    # wrong.
    @field_validator("smtp_to", mode="before")
    @classmethod
    def split_smtp_to(cls, value):
        if isinstance(value, str):
            return [address.strip() for address in value.split(",") if address.strip()]
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


def ensure_data_dir(settings) -> Path:
    """Create the data directory. Safe to call repeatedly."""
    root = Path(settings.data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_settings() -> Settings:
    """Settings as the application sees them: file, then environment.

    The file is applied here rather than in model_config so that
    SYSWATCH_CONFIG_FILE is read now instead of at import — which is what lets a
    service point at a file in its own data directory. It also keeps a bare
    Settings() reading only the environment, so a syswatch.env sitting in
    someone's working directory cannot quietly change what a test is testing.
    """
    return Settings(_env_file=config_file_path())


# No module-level `settings = get_settings()`.
#
# It read the config file at import, which is exactly what the docstring above
# says this design avoids. The consequence showed up on a machine with SysWatch
# installed: syswatch.env is readable by Administrators and SYSTEM only, so
# importing anything that reaches config.py from an ordinary prompt raised
# PermissionError - `pytest` included, on the developer's own machine, with no
# way for a fixture to intervene because the read happened at import.
#
# Callers ask for settings when they need them.
