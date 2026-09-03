import statistics
import time

import pytest

from app.auth.password import (
    DUMMY_HASH,
    MIN_PASSWORD_LENGTH,
    WeakPassword,
    check_password_policy,
    hash_password,
    verify_password,
)

GOOD_PASSWORD = "correct horse Battery staple"


def test_the_right_password_verifies():
    assert verify_password(GOOD_PASSWORD, hash_password(GOOD_PASSWORD)) is True


def test_the_wrong_password_does_not():
    assert verify_password("not the password 1", hash_password(GOOD_PASSWORD)) is False


def test_the_stored_value_is_not_the_password():
    stored = hash_password(GOOD_PASSWORD)

    assert stored != GOOD_PASSWORD
    assert GOOD_PASSWORD not in stored
    # Every part of the password, in case some prefix leaked through.
    for word in GOOD_PASSWORD.split():
        assert word not in stored


def test_the_hash_is_argon2id():
    assert hash_password(GOOD_PASSWORD).startswith("$argon2id$")


def test_the_same_password_hashes_differently_each_time():
    first = hash_password(GOOD_PASSWORD)
    second = hash_password(GOOD_PASSWORD)

    # Distinct salts: two accounts sharing a password must not share a hash, or
    # the table itself tells you which users to attack together.
    assert first != second
    assert verify_password(GOOD_PASSWORD, first)
    assert verify_password(GOOD_PASSWORD, second)


def test_a_corrupt_hash_is_a_failed_login_not_an_exception():
    assert verify_password(GOOD_PASSWORD, "not-a-hash") is False
    assert verify_password(GOOD_PASSWORD, "") is False


def test_verifying_against_the_dummy_hash_fails():
    assert verify_password(GOOD_PASSWORD, DUMMY_HASH) is False


def test_the_dummy_hash_costs_what_a_real_verify_costs():
    def median_ms(password_hash):
        timings = []
        for _ in range(5):
            start = time.perf_counter()
            verify_password("some candidate password", password_hash)
            timings.append(time.perf_counter() - start)
        return statistics.median(timings)

    real = median_ms(hash_password(GOOD_PASSWORD))
    dummy = median_ms(DUMMY_HASH)

    # The point is that an unknown username does not return in microseconds
    # while a known one takes ~40ms. A wide band, because this is wall-clock on
    # a shared machine — it is guarding against an order-of-magnitude gap, not
    # measuring parity.
    assert dummy > real * 0.5


# --- policy ---------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        "Sh0rt!",
        "a" * (MIN_PASSWORD_LENGTH - 1),
    ],
)
def test_a_short_password_is_rejected(password):
    with pytest.raises(WeakPassword, match="at least"):
        check_password_policy(password)


@pytest.mark.parametrize(
    "password",
    [
        "aaaaaaaaaaaaaaa",
        "AAAAAAAAAAAAAAA",
        "123456789012345",
        "!!!!!!!!!!!!!!!",
    ],
)
def test_a_single_character_class_is_rejected(password):
    with pytest.raises(WeakPassword, match="at least two of"):
        check_password_policy(password)


@pytest.mark.parametrize(
    "password",
    [
        "correct horse Battery staple",
        "lowercaseand1digit",
        "passphrase with spaces!",
        "MiXeDcAsElOnGeNoUgH",
    ],
)
def test_an_acceptable_password_passes(password):
    check_password_policy(password)


def test_hashing_enforces_the_policy():
    # No path may store a password the policy rejects, not even one that skips
    # the explicit check.
    with pytest.raises(WeakPassword):
        hash_password("short")
