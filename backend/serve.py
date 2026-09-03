"""Production entrypoint for the backend.

    python serve.py

Separate from run.py rather than a flag on it. run.py exists to reload on every
edit; this one exists to be started by a service manager and left alone, and a
single script that tries to be both ends up being reached for in the wrong mode.

Configuration comes from the environment and the config file — see
config.py and syswatch.env.example. The command line carries only the two
things an operator overrides while looking at a terminal.
"""
import argparse
import sys

import uvicorn

from app.main import create_app
from config import get_settings

# Why one process, in the message someone sees when they ask for more:
#
#   - the poller would run in every worker, so the agent gets polled N times
#     and the snapshots table absorbs the duplicates
#   - the login rate limiter counts in memory, so N workers allow N times the
#     failed attempts before anything trips
#   - SQLite takes one writer at a time; N pollers writing is contention that
#     buys nothing
#
# None of that is fixed by a flag, so the flag is refused rather than ignored.
NO_WORKERS = (
    "--workers is not supported.\n"
    "\n"
    "SysWatch runs one process on purpose:\n"
    "  * the snapshot poller would run in every worker and collect N times over\n"
    "  * the login rate limit is counted in memory, so N workers allow N times\n"
    "    the attempts\n"
    "  * SQLite serialises writers, so extra ones only contend\n"
    "\n"
    "Scale by moving to PostgreSQL and a shared rate limiter first."
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python serve.py",
        description="Run the SysWatch backend for production.",
    )
    parser.add_argument("--host", help="Overrides SYSWATCH_HOST")
    parser.add_argument("--port", type=int, help="Overrides SYSWATCH_PORT")
    # Accepted so it can be refused with a reason. Left out of the parser it
    # would be an "unrecognized argument", which explains nothing.
    parser.add_argument("--workers", type=int, help=argparse.SUPPRESS)
    return parser


def main(argv=None, run=uvicorn.run):
    args = build_parser().parse_args(argv)

    if args.workers is not None and args.workers != 1:
        print(NO_WORKERS, file=sys.stderr)
        return 1

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port

    run(
        create_app(),
        host=host,
        port=port,
        # No reload: that is run.py's job, and a service manager restarting a
        # process because a file changed is not a thing anyone asked for.
        #
        # log_config=None so uvicorn leaves logging alone. Its default replaces
        # the handlers configured in app/logging_config.py, which is where the
        # file handler lands in the next commit.
        log_config=None,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
