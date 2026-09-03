import pytest

from app.auth.create_admin import build_parser, main
from app.auth.password import verify_password
from app.db import session as db_session
from app.repositories import UserStore

PASSWORD = "correct horse Battery staple"


def prompts(*answers):
    """A getpass stand-in that returns each answer in turn."""
    remaining = list(answers)
    return lambda _prompt: remaining.pop(0)


def run(argv, password=PASSWORD, confirm=None, username=None):
    return main(
        argv,
        prompt=prompts(password, password if confirm is None else confirm),
        ask=lambda _prompt: username,
    )


def test_it_creates_an_admin(database, capsys):
    assert run(["--username", "root"]) == 0

    user = UserStore().by_username("root")
    assert user.role == "admin"
    assert user.enabled is True
    assert "Created admin 'root'" in capsys.readouterr().out


def test_the_password_is_stored_hashed(database):
    run(["--username", "root"])

    user = UserStore().by_username("root")
    assert user.password_hash != PASSWORD
    assert PASSWORD not in user.password_hash
    assert verify_password(PASSWORD, user.password_hash)


def test_the_password_never_appears_as_an_argument():
    options = {action.option_strings[0] for action in build_parser()._actions if action.option_strings}

    # An argument would land in the shell's history file and in the process
    # list, outliving the terminal by a long way. The prompt is the only way in.
    assert "--password" not in options


def test_it_can_create_a_viewer(database):
    assert run(["--username", "viv", "--role", "viewer"]) == 0

    assert UserStore().by_username("viv").role == "viewer"


def test_it_prompts_for_a_username_when_not_given(database):
    assert run([], username="prompted") == 0

    assert UserStore().by_username("prompted") is not None


def test_an_empty_username_is_refused(database, capsys):
    assert run([], username="   ") == 1

    assert UserStore().count() == 0
    assert "must not be empty" in capsys.readouterr().err


def test_it_says_when_this_is_the_first_account(database, capsys):
    run(["--username", "root"])

    assert "This is the first account" in capsys.readouterr().out


def test_it_does_not_say_so_for_the_second(database, capsys):
    run(["--username", "root"])
    capsys.readouterr()

    run(["--username", "second"])

    assert "first account" not in capsys.readouterr().out


# --- refusals ---------------------------------------------------------------


def test_it_refuses_an_existing_username(database, capsys):
    run(["--username", "root"])
    original = UserStore().by_username("root").password_hash

    assert run(["--username", "root"], password="a different Password 1") == 1

    assert "already exists" in capsys.readouterr().err
    # Refused means unchanged, not "probably unchanged".
    assert UserStore().by_username("root").password_hash == original


def test_a_weak_password_creates_nothing(database, capsys):
    assert run(["--username", "root"], password="short") == 1

    assert UserStore().count() == 0
    assert "at least" in capsys.readouterr().err


def test_a_mismatched_confirmation_creates_nothing(database, capsys):
    assert run(["--username", "root"], confirm="something Else 12") == 1

    assert UserStore().count() == 0
    assert "did not match" in capsys.readouterr().err


# --- resetting --------------------------------------------------------------


def test_reset_password_replaces_the_hash(database):
    run(["--username", "root"])

    new_password = "an entirely New passphrase 9"
    assert run(["--username", "root", "--reset-password"], password=new_password) == 0

    user = UserStore().by_username("root")
    assert verify_password(new_password, user.password_hash)
    # The old one has to stop working, or a reset is only a suggestion.
    assert not verify_password(PASSWORD, user.password_hash)


def test_reset_password_needs_an_existing_user(database, capsys):
    assert run(["--username", "ghost", "--reset-password"]) == 1

    assert "No user named" in capsys.readouterr().err


def test_reset_password_still_enforces_the_policy(database):
    run(["--username", "root"])

    assert run(["--username", "root", "--reset-password"], password="weak") == 1

    # Still the original password, not a weak one.
    assert verify_password(PASSWORD, UserStore().by_username("root").password_hash)


# --- an unmigrated database -------------------------------------------------


def test_it_tells_you_to_migrate_first(capsys):
    # An engine with no schema at all, which is what running the command before
    # alembic looks like.
    db_session.dispose_engine()
    db_session.init_engine("sqlite://")

    try:
        assert run(["--username", "root"]) == 1
        assert "alembic upgrade head" in capsys.readouterr().err
    finally:
        db_session.dispose_engine()
