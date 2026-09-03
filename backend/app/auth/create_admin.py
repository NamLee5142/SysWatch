"""Create the first account, or reset an existing one's password.

    python -m app.auth.create_admin

A command rather than a POST /setup-admin endpoint. An endpoint that mints an
administrator has to be switched off the moment it is first used, and the
version of that which is still reachable in production is a well-known way to
lose a system. A command cannot be left enabled.

The password is only ever read from a hidden prompt. There is deliberately no
--password flag: an argument would land in the shell's history file and in the
process list, where it would outlive the terminal session by a long way.
"""
import argparse
import getpass
import sys

from sqlalchemy.exc import OperationalError

from app.auth.password import WeakPassword, hash_password
from app.db import init_engine
from app.repositories import UserStore

MIGRATE_FIRST = (
    "The users table does not exist. Run 'alembic upgrade head' first."
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m app.auth.create_admin",
        description="Create a SysWatch account, or reset an existing one's password.",
    )
    parser.add_argument("--username", help="Prompted for when not given")
    parser.add_argument(
        "--role",
        choices=("admin", "viewer"),
        default="admin",
        help="Role for a new account (default: admin)",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Replace the password of an account that already exists",
    )
    return parser


def read_password(prompt=getpass.getpass):
    """Read and confirm a password from a hidden prompt.

    Returns the password, or None when the two entries differ. Nothing is
    echoed and nothing is returned to the caller's shell.
    """
    first = prompt("Password: ")
    second = prompt("Confirm:  ")

    if first != second:
        return None

    return first


def main(argv=None, prompt=getpass.getpass, ask=input):
    args = build_parser().parse_args(argv)

    init_engine()
    store = UserStore()

    try:
        existing_accounts = store.count()
    except OperationalError:
        print(MIGRATE_FIRST, file=sys.stderr)
        return 1

    username = (args.username or ask("Username: ")).strip()
    if not username:
        print("Username must not be empty.", file=sys.stderr)
        return 1

    existing = store.by_username(username)

    if existing is not None and not args.reset_password:
        print(
            f"User {username!r} already exists. "
            "Pass --reset-password to replace their password.",
            file=sys.stderr,
        )
        return 1

    if existing is None and args.reset_password:
        print(f"No user named {username!r} to reset.", file=sys.stderr)
        return 1

    password = read_password(prompt)
    if password is None:
        print("Passwords did not match.", file=sys.stderr)
        return 1

    try:
        password_hash = hash_password(password)
    except WeakPassword as weak:
        # The policy message is safe to show: it describes the rule, not the
        # attempt.
        print(f"{weak}.", file=sys.stderr)
        return 1

    if existing is not None:
        store.set_password(existing.id, password_hash)
        print(f"Password updated for {username!r}.")
        return 0

    store.create(username=username, password_hash=password_hash, role=args.role)
    print(f"Created {args.role} {username!r}.")

    if existing_accounts == 0:
        print("This is the first account. Log in at the dashboard to continue.")

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
