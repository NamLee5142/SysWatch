"""Password hashing and the policy applied when a password is set.

Nothing in this module logs. It is the only place a plaintext password exists
in the process, and a stray logger here would put every account's password into
a file that outlives it — so there is deliberately no logger to reach for.
"""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id at RFC 9106's first recommended option, pinned rather than left to
# the library's defaults: the work factor is a security decision, and "whatever
# argon2-cffi defaults to after the next upgrade" is not one. Each stored hash
# encodes the parameters it was made with, so raising these later does not
# invalidate existing passwords.
TIME_COST = 3
MEMORY_COST_KIB = 65536  # 64 MiB
PARALLELISM = 4

MIN_PASSWORD_LENGTH = 12

_hasher = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST_KIB,
    parallelism=PARALLELISM,
)

# Verified against when the username does not exist, so a login for an unknown
# user costs the same as one for a known user with the wrong password. Without
# it, "no such user" returns in microseconds and "wrong password" in ~40ms,
# which is a username oracle regardless of how carefully the response body is
# worded. Generated with the hasher above so the parameters cannot drift apart.
DUMMY_HASH = _hasher.hash("dummy password, only ever used to burn time")


class WeakPassword(ValueError):
    """A password that fails the policy. The message is safe to show a user."""


def check_password_policy(password: str) -> None:
    """Raise WeakPassword unless the password is acceptable to store.

    Two rules, on purpose: long enough to be worth hashing, and not a single
    run of one kind of character. Composition rules beyond that push people
    towards `Password1!` and buy very little.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    classes = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    if classes < 2:
        raise WeakPassword(
            "Password must mix at least two of: lower case, upper case, digits, symbols"
        )


def hash_password(password: str) -> str:
    """Hash a password for storage, enforcing the policy on the way.

    The policy check lives here rather than only at the call site so there is no
    code path that can store a password weaker than the policy allows.
    """
    check_password_policy(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Whether the password matches the hash. Never raises.

    A wrong password, a corrupt stored hash and a hash from an unknown scheme
    are all just a failed login — none of them should become a 500 that tells
    the caller something went wrong on the server rather than with their
    credentials.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
