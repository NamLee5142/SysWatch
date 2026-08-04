from fastapi import FastAPI
from app.api import health
import logging
from app import logging_config as app_logging

app = FastAPI(title="SysWatch Backend")

app.include_router(health.router)


@app.on_event("startup")
async def on_startup():
    app_logging.configure_logging()
    logging.getLogger("uvicorn").info("Starting SysWatch Backend")


@app.on_event("shutdown")
async def on_shutdown():
    logging.getLogger("uvicorn").info("Shutting down SysWatch Backend")


@app.get("/")
def root():
    return {"service": "syswatch-backend"}
