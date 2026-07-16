import pytest

from app.security.passwords import BCRYPT_MAX_PASSWORD_BYTES, hash_password


def test_hash_password_rejects_values_over_bcrypt_limit():
    password = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

    with pytest.raises(ValueError, match="72-byte limit"):
        hash_password(password)


def test_demo_password_example_is_bcrypt_compatible():
    password = "change-this-demo-password"

    assert len(password.encode("utf-8")) <= BCRYPT_MAX_PASSWORD_BYTES
    assert hash_password(password).startswith("$2b$")
