import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import logging_config as app_logging
from app.alerts import AlertEngine
from app.api import alerts, health, hosts, snapshot, snapshots, status
from app.client import AgentClient
from app.db import dispose_engine, init_engine
from app.repositories import AlertRuleStore, AlertStore, SnapshotStore
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import get_settings


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_logging.configure_logging()
    logger = logging.getLogger("uvicorn")
    logger.info("Starting SysWatch Backend")

    settings = get_settings()

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


def create_app() -> FastAPI:
    app = FastAPI(title="SysWatch Backend", lifespan=lifespan)

    # Without this the dashboard cannot read the API at all: the browser blocks
    # a cross-origin fetch before the request reaches any route.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        # The API is read-only and unauthenticated. Allowing credentials would
        # let a browser attach cookies to these requests, which is exactly what
        # should not happen until Phase 4 adds authentication.
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(status.router)
    app.include_router(hosts.router)
    app.include_router(snapshot.router)
    app.include_router(snapshots.router)
    app.include_router(alerts.router)

    @app.get("/")
    def root():
        return {"service": "syswatch-backend"}

    return app


app = create_app()
