"""Turning an agent's bearer token into the host it speaks for.

Nothing here logs a raw token or a token hash. Every way resolution can fail
arrives as the same None, and it is the dependency's job to turn all of them
into one 401 - the distinctions drawn here (no such token, revoked) must not
reach a caller, because a caller who can tell "revoked" from "never existed"
can enumerate which credentials a deployment has issued.
"""
from app.auth.agent_token import hash_token
from app.models.auth import CurrentAgent
from app.repositories import AgentTokenStore
from config import get_settings


class AgentAuthService:
    def __init__(self, token_store=None, secret=None):
        self._tokens = token_store or AgentTokenStore()
        self._secret = get_settings().session_secret if secret is None else secret

    def resolve(self, raw_token):
        """The host a bearer token speaks for, or None.

        No timing defence, unlike authenticate(). There is nothing to enumerate:
        the lookup key is an HMAC under a secret the caller does not have, so a
        token cannot be probed into existence and a miss reveals only that this
        particular unguessable string is not one of ours.
        """
        if not raw_token:
            return None

        # A token issued under a different secret - or none - cannot resolve,
        # which is what makes rotating SYSWATCH_SESSION_SECRET revoke every
        # agent at once. Refusing here rather than hashing under "" keeps that
        # from silently becoming "every agent matches the empty-key namespace".
        if not self._secret:
            return None

        record = self._tokens.by_token_hash(hash_token(raw_token, self._secret))
        if record is None:
            return None

        if not record.enabled:
            # Revocation takes effect on the next request, not on the next
            # restart. The row stays so an audit can still see it existed.
            return None

        self._tokens.touch(record.id)
        return CurrentAgent.from_record(record)
