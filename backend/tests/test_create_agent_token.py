"""Issuing an agent's credential from the command line.

The done-when for this commit is a negative: the token never reaches shell
history, a log, or the process list. Two of those are properties of the
interface rather than of a run, so they are tested against the parser and the
source.
"""
import re
from pathlib import Path

import pytest

from app.auth.agent_token import hash_token
from app.auth.create_agent_token import build_parser, main
from app.repositories import AgentTokenStore

SECRET = "a-deployment-secret-long-enough-to-be-real"

MODULE = Path(__file__).resolve().parents[1] / "app" / "auth" / "create_agent_token.py"


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SYSWATCH_SESSION_SECRET", SECRET)


def issued_token(captured):
    """The token from the command's output: the one line that is only a token."""
    lines = [line.strip() for line in captured.out.splitlines() if line.strip()]
    candidates = [line for line in lines if re.fullmatch(r"[A-Za-z0-9_-]{43,}", line)]
    assert len(candidates) == 1, f"expected exactly one token line, got {candidates}"
    return candidates[0]


# --- the interface must not be able to carry a secret ------------------------


def test_there_is_no_token_flag():
    """An argument would land in shell history and the process list.

    The same rule that keeps --password off create_admin, and the reason the
    token is generated here rather than supplied.
    """
    options = {action.option_strings[0] for action in build_parser()._actions
               if action.option_strings}

    assert "--token" not in options
    assert "--secret" not in options


def test_the_module_has_no_logger():
    """A plaintext token exists in this process; nothing here may write a file."""
    code = chr(10).join(
        line for line in MODULE.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]

    assert "import logging" not in code
    assert "getLogger" not in code
    assert "logger" not in body


# --- issuing ------------------------------------------------------------------


def test_it_issues_a_token_for_a_host(database, capsys):
    assert main(["--host", "buildbox"]) == 0

    captured = capsys.readouterr()
    assert "issued for 'buildbox'" in captured.out

    tokens = AgentTokenStore().for_host("buildbox")
    assert len(tokens) == 1
    assert tokens[0].enabled is True


def test_the_printed_token_is_the_one_that_was_stored(database, capsys):
    main(["--host", "buildbox"])

    token = issued_token(capsys.readouterr())
    found = AgentTokenStore().by_token_hash(hash_token(token, SECRET))

    assert found is not None
    assert found.host_name == "buildbox"


def test_the_token_is_not_stored_in_any_column(database, capsys):
    """Shown once, and unrecoverable afterwards."""
    main(["--host", "buildbox"])
    token = issued_token(capsys.readouterr())

    from sqlalchemy import select

    from app.db import get_session
    from app.db.models import AgentTokenRecord

    with get_session() as session:
        row = session.execute(select(AgentTokenRecord)).scalars().one()
        values = " ".join(str(getattr(row, c.name)) for c in row.__table__.columns)

    assert token not in values


def test_it_says_the_token_cannot_be_recovered(database, capsys):
    main(["--host", "buildbox"])

    assert "Shown once" in capsys.readouterr().out


def test_a_description_is_kept(database, capsys):
    main(["--host", "buildbox", "--description", "the box in the server room"])

    assert AgentTokenStore().for_host("buildbox")[0].description == (
        "the box in the server room"
    )


def test_two_tokens_for_a_host_are_allowed_and_flagged(database, capsys):
    """Rotation is normal; forgetting to revoke the old one is the failure."""
    main(["--host", "buildbox"])
    capsys.readouterr()

    main(["--host", "buildbox"])

    output = capsys.readouterr().out
    assert "already has 1 enabled token" in output
    assert "--revoke" in output


def test_an_empty_host_is_refused(database, capsys):
    assert main(["--host", "   "]) == 1
    assert "must not be empty" in capsys.readouterr().err


def test_it_needs_something_to_do(database, capsys):
    assert main([]) == 1
    assert "--host" in capsys.readouterr().err


# --- the secret ---------------------------------------------------------------


def test_it_refuses_without_a_session_secret(database, capsys, monkeypatch):
    """A token hashed under an empty key verifies against nothing.

    Issuing one anyway would produce a credential that looks right, is written
    down, deployed to a machine, and fails the first time it is used - by which
    point the operator is debugging the agent rather than the command that
    misled them.
    """
    monkeypatch.delenv("SYSWATCH_SESSION_SECRET", raising=False)

    assert main(["--host", "buildbox"]) == 1

    captured = capsys.readouterr()
    assert "SYSWATCH_SESSION_SECRET must be set" in captured.err
    assert AgentTokenStore().all() == []


def test_the_error_does_not_print_a_secret(database, capsys, monkeypatch):
    monkeypatch.delenv("SYSWATCH_SESSION_SECRET", raising=False)
    main(["--host", "buildbox"])

    assert SECRET not in capsys.readouterr().err


# --- listing and revoking -----------------------------------------------------


def test_listing_shows_hosts_but_no_tokens(database, capsys):
    main(["--host", "buildbox"])
    token = issued_token(capsys.readouterr())

    assert main(["--list"]) == 0

    listing = capsys.readouterr().out
    assert "buildbox" in listing
    assert "enabled" in listing
    assert token not in listing


def test_listing_shows_the_stored_hash_to_nobody(database, capsys):
    main(["--host", "buildbox"])
    capsys.readouterr()
    stored = AgentTokenStore().for_host("buildbox")[0]

    main(["--list"])

    assert stored.token_hash not in capsys.readouterr().out


def test_an_empty_list_says_so(database, capsys):
    assert main(["--list"]) == 0
    assert "No agent tokens" in capsys.readouterr().out


def test_revoking_disables_without_deleting(database, capsys):
    main(["--host", "buildbox"])
    capsys.readouterr()
    token_id = AgentTokenStore().for_host("buildbox")[0].id

    assert main(["--revoke", str(token_id)]) == 0

    assert "Revoked" in capsys.readouterr().out
    remaining = AgentTokenStore().get(token_id)
    assert remaining is not None
    assert remaining.enabled is False


def test_a_revoked_token_can_be_restored(database, capsys):
    main(["--host", "buildbox"])
    token_id = AgentTokenStore().for_host("buildbox")[0].id
    main(["--revoke", str(token_id)])
    capsys.readouterr()

    assert main(["--restore", str(token_id)]) == 0
    assert AgentTokenStore().get(token_id).enabled is True


def test_revoking_an_unknown_id_is_an_error(database, capsys):
    assert main(["--revoke", "999"]) == 1
    assert "No agent token with id 999" in capsys.readouterr().err


def test_listing_marks_a_revoked_token(database, capsys):
    main(["--host", "buildbox"])
    token_id = AgentTokenStore().for_host("buildbox")[0].id
    main(["--revoke", str(token_id)])
    capsys.readouterr()

    main(["--list"])

    assert "revoked" in capsys.readouterr().out


# --- an unmigrated database ---------------------------------------------------


def test_it_tells_you_to_migrate_first(capsys):
    from app.db import session as db_session

    db_session.dispose_engine()
    db_session.init_engine("sqlite://")  # no schema at all

    try:
        assert main(["--host", "buildbox"]) == 1
        assert "alembic upgrade head" in capsys.readouterr().err
    finally:
        db_session.dispose_engine()
