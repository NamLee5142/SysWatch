import logging
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import logging_config as app_logging
from app.alerts import AlertEngine
from app.alerts.notifier import build_notifier, verify_notification_configuration
from app.api import (
    alert_rules,
    alerts,
    auth,
    health,
    hosts,
    ingest,
    snapshot,
    snapshots,
    status,
)
from app.auth.dependencies import require_authenticated_user
from app.client import AgentClient
from app.db import dispose_engine, init_engine
from app.repositories import AlertRuleStore, AlertStore, SnapshotStore
from app.security import SecurityHeadersMiddleware, verify_security_configuration
from app.spa import mount_dashboard
from app.version import VERSION
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import ensure_data_dir, get_settings


def create_poller(settings):
    """Build the poller that collects snapshots whether or not anyone is asking."""
    store = SnapshotStore()
    service = SnapshotService(client=AgentClient(settings.agent_base_url), store=store)

    engine = None
    if settings.alerts_enabled:
        engine = AlertEngine(
            AlertRuleStore(),
            AlertStore(),
            notifier=build_notifier(settings),
            repeat_after=(
                timedelta(hours=settings.notify_repeat_hours)
                if settings.notify_repeat_hours
                else None
            ),
        )

    return SnapshotPoller(
        service,
        interval_seconds=settings.poll_interval_seconds,
        store=store,
        retention_days=settings.retention_days,
        engine=engine,
        agent_url=settings.agent_base_url,
    )


