import logging


def configure_logging():
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)
    # reduce verbosity of uvicorn access logs by default
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
