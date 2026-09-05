"""Run helper for the backend during development."""
from uvicorn import run

from app.main import create_app
from config import get_settings

_app = None


def __getattr__(name):
    """Same reason as app/main.py: built on access, not on import.

    uvicorn's reloader imports this module as "run:app" and reads the
    attribute, which still works. Importing it for any other reason no longer
    reads a config file this process may not be allowed to open.
    """
    global _app

    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    if _app is None:
        _app = create_app()

    return _app


if __name__ == "__main__":
    # uvicorn needs an import string (not the app object) to enable reload
    settings = get_settings()
    run("run:app", host=settings.host, port=settings.port, reload=True)
