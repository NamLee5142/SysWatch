"""Response hardening and the startup checks that refuse an unsafe configuration."""
from starlette.datastructures import MutableHeaders

# The documentation UI is HTML that loads its own scripts and styles; the API's
# content security policy would blank it. The other headers still apply to it —
# only the CSP is skipped, and only here.
DOCUMENTATION_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})

SECURITY_HEADERS = {
    # This API answers JSON. Content sniffing turning a response into something
    # a browser will execute is a whole class of bug that simply stops existing.
    "X-Content-Type-Options": "nosniff",
    # Nothing here should ever be framed. With the session in a SameSite=Lax
    # cookie this closes the remaining clickjacking shape.
    "X-Frame-Options": "DENY",
    # URLs here carry host names and alert ids. No referrer leaves the origin.
    "Referrer-Policy": "no-referrer",
}

# 'none' because a JSON API needs nothing: no scripts, no styles, no images, no
# frames. Anything that can load a resource is a capability this surface has no
# use for.
API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"

# The dashboard is served from this process now, and 'none' would forbid it
# loading its own bundle — the page renders blank with a console full of CSP
# violations. Everything it needs comes from this origin, so 'self' is the whole
# policy, minus one concession: 'unsafe-inline' for styles, because the chart
# library sets them on elements it renders.
DASHBOARD_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)

MIN_SESSION_SECRET_LENGTH = 32


class InsecureConfiguration(RuntimeError):
    """A configuration the process refuses to start with."""


class SecurityHeadersMiddleware:
    """Adds the headers above to every response.

    Pure ASGI rather than BaseHTTPMiddleware: this only needs to touch the
    response start message, and wrapping every response in a streaming one to
    set four headers would be a lot of machinery for it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if path not in DOCUMENTATION_PATHS:
                    # Chosen by what is being sent rather than by path: the
                    # same process answers JSON and serves an HTML application,
                    # and they need opposite policies.
                    content_type = headers.get("content-type", "")
                    policy = (
                        DASHBOARD_CONTENT_SECURITY_POLICY
                        if content_type.startswith("text/html")
                        else API_CONTENT_SECURITY_POLICY
                    )
                    headers.setdefault("Content-Security-Policy", policy)

            await send(message)

        await self.app(scope, receive, send_with_headers)


def verify_security_configuration(settings):
    """Refuse to start rather than run with a session secret nobody set.

    A default secret shipped in the source is a published key: every
    installation would share it, and anyone could mint a session for any of
    them. There is no safe fallback, so a missing value is fatal — except in
    dev_mode, which is the explicit "I know, this is a laptop" switch.

    Returns a list of warnings worth logging.
    """
    warnings = []

    if not settings.auth_enabled:
        if not settings.dev_mode:
            # A warning was not enough. Anyone reading a startup log sees a
            # hundred lines of normal, and this one says the whole API is open
            # to anyone who can reach the port. Refusing to start is the only
            # version of this message that cannot be scrolled past.
            raise InsecureConfiguration(
                "SYSWATCH_AUTH_ENABLED is false, which opens every endpoint and "
                "treats every caller as an administrator. Set SYSWATCH_DEV_MODE=true "
                "if this is a development machine; otherwise remove the setting."
            )

        warnings.append(
            "SYSWATCH_AUTH_ENABLED is false: every endpoint is open and every "
            "caller is treated as an administrator."
        )
        return warnings

    for origin in settings.cors_origins:
        if not settings.dev_mode and not origin.startswith("https://"):
            # Not pedantry: the session cookie carries Secure, so a browser on
            # an http:// origin never sends it back. A dashboard configured
            # this way logs in and stays logged out, and the symptom points
            # nowhere near the cause.
            raise InsecureConfiguration(
                f"SYSWATCH_CORS_ORIGINS contains {origin!r}. The session cookie is "
                "Secure, so a browser on an http:// origin will never send it — "
                "use https://, or set SYSWATCH_DEV_MODE=true for local work."
            )

    if settings.dev_mode:
        warnings.append(
            "SYSWATCH_DEV_MODE is true: the session cookie is sent without the "
            "Secure flag. Never run this facing a network."
        )
        if not settings.session_secret:
            warnings.append(
                "SYSWATCH_SESSION_SECRET is unset; sessions will not survive a "
                "restart and are not protected by a key."
            )
        return warnings

    if not settings.session_secret:
        raise InsecureConfiguration(
            "SYSWATCH_SESSION_SECRET must be set when authentication is enabled. "
            "Generate one with: python -c \"import secrets; "
            'print(secrets.token_urlsafe(48))"'
        )

    if len(settings.session_secret) < MIN_SESSION_SECRET_LENGTH:
        raise InsecureConfiguration(
            f"SYSWATCH_SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} "
            "characters. A short key is guessable, and guessing it mints sessions."
        )

    return warnings
