import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import logging_config as app_logging
from app.api import health, snapshot, snapshots
from app.client import AgentClient
from app.db import dispose_engine, init_engine
from app.repositories import SnapshotStore
from app.services.snapshot_poller import SnapshotPoller
from app.services.snapshot_service import SnapshotService
from config import get_settings


def create_poller(settings):
    """Build the poller that collects snapshots whether or not anyone is asking."""
    service = SnapshotService(
        client=AgentClient(settings.agent_base_url),
        store=SnapshotStore(),
    )
    return SnapshotPoller(service, interval_seconds=settings.poll_interval_seconds)


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

    app.include_router(health.router)
    app.include_router(snapshot.router)
    app.include_router(snapshots.router)

    @app.get("/")
    def root():
        return {"service": "syswatch-backend"}

    return app


app = create_app()