def warn_about_a_stray_database(settings, logger):
    """Say something when the old, working-directory database is still around.

    Before this sprint the default was ./syswatch.db, relative to wherever the
    process happened to start. Anyone upgrading gets a new, empty database in
    the data directory and no explanation for where their history went.
    """
    legacy = Path("syswatch.db")

    if not legacy.is_file():
        return

    if legacy.resolve() == Path(settings.data_dir).resolve() / "syswatch.db":
        return

    logger.warning(
        "Found %s in the working directory, but the configured database is %s. "
        "Earlier versions defaulted to the working directory; move the file or "
        "set SYSWATCH_DATABASE_URL if that is the one you meant.",
        legacy.resolve(),
        settings.database_url,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_data_dir(settings)

    # Configured before anything else is logged, or the first few lines of a
    # failed startup — the ones that say why — go to a console nobody is
    # watching and never reach the file.
    log_file = app_logging.configure_logging(settings)
    logger = logging.getLogger("uvicorn")

    logger.info("Starting SysWatch Backend %s", VERSION)
    logger.info("Data directory: %s", settings.data_dir)
    logger.info("Log file: %s", log_file or "none (console only)")
    logger.info("Agent: %s", settings.agent_base_url)
    logger.info(
        "Authentication: %s | polling: %s | alerts: %s",
        "on" if settings.auth_enabled else "OFF",
        "on" if settings.polling_enabled else "off",
        "on" if settings.alerts_enabled else "off",
    )

    # A process that cannot authenticate safely should fail loudly here rather
    # than serve traffic and find out later.
    for warning in verify_security_configuration(settings):
        logger.warning(warning)

    # Beside the security check, and fatal in the same way. A transport that
    # cannot deliver should be found now rather than when the first alert does
    # not arrive.
    for warning in verify_notification_configuration(settings):
        logger.warning(warning)

    warn_about_a_stray_database(settings, logger)

    # The engine holds a connection pool and is created once here rather than
    # per request, which is what get_settings() being uncached would otherwise
    # encourage.
    init_engine()

    poller = create_poller(settings) if settings.polling_enabled else None
    if poller is not None:
        poller.start()
    else:
        logger.info("Snapshot polling is disabled")

    app.state.poller = poller

    reason = "requested"
    try:
        yield
    except BaseException as stopping:
        # Says which signal or error took the process down, rather than leaving
        # a log that simply stops.
        reason = f"{type(stopping).__name__}: {stopping}" if str(stopping) else type(stopping).__name__
        raise
    finally:
        logger.info("Shutting down SysWatch Backend (%s)", reason)
        if poller is not None:
            await poller.stop()
        dispose_engine()
        logger.info("Shutdown complete")


# Everything the backend answers hangs off this. The dashboard owns every
# other path, so the split has to be a prefix rather than a route-by-route
# arrangement someone can forget to follow.
API_PREFIX = "/api"


def create_app() -> FastAPI:
    # Here as well as in the lifespan: create_app() runs at import, and the
    # dashboard mount below logs during it. Without this those messages are
    # emitted before logging is configured and vanish.
    app_logging.configure_logging()

    settings = get_settings()

    # debug stays off: FastAPI's debug mode returns a traceback to the
    # caller, which hands out file paths, local variables and library
    # versions to anyone who can provoke a 500.
    #
    # The documentation UI is a development tool. In production it is a free,
    # always-current map of every endpoint and every request shape, offered to
    # anyone who can reach the port. Passed as None at construction rather than
    # unregistered afterwards, so there is no window where the routes exist.
    docs = settings.dev_mode
    app = FastAPI(
        title="SysWatch Backend",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )

    app.add_middleware(SecurityHeadersMiddleware)

    # Without this the dashboard cannot read the API at all: the browser blocks
    # a cross-origin fetch before the request reaches any route.
    app.add_middleware(
        CORSMiddleware,
        # Never "*". Settings refuses it outright, because Starlette answers a
        # wildcard under allow_credentials by echoing back whatever Origin
        # asked — which is not "any origin may read public data", it is "any
        # site may make requests as the logged-in user".
        allow_origins=settings.cors_origins,
        # Required now that the session lives in a cookie: without it the
        # browser sends the credential on no cross-origin request and accepts
        # the Set-Cookie on none either.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        # Narrowed from "*". The API takes JSON bodies and a cookie the browser
        # attaches itself; nothing else needs naming.
        allow_headers=["Content-Type"],
        # Only the CORS-safelisted response headers reach page JavaScript by
        # default, and Retry-After is not one of them — without this the login
        # form cannot tell the user how long the rate limit has to run.
        expose_headers=["Retry-After"],
    )

    # Every route lives under /api so the dashboard can own every other
    # path. Without the prefix, GET /alerts is ambiguous: it is both this
    # API's alert list and the page a browser deep-links to.
    app.include_router(health.router, prefix=API_PREFIX)
    # Before the protected routers, and itself unprotected: this is where a
    # caller with no session goes to get one.
    app.include_router(auth.router, prefix=API_PREFIX)
    # Everything past this point needs a session. /health stays public so a
    # load balancer can ask whether the process is alive; /status does not,
    # because it reports poll timing, the last error and whether the agent is
    # reachable — operational detail that is nobody's business anonymously.
    #
    # Applied per router rather than as middleware so the dependency tree is
    # the policy: a new router is unprotected only if someone leaves it out of
    # this list on purpose.
    # Not in the protected list below, and not unprotected either: every route
    # on it carries require_agent, which authenticates a bearer token rather
    # than a session cookie. Adding the session dependency here would demand a
    # cookie an unattended service has no way to obtain.
    app.include_router(ingest.router, prefix=API_PREFIX)

    protected = [Depends(require_authenticated_user)]

    app.include_router(status.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(hosts.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(snapshot.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(snapshots.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(alerts.router, prefix=API_PREFIX, dependencies=protected)
    # The alert-rule writes carry require_admin on the routes themselves.
    app.include_router(alert_rules.router, prefix=API_PREFIX, dependencies=protected)

    # Last, so every /api route is matched first. Everything left over is the
    # dashboard's — including "/", which is why no route claims it.
    mount_dashboard(app, settings.dashboard_dir)

    return app


_app = None


def __getattr__(name):
    """Build the application when `app` is asked for, not when this is imported.

    `uvicorn app.main:app` is a documented way to run this, so the attribute
    has to exist - but constructing it at import meant that importing anything
    from this module configured logging and read the config file as a side
    effect.

    On a machine with SysWatch installed that is fatal rather than untidy:
    syswatch.env is readable by Administrators and SYSTEM only, so `import
    app.main` from an ordinary prompt raised PermissionError. The test suite
    imports create_app in conftest, so `pytest` stopped working on any
    developer machine that had installed the thing it was testing - and no
    fixture could prevent it, because the read happened before fixtures exist.
    """
    global _app

    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    if _app is None:
        _app = create_app()

    return _app
