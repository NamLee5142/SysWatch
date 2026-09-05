"""A guard against committing a secret, rather than a note saying we checked.

A one-time audit is true on the day it is written. This runs on every suite,
so the answer stays true — and it fails on the change that would break it
rather than on the day someone thinks to look again.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Shapes that are a secret whatever the surrounding code says.
SECRET_PATTERNS = {
    "private key": re.compile(r"BEGIN (RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    "Slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "Azure/Google key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
}

# Whatever the application writes while running. Every one of these is either
# the monitored machine's telemetry or a session secret.
RUNTIME_ARTIFACTS = [
    "backend/data/syswatch.db",
    "backend/data/syswatch.db-wal",
    "backend/data/syswatch.db-shm",
    "backend/data/syswatch.db.backup",
    "backend/data/backup-2026-09-04.db",
    "backend/data/syswatch.env",
    "backend/data/logs/syswatch.log",
    # Rotated files: the plain *.log pattern does not match a .log.3 suffix,
    # which is how a directory-level rule earns its place.
    "backend/data/logs/syswatch.log.3",
    "agent/logs/agent.log",
    "agent/logs/agent.log.1",
    "backend/syswatch.env",
    "backend/.env",
    "backend/.env.production",
    "dashboard/.env.local",
    # `app.db.backup` writes to an arbitrary destination, so a backup taken from
    # the repository root is a plausible accident — and it carries every argon2
    # password hash and every live session token hash.
    "backup-2026-09-04.db",
    "backend/backup.db",
    "snapshot.sqlite3",
    # Key material. None of this exists yet; the point is that it is ignored
    # before it arrives rather than after.
    "certs/server.key",
    "certs/server.pem",
    "id_rsa",
    "deploy/secrets.json",
]


def git(*arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def tracked_files():
    listing = git("ls-files")
    if listing.returncode != 0:
        pytest.skip("not a git checkout")
    return [line for line in listing.stdout.splitlines() if line]


@pytest.mark.parametrize("path", RUNTIME_ARTIFACTS)
def test_runtime_artifacts_cannot_be_committed(path):
    result = git("check-ignore", "-q", path)

    assert result.returncode == 0, (
        f"{path} is not ignored. Everything the application writes at runtime is "
        "either the monitored machine's telemetry or a secret."
    )


def test_no_runtime_artifact_is_already_tracked():
    tracked = set(tracked_files())

    accidents = [path for path in RUNTIME_ARTIFACTS if path in tracked]

    # Ignoring a file does not untrack one that is already committed.
    assert accidents == []


def test_no_tracked_file_contains_a_secret_shaped_string():
    findings = []

    for path in tracked_files():
        full = REPO_ROOT / path
        if not full.is_file() or full.stat().st_size > 1_000_000:
            continue

        try:
            text = full.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; nothing to read a key out of

        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text) and full.name != Path(__file__).name:
                findings.append(f"{path}: looks like a {name}")

    assert findings == [], "\n".join(findings)


def test_the_example_config_never_gains_a_real_secret():
    example = REPO_ROOT / "backend" / "syswatch.env.example"
    assert example.is_file()

    for number, line in enumerate(example.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # It is committed, so the only safe content is commentary. An
        # uncommented assignment here is a value somebody chose.
        pytest.fail(f"syswatch.env.example line {number} is not a comment: {stripped!r}")
