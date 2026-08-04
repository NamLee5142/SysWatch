"""Run helper for the backend during development."""
from uvicorn import run
from config import settings

if __name__ == "__main__":
    run("app.main:app", host=settings.host, port=settings.port, reload=True)
