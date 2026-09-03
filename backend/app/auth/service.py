"""Authentication and session lifecycle.

Nothing here logs a password, a raw token or a token hash. Failures are
reported to the caller as None, and it is the API layer's job to turn every one
of them into the same generic 401 — the distinctions this module draws
internally (no such user, wrong password, disabled, expired) must not reach a
client.
"""
from datetime import datetime, timedelta, timezone

from app.auth.password import DUMMY_HASH, verify_password
from app.auth.session import hash_token, new_token
from app.models.auth import CurrentUser
from app.repositories.auth_store import SessionStore, UserStore
from config import get_settings


class AuthService:
    def __init__(self, user_store=None, session_store=None, secret=None, ttl_seconds=None):
        settings = get_settings()
        self._users = user_store or UserStore()
        self._sessions = session_store or SessionStore()
        self._secret = settings.session_secret if secret is None else secret
        self._ttl = timedelta(
            seconds=settings.session_ttl_seconds if ttl_seconds is None else ttl_seconds
        )

    def authenticate(self, username, password):
        """The account these credentials belong to, or None.

        One None for every kind of failure, and every path costs one Argon2
        verify: an unknown username burns the same time against DUMMY_HASH that
        a real one would, and a disabled account is only rejected *after* its
        password is checked. Returning early in either case would answer "does
        this account exist?" through the response time regardless of how
        carefully the body is worded.
        """
        user = self._users.by_username(username)

        if user is None:
            verify_password(password, DUMMY_HASH)
            return None

        if not verify_password(password, user.password_hash):
            return None

        if not user.enabled:
            return None

        return user

    def create_session(self, user):
        """Open a session and return its raw token — the only time it exists.

        The caller puts this in a Set-Cookie header and forgets it. What is
        stored is the keyed hash, which cannot be turned back into a cookie.
        """
        token = new_token()
        self._sessions.create(
            token_hash=hash_token(token, self._secret),
            user_id=user.id,
            expires_at=_utcnow() + self._ttl,
        )
        return token

    def resolve_session(self, raw_token):
        """Who a cookie belongs to, or None if it does not identify anyone.

        Checks, in order: the token resolves to a row, the row has not expired,
        the account still exists, and the account is still enabled — so
        disabling or deleting a user ends the sessions they already hold rather
        than waiting for those to expire.
        """
        if not raw_token:
            return None

        record = self._sessions.by_token_hash(hash_token(raw_token, self._secret))
        if record is None:
            return None

        if record.expires_at <= _utcnow():
            # Left for prune_expired() rather than deleted here: expiry is
            # enforced on this read, so removing the row is housekeeping and
            # does not belong on a request path.
            return None

        user = self._users.get(record.user_id)
        if user is None or not user.enabled:
            return None

        self._sessions.touch(record.id)
        return CurrentUser.from_record(user)

    def revoke(self, raw_token):
        """End one session. Returns whether there was one to end."""
        if not raw_token:
            return False

        record = self._sessions.by_token_hash(hash_token(raw_token, self._secret))
        if record is None:
            return False

        return self._sessions.delete(record.id)

    def prune_expired(self):
        """Drop sessions past their expiry. Returns rows removed."""
        return self._sessions.prune_expired()


def _utcnow():
    return datetime.now(timezone.utc)
