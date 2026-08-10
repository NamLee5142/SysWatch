"""Run helper for the backend during development."""
from uvicorn import run

from app.main import create_app
from config import settings

app = create_app()

if __name__ == "__main__":
    run(app, host=settings.host, port=settings.port, reload=True)
