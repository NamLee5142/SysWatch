"""Run helper for the backend during development."""
from uvicorn import run

from app.main import create_app
from config import settings

app = create_app()

if __name__ == "__main__":
    # uvicorn needs an import string (not the app object) to enable reload
    run("run:app", host=settings.host, port=settings.port, reload=True)
