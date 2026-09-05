"""The version of SysWatch this process is running.

One number, read from the VERSION file at the repository root, so the agent,
the backend, the dashboard and the installer cannot drift apart and report four
different things about the same deployment. `scripts/sync_version.py` propagates
it to the files that must hold a literal copy — package.json cannot read a file
at build time — and `--check` fails when they have diverged.

Resolved once at import. The file is looked for beside the backend first,
because an install directory holds a copy of the backend without the repository
around it.
"""
import os
from pathlib import Path

VERSION_FILE_NAME = "VERSION"
VERSION_VAR = "SYSWATCH_VERSION"
UNKNOWN = "unknown"

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Ordered by how specific each location is to this process, not by likelihood.
CANDIDATES = (
    BACKEND_ROOT / VERSION_FILE_NAME,
    BACKEND_ROOT.parent / VERSION_FILE_NAME,
)


def read_version(candidates=CANDIDATES, environ=None):
    """The version string, or "unknown" if there is nothing to read.

    Never raises. A missing or unreadable VERSION file is a packaging mistake
    worth seeing in the health response, and not a reason for a process that is
    otherwise working to refuse to start.
    """
    environ = os.environ if environ is None else environ

    override = environ.get(VERSION_VAR, "").strip()
    if override:
        return override

    for candidate in candidates:
        try:
            content = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue

        if content:
            return content

    return UNKNOWN


VERSION = read_version()
