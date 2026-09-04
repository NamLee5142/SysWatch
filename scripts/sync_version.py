"""Propagate the version in VERSION to the files that must hold a copy.

    python scripts/sync_version.py           # write
    python scripts/sync_version.py --check   # report drift, change nothing

Most of the tree reads VERSION directly: CMake reads it at configure time, and
the backend reads it at import. npm cannot — package.json needs a literal
string — so those files are written here instead of being kept in step by hand.

--check is the half that matters. A sync script only helps the person who
remembers to run it; the check runs in the test suite and in CI, where nobody
has to remember.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"

# Anything looser lets "0.10" or "1.0.0-dev " through, and CMake's project()
# rejects both after the fact, at configure time, in someone else's checkout.
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

VERSION_FIELD = re.compile(r'("version"\s*:\s*")[^"]*(")')

# npm writes the project's own version into a lockfile twice: once at the top
# and once in the packages[""] entry describing the root package. Updating only
# the first leaves a lockfile that disagrees with itself.
LOCKFILE_ROOT_PACKAGE = '"": {'


class VersionProblem(Exception):
    """The version could not be read, or a file could not be brought in line."""


def read_version(path=VERSION_FILE):
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise VersionProblem(f"Cannot read {path}: {error}") from error

    if not SEMVER.match(raw):
        raise VersionProblem(
            f"{path} contains {raw!r}, which is not MAJOR.MINOR.PATCH. "
            "CMake's project(VERSION) rejects anything else."
        )

    return raw


def package_versions(path):
    """Every place `path` states the project's own version."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VersionProblem(f"Cannot read {path}: {error}") from error

    found = {"version": document.get("version")}

    root_package = document.get("packages", {}).get("")
    if isinstance(root_package, dict):
        found['packages[""].version'] = root_package.get("version")

    return found


def _set_version_after(text, anchor, version, path):
    """Replace the first "version" field at or after `anchor`."""
    start = 0
    if anchor is not None:
        start = text.find(anchor)
        if start == -1:
            raise VersionProblem(f"No {anchor} block in {path}")

    match = VERSION_FIELD.search(text, start)
    if match is None:
        raise VersionProblem(f'No "version" field after {anchor or "the start"} in {path}')

    return text[: match.start()] + match.group(1) + version + match.group(2) + text[match.end() :]


def write_versions(path, version):
    """Rewrite only the version fields. Returns whether the file changed.

    A targeted edit rather than json.dump, which would reformat the whole file
    — a 10,000-line diff on a lockfile — and drop the trailing newline npm
    writes.
    """
    original = path.read_text(encoding="utf-8")
    updated = _set_version_after(original, None, version, path)

    if LOCKFILE_ROOT_PACKAGE in updated:
        updated = _set_version_after(updated, LOCKFILE_ROOT_PACKAGE, version, path)

    if updated != original:
        path.write_text(updated, encoding="utf-8")

    return updated != original


def targets(repo_root=REPO_ROOT):
    """The files holding a literal copy of the version."""
    return [
        ("dashboard/package.json", repo_root / "dashboard" / "package.json"),
        ("dashboard/package-lock.json", repo_root / "dashboard" / "package-lock.json"),
    ]


def drift(version, repo_root=REPO_ROOT):
    """Every field that disagrees with `version`, as a list of descriptions."""
    problems = []

    for label, path in targets(repo_root):
        if not path.exists():
            continue

        for field, found in package_versions(path).items():
            if found != version:
                problems.append(
                    f"{label} {field} is {found!r}, VERSION says {version!r}"
                )

    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python scripts/sync_version.py",
        description="Propagate VERSION to the files that hold a literal copy.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift and exit non-zero without writing anything",
    )
    args = parser.parse_args(argv)

    try:
        version = read_version()
    except VersionProblem as problem:
        print(str(problem), file=sys.stderr)
        return 1

    if args.check:
        problems = drift(version)
        for problem in problems:
            print(problem, file=sys.stderr)

        if problems:
            print("Run: python scripts/sync_version.py", file=sys.stderr)
            return 1

        print(f"Everything is at {version}.")
        return 0

    changed = []
    for label, path in targets():
        if not path.exists():
            continue
        try:
            if write_versions(path, version):
                changed.append(label)
        except VersionProblem as problem:
            print(str(problem), file=sys.stderr)
            return 1

    if changed:
        print(f"Set {version} in: {', '.join(changed)}")
    else:
        print(f"Already at {version}.")

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
