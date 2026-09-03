"""Session token primitives. No I/O, no database, no logging.

The raw token exists in exactly two places: the response that sets the cookie,
and the browser holding it. It is never written down. What the `sessions` table
stores is the keyed hash below, so a reader of the database learns which
sessions exist but cannot produce a cookie for any of them.
"""
import hmac
import secrets
from hashlib import sha256

# 256 bits of randomness. token_urlsafe encodes it base64url, so the value is
# cookie-safe without escaping.
TOKEN_BYTES = 32


def new_token() -> str:
    """A fresh session token. Cryptographically random, never reused."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str, secret: str) -> str:
    """The value stored for a token: HMAC-SHA256 under the deployment secret.

    A plain hash of a 256-bit random token would already be unforgeable, so the
    key buys two specific things rather than raw strength: rotating
    SYSWATCH_SESSION_SECRET invalidates every live session at once, which is the
    lever to pull after a database leak; and a table lifted from one deployment
    is inert against another.
    """
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), sha256).hexdigest()
