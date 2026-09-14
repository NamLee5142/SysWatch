"""Issue, list and revoke the credentials remote agents push with.

    python -m app.auth.create_agent_token --host buildbox
    python -m app.auth.create_agent_token --list
    python -m app.auth.create_agent_token --revoke 3

A command rather than an endpoint, for the same reason as create_admin: an
endpoint that mints a credential has to be switched off the moment it is first
used, and the version of that which is still reachable in production is a
well-known way to lose a system. A command cannot be left enabled.

The token is generated here and printed once. There is deliberately no --token
flag to supply one: an argument would land in the shell's history file and in
the process list, where it outlives the terminal session by a long way - the
same rule that keeps --password off create_admin. It also means an operator
cannot choose a weak one.

Nothing in this module logs. It is a place a plaintext token exists in the
process, so there is deliberately no logger to reach for.
"""
import argparse
import sys

from sqlalchemy.exc import OperationalError

from app.auth.agent_token import hash_token, new_token
from app.db import init_engine
from app.repositories import AgentTokenStore
from config import get_settings

MIGRATE_FIRST = (
    "The agent_tokens table does not exist. Run 'alembic upgrade head' first."
)

NO_SECRET = (
    "SYSWATCH_SESSION_SECRET must be set before issuing an agent token.\n"
    "The token is stored as an HMAC under that key, so a token issued without\n"
    "one could never be verified by a backend that has one - and every token\n"
    "issued under a different key stops working the moment it is set.\n"
    'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m app.auth.create_agent_token",
        description="Issue, list or revoke the credential a remote agent pushes with.",
    )
    parser.add_argument("--host", help="Host name the token speaks for")
    parser.add_argument(
        "--description",
        help="A note for whoever reads this list in a year",
    )
    parser.add_argument(
        "--list", action="store_true", help="Show every token, without the tokens"
    )
    parser.add_argument(
        "--revoke",
        type=int,
        metavar="ID",
        help="Disable a token by id. The row stays, so the record does too",
    )
    parser.add_argument(
        "--restore",
        type=int,
        metavar="ID",
        help="Re-enable a token disabled by mistake",
    )
    return parser


def _listing(store, out):
    tokens = store.all()
    if not tokens:
        print("No agent tokens have been issued.", file=out)
        return 0

    print(f"{'ID':>4}  {'HOST':<24} {'STATE':<8} {'LAST SEEN':<22} DESCRIPTION", file=out)
    for token in tokens:
        seen = token.last_seen_at.isoformat() if token.last_seen_at else "never"
        state = "enabled" if token.enabled else "revoked"
        print(
            f"{token.id:>4}  {token.host_name:<24} {state:<8} {seen:<22} "
            f"{token.description or ''}",
            file=out,
        )
    return 0


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)

    init_engine()
    store = AgentTokenStore()

    try:
        store.all()
    except OperationalError:
        print(MIGRATE_FIRST, file=err)
        return 1

    if args.list:
        return _listing(store, out)

    for flag, enabled, verb in (("revoke", False, "Revoked"), ("restore", True, "Restored")):
        token_id = getattr(args, flag)
        if token_id is None:
            continue
        changed = store.set_enabled(token_id, enabled)
        if changed is None:
            print(f"No agent token with id {token_id}.", file=err)
            return 1
        print(f"{verb} token {token_id} for {changed.host_name!r}.", file=out)
        return 0

    if not args.host:
        print(
            "Give --host, or --list, --revoke or --restore. "
            "Run with --help for the details.",
            file=err,
        )
        return 1

    host = args.host.strip()
    if not host:
        print("Host name must not be empty.", file=err)
        return 1

    # Checked here rather than left to produce a hash under an empty key. A
    # token issued without the secret verifies against nothing.
    secret = get_settings().session_secret
    if not secret:
        print(NO_SECRET, file=err)
        return 1

    existing = [token for token in store.for_host(host) if token.enabled]

    token = new_token()
    record = store.create(
        host_name=host, token_hash=hash_token(token, secret), description=args.description
    )

    print(f"Agent token {record.id} issued for {host!r}.", file=out)
    print(file=out)
    print(token, file=out)
    print(file=out)
    print(
        "Shown once. It is stored as a hash, so this cannot be recovered - "
        "issue a new one if it is lost.",
        file=out,
    )
    print(
        "Put it in the agent's configuration on that machine, in a file only "
        "Administrators and SYSTEM can read.",
        file=out,
    )

    if existing:
        # Normal during a rotation, and worth saying out loud: the old one still
        # works until it is revoked, which is the point, and forgetting to
        # revoke it is the failure mode.
        ids = ", ".join(str(token.id) for token in existing)
        print(file=out)
        print(
            f"Note: {host!r} already has {len(existing)} enabled token(s): {ids}. "
            f"Revoke with --revoke <id> once the new one is deployed.",
            file=out,
        )

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
