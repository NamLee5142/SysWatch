"""The dependencies that turn a cookie into a caller, and a caller into a role.

These are the enforcement points. A route is protected because one of these
sits in front of it, not because the dashboard declines to render a button —
the dashboard hides admin controls from a viewer as a courtesy, and this is
what makes hiding them unnecessary.
"""
from fastapi import Depends, HTTPException, Request

from app.auth.agent_service import AgentAuthService
from app.auth.service import AuthService
from app.auth.session import SESSION_COOKIE
from app.models.auth import CurrentAgent, CurrentUser
from config import get_settings

# Yielded to every protected route when SYSWATCH_AUTH_ENABLED is false, which
# restores the anonymous API of Sprint 8 for local development. Named rather
# than blank so it is obvious in a log or a debugger that nothing authenticated.
ANONYMOUS_ADMIN = CurrentUser(username="anonymous", role="admin")


def create_auth_service() -> AuthService:
    return AuthService()


def create_agent_auth_service() -> AgentAuthService:
    return AgentAuthService()


def require_authenticated_user(request: Request) -> CurrentUser:
    """The caller, or 401.

    Every reason a session can fail to resolve — absent, forged, expired, the
    account disabled or deleted — arrives here as the same None and leaves as
    the same 401. Which one it was is not the caller's business.
    """
    if not get_settings().auth_enabled:
        return ANONYMOUS_ADMIN

    current = create_auth_service().resolve_session(request.cookies.get(SESSION_COOKIE))

    if current is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return current


def require_admin(
    current: CurrentUser = Depends(require_authenticated_user),
) -> CurrentUser:
    """The caller, if they are an admin. 403 if they are merely logged in.

    403 rather than 404: hiding the existence of a route the caller can already
    see in the API docs buys nothing, and a viewer who gets a 404 for a rule
    they can read through GET will file it as a bug.
    """
    if current.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")

    return current


def bearer_token(request: Request):
    """The token from an Authorization header, or None.

    Deliberately strict about the scheme. Accepting a bare token as well would
    mean a client that sends "Basic <base64>" gets its base64 tried as a token,
    and the one that sends the header twice gets whichever the framework kept.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None

    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None

    return value.strip() or None


def require_agent(request: Request) -> CurrentAgent:
    """The machine this request speaks for, or 401.

    **Not affected by SYSWATCH_AUTH_ENABLED**, unlike every dependency above.
    That switch turns authorization off for local work by treating the caller as
    an administrator, which works because the routes it guards only need to know
    whether the caller may act. This one needs to know *who is speaking*: a
    snapshot has to be filed under a host, and with no credential there is no
    answer. Falling back to the payload's hostName would put a forgeable
    identity on the write path, and would put it there only in the
    configuration nobody tests against.

    Every reason resolution can fail - no header, wrong scheme, unknown token,
    revoked token - arrives as the same None and leaves as the same 401. A
    caller able to tell "revoked" from "never existed" can enumerate which
    credentials a deployment has issued.
    """
    current = create_agent_auth_service().resolve(bearer_token(request))

    if current is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            # RFC 9110: a 401 says which scheme would work. Without it a client
            # cannot tell "your token is wrong" from "this endpoint wants a
            # cookie", and the agent has no browser to work it out for it.
            headers={"WWW-Authenticate": "Bearer"},
        )

    return current
