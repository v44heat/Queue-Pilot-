"""Authentication/authorization helpers. Roles are always read from the database,
never trusted from the token, so role and status changes take effect immediately."""
from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from ..extensions import db, jwt
from ..models.user import TokenBlocklist, User


def error(code: str, message: str, status: int, details: dict | None = None):
    body = {"error": code, "message": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def roles_required(*roles: str):
    """Require a valid JWT, an ACTIVE account, and (if given) one of `roles`."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            try:
                user = db.session.get(User, int(get_jwt_identity()))
            except (TypeError, ValueError):
                user = None
            if user is None:
                return error("unauthorized", "Authentication required.", 401)
            if not user.is_active:
                return error("account_disabled", "This account has been deactivated.", 403)
            if roles and user.role not in roles:
                return error("forbidden", "You do not have permission to perform this action.", 403)
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def register_jwt_handlers() -> None:
    @jwt.token_in_blocklist_loader
    def _is_revoked(_header, payload):
        return db.session.query(TokenBlocklist.id).filter_by(jti=payload["jti"]).first() is not None

    @jwt.unauthorized_loader
    def _missing(_reason):
        return error("unauthorized", "Authentication required.", 401)

    @jwt.invalid_token_loader
    def _invalid(_reason):
        return error("invalid_token", "Invalid authentication token.", 401)

    @jwt.expired_token_loader
    def _expired(_header, _payload):
        return error("token_expired", "Your session has expired. Please log in again.", 401)

    @jwt.revoked_token_loader
    def _revoked(_header, _payload):
        return error("token_revoked", "You have been logged out. Please log in again.", 401)
