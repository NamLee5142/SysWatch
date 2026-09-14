"""Credentials an agent holds, and how they are stored.

Nothing in this module logs. It is a place a plaintext token exists in the
process, and a stray logger here would put every agent's credential into a file
that outlives it - so there is deliberately no logger to reach for, the same
rule as password.py, session.py and alerts/smtp.py.

**Not Argon2, deliberately**, even though this is a credential and passwords in
this project are Argon2id. The two are different problems:

- A password is short, human-chosen and low-entropy, so the stored form has to
  be expensive to attack offline. It is verified once, at login, and 40ms is a
  price paid rarely.
- An agent token is 256 bits from `secrets`, so there is nothing to guess: a
  keyed hash is already unforgeable. It is verified on *every push* - once per
  agent per poll interval, forever - and an unauthenticated caller posting
  garbage to the ingestion endpoint would otherwise force 64 MiB and 40ms of
  Argon2 work per request. That is a denial-of-service amplifier reachable
  before authentication, which is the worst place to put one.

So this follows session.py: HMAC-SHA256 under the deployment secret. The key
buys the same two things it buys there - rotating SYSWATCH_SESSION_SECRET
invalidates every agent at once, which is the lever to pull after a database
leak, and a table lifted from one deployment is inert against another.
"""
import hmac
import secrets
from hashlib import sha256

# 256 bits, matching session.py. token_urlsafe encodes base64url, so the value
# survives an Authorization header, a config file and a copy-paste unharmed.
TOKEN_BYTES = 32

# Domain separation. Session tokens are HMACed under the same secret, so
# without a distinct prefix the same random string would hash identically in
# both tables - and a value that authenticated as one could be presented as the
# other. The version is here so a future change of scheme is a new label rather
# than a silent reinterpretation of stored hashes.
_DOMAIN = b"syswatch-agent-token:v1:"


def new_token() -> str:
    """A fresh token. Shown to an operator once and never recoverable after."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str, secret: str) -> str:
    """The value stored for a token: HMAC-SHA256 under the deployment secret."""
    return hmac.new(
        secret.encode("utf-8"), _DOMAIN + token.encode("utf-8"), sha256
    ).hexdigest()


def tokens_match(presented: str, stored: str) -> bool:
    """Constant-time comparison of two hashes.

    The lookup itself is by unique index and an attacker cannot produce a hash
    without the secret, so this is defence in depth rather than the load-bearing
    check. It costs nothing and removes a whole category of argument.
    """
    return hmac.compare_digest(presented, stored)
