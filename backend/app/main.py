from fastapi import FastAPI
from app.api import health

app = FastAPI(title="SysWatch Backend")

app.include_router(health.router)

@app.get("/")
def root():
    return {"service": "syswatch-backend"}
