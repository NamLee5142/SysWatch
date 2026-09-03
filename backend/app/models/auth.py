from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

# Two roles, deliberately. The only authorization split this sprint needs is
# "may change alert rules"; a permission system holding one permission would be
# scaffolding rather than design. See docs/sprint-9.md.
Role = Literal["admin", "viewer"]

# Trimmed and non-empty: a username of "" or "   " is a UI slip, and it should
# fail at the boundary rather than become a row nobody can ever log in as.
Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]

# Not a policy — that lives in the password service and applies when a password
# is *set*. Enforcing a minimum here would tell an attacker the policy for free,
# and reject accounts whose password predates it. The cap is a resource guard:
# an unbounded body should not reach the hasher.
Password = Annotated[str, Field(min_length=1, max_length=1024)]


class Credentials(BaseModel):
    """Body for POST /auth/login.

    Nothing that accepts this model may put it in a response or a log line: the
    password is only ever passed to verification and then dropped.
    """

    username: Username
    password: Password


class CurrentUser(BaseModel):
    """Who the caller is — the GET /auth/me response, and what the
    authentication dependencies yield.

    Deliberately only these two fields. There is no password_hash attribute to
    forget to exclude, so no serializer, log line or debug dump can leak one.
    If something later needs the user's id, give it a separate internal type
    rather than widening this one, or /auth/me widens with it.
    """

    username: str
    role: Role

    @classmethod
    def from_record(cls, record) -> "CurrentUser":
        """Build from a UserRecord.

        Taken structurally rather than by import, so the API models stay
        independent of the database layer — the rule Snapshot and Alert follow.
        """
        return cls(username=record.username, role=record.role)
