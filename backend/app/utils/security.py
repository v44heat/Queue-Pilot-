"""Password hashing helpers (Werkzeug scrypt, salted)."""
from werkzeug.security import check_password_hash, generate_password_hash

# Used to equalise timing when a login email does not exist.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def burn_password_check(password: str) -> None:
    check_password_hash(_DUMMY_HASH, password)
