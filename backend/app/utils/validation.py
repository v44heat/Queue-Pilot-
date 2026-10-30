"""Input validation. Each validator returns (clean_data, errors)."""
import re

from ..models.user import ROLES, STATUSES

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-]{6,18}[0-9]$")


def _str(data: dict, key: str) -> str | None:
    v = data.get(key)
    return v.strip() if isinstance(v, str) else None


def check_password_policy(password) -> str | None:
    if not isinstance(password, str):
        return "Password is required."
    if len(password) < 8 or len(password) > 128:
        return "Password must be 8-128 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "Password must contain at least one letter and one number."
    return None


def validate_new_user(data, allow_role: bool = False):
    """Validate registration / admin-create payloads.

    Public registration passes allow_role=False: any 'role' value is ignored
    and the account is always CUSTOMER.
    """
    errors: dict[str, str] = {}
    if not isinstance(data, dict):
        return {}, {"_": "Request body must be a JSON object."}

    name = _str(data, "name")
    if not name or not (2 <= len(name) <= 120):
        errors["name"] = "Name is required (2-120 characters)."

    email = _str(data, "email")
    email = email.lower() if email else None
    if not email or len(email) > 255 or not _EMAIL_RE.match(email):
        errors["email"] = "A valid email address is required."

    pw_error = check_password_policy(data.get("password"))
    if pw_error:
        errors["password"] = pw_error

    phone = _str(data, "phone") or None
    if phone and not _PHONE_RE.match(phone):
        errors["phone"] = "Enter a valid phone number."

    role = "CUSTOMER"
    if allow_role:
        role = (_str(data, "role") or "CUSTOMER").upper()
        if role not in ROLES:
            errors["role"] = f"Role must be one of {', '.join(ROLES)}."

    clean = {"name": name, "email": email, "password": data.get("password"), "phone": phone, "role": role}
    return clean, errors


def validate_user_update(data):
    errors: dict[str, str] = {}
    clean: dict = {}
    if not isinstance(data, dict) or not data:
        return {}, {"_": "Provide at least one field to update."}

    if "name" in data:
        name = _str(data, "name")
        if not name or not (2 <= len(name) <= 120):
            errors["name"] = "Name must be 2-120 characters."
        else:
            clean["name"] = name
    if "phone" in data:
        phone = _str(data, "phone") or None
        if phone and not _PHONE_RE.match(phone):
            errors["phone"] = "Enter a valid phone number."
        else:
            clean["phone"] = phone
    if "role" in data:
        role = (_str(data, "role") or "").upper()
        if role not in ROLES:
            errors["role"] = f"Role must be one of {', '.join(ROLES)}."
        else:
            clean["role"] = role
    if "status" in data:
        status = (_str(data, "status") or "").upper()
        if status not in STATUSES:
            errors["status"] = f"Status must be one of {', '.join(STATUSES)}."
        else:
            clean["status"] = status
    return clean, errors
