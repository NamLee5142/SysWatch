from fastapi import APIRouter, HTTPException, Request, Response

from app.auth.service import AuthService
from app.models.auth import Credentials, CurrentUser
from config import get_settings

router = APIRouter()

# Named rather than a bare "session": cookies are scoped by host, not by port,
# so anything else served from localhost during development would collide with
# a generic name.
SESSION_COOKIE = "syswatch_session"

# One message for every way a login can fail. The service already spends the
# same time on an unknown username as on a wrong password; saying "no such user"
# here would hand back through the body what that was careful not to leak
# through the clock.
INVALID_CREDENTIALS = "Invalid username or password"


def create_auth_service() -> AuthService:
    return AuthService()


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.post(
    "/auth/login",
    response_model=CurrentUser,
    summary="Exchange credentials for a session cookie",
    responses={401: {"description": "Invalid username or password"}},
)
def login(credentials: Credentials, response: Response):
    service = create_auth_service()

    user = service.authenticate(credentials.username, credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    _set_session_cookie(response, service.create_session(user))

    # The role travels back with the login so the dashboard can render the right
    # controls without a second round trip. CurrentUser has no field a password
    # hash could land in.
    return CurrentUser.from_record(user)


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.post(
    "/auth/logout",
    status_code=204,
    summary="End the current session",
)
def logout(request: Request):
    # Idempotent: logging out without a session, or with one the server has
    # already forgotten, is a success. There is nothing useful for a caller to
    # do differently, and reporting it would confirm whether a token was live.
    create_auth_service().revoke(request.cookies.get(SESSION_COOKIE))

    # Built here rather than injected, because returning a Response replaces
    # anything set on an injected one — the cleared cookie has to go on this.
    response = Response(status_code=204)
    _clear_session_cookie(response)
    return response


# sync def so FastAPI runs the blocking database work in a threadpool
# instead of stalling the event loop
@router.get(
    "/auth/me",
    response_model=CurrentUser,
    summary="Who the caller is",
    responses={401: {"description": "Not authenticated"}},
)
def me(request: Request):
    current = create_auth_service().resolve_session(request.cookies.get(SESSION_COOKIE))

    if current is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return current


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        # The browser holds this; page JavaScript must not be able to read it.
        httponly=True,
        # HTTPS only, except in development where the dashboard is served over
        # plain HTTP through the Vite proxy.
        secure=not settings.dev_mode,
        # Lax rather than Strict: the cookie still travels on a top-level
        # navigation back into the dashboard, which Strict would break, while
        # cross-site form posts — the CSRF shape that matters for a JSON API —
        # still do not carry it.
        samesite="lax",
        path="/",
        # Expire the cookie alongside the session it names, so a browser is not
        # holding a credential the server has already stopped honouring.
        max_age=settings.session_ttl_seconds,
        # No domain attribute on purpose: the cookie stays scoped to the host
        # the browser actually talked to. Setting one would break the
        # development proxy, which rewrites the origin.
    )


def _clear_session_cookie(response: Response) -> None:
    settings = get_settings()

    # Every attribute that identifies the cookie has to match the one that set
    # it, or the browser deletes nothing and keeps the original.
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=not settings.dev_mode,
        samesite="lax",
    )
