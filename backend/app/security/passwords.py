from passlib.context import CryptContext

BCRYPT_MAX_PASSWORD_BYTES = 72

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def validate_bcrypt_password_size(password: str) -> None:
    password_size = len(password.encode("utf-8"))
    if password_size > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            "Password exceeds bcrypt's 72-byte limit. "
            f"Received {password_size} bytes; use {BCRYPT_MAX_PASSWORD_BYTES} bytes or fewer."
        )


def hash_password(password: str) -> str:
    validate_bcrypt_password_size(password)
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)
