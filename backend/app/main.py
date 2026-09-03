import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import logging_config as app_logging
from app.alerts import AlertEngine
from app.api import alert_rules, alerts, auth, health, hosts, snapshot, snapshots, status
from app.auth.dependencies import require_authenticated_user
from app.client import AgentClient
from app.db import dispose_engine, init_engine
from app.repositories import AlertRuleStore, AlertStore, SnapshotStore
from app.security import SecurityHeadersMiddleware, verify_security_configuration
from app.spa import mount_dashboard
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import ensure_data_dir, get_settings


def create_poller(settings):
    """Build the poller that collects snapshots whether or not anyone is asking."""
    store = SnapshotStore()
    service = SnapshotService(client=AgentClient(settings.agent_base_url), store=store)

    engine = None
    if settings.alerts_enabled:
        engine = AlertEngine(AlertRuleStore(), AlertStore())

    return SnapshotPoller(
        service,
        interval_seconds=settings.poll_interval_seconds,
        store=store,
        retention_days=settings.retention_days,
        engine=engine,
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
    app_logging.configure_logging()
    logger = logging.getLogger("uvicorn")
    logger.info("Starting SysWatch Backend")

    settings = get_settings()

    # Before anything else: a process that cannot authenticate safely should
    # fail loudly here rather than serve traffic and find out later.
    for warning in verify_security_configuration(settings):
        logger.warning(warning)

    data_dir = ensure_data_dir(settings)
    logger.info("Data directory: %s", data_dir)
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

    try:
        yield
    finally:
        if poller is not None:
            await poller.stop()
        dispose_engine()
        logger.info("Shutting down SysWatch Backend")


# Everything the backend answers hangs off this. The dashboard owns every
# other path, so the split has to be a prefix rather than a route-by-route
# arrangement someone can forget to follow.
API_PREFIX = "/api"


def create_app() -> FastAPI:
    # Here as well as in the lifespan: create_app() runs at import, and the
    # dashboard mount below logs during it. Without this those messages are
    # emitted before logging is configured and vanish.
    app_logging.configure_logging()

    # debug stays off: FastAPI's debug mode returns a traceback to the
    # caller, which hands out file paths, local variables and library
    # versions to anyone who can provoke a 500.
    app = FastAPI(title="SysWatch Backend", lifespan=lifespan)

    app.add_middleware(SecurityHeadersMiddleware)

    # Without this the dashboard cannot read the API at all: the browser blocks
    # a cross-origin fetch before the request reaches any route.
    app.add_middleware(
        CORSMiddleware,
        # Never "*". Settings refuses it outright, because Starlette answers a
        # wildcard under allow_credentials by echoing back whatever Origin
        # asked — which is not "any origin may read public data", it is "any
        # site may make requests as the logged-in user".
        allow_origins=get_settings().cors_origins,
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
    mount_dashboard(app, get_settings().dashboard_dir)

    return app


app = create_app()
