"""Registration, login, logout and current-user endpoints."""
from flask import Blueprint, current_app, g, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request
from flask import jsonify
from sqlalchemy.exc import IntegrityError

from ..extensions import db, limiter
from ..models.user import TokenBlocklist, User
from ..utils.auth import error, roles_required
from ..utils.security import burn_password_check
from ..utils.validation import validate_new_user

auth_bp = Blueprint("auth", __name__)


def _token_for(user: User) -> str:
    return create_access_token(identity=str(user.id))


@auth_bp.post("/register")
@limiter.limit("5 per minute")
def register():
    clean, errors = validate_new_user(request.get_json(silent=True), allow_role=False)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)

    if User.query.filter_by(email=clean["email"]).first():
        return error("email_taken", "An account with this email already exists.", 409, {"email": "Email already registered."})

    user = User(name=clean["name"], email=clean["email"], phone=clean["phone"], role="CUSTOMER")
    user.set_password(clean["password"])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("email_taken", "An account with this email already exists.", 409, {"email": "Email already registered."})

    current_app.logger.info("New customer registered id=%s", user.id)
    return jsonify(user=user.to_dict(), access_token=_token_for(user)), 201


@auth_bp.post("/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email").strip().lower() if isinstance(data.get("email"), str) else ""
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    if not email or not password:
        return error("validation_error", "Email and password are required.", 400)

    user = User.query.filter_by(email=email).first()
    if user is None:
        burn_password_check(password)  # keep timing similar for unknown emails
        return error("invalid_credentials", "Invalid email or password.", 401)
    if not user.check_password(password):
        current_app.logger.warning("Failed login for user id=%s", user.id)
        return error("invalid_credentials", "Invalid email or password.", 401)
    if not user.is_active:
        return error("account_disabled", "This account has been deactivated.", 403)

    return jsonify(user=user.to_dict(), access_token=_token_for(user))


@auth_bp.post("/logout")
def logout():
    verify_jwt_in_request()
    payload = get_jwt()
    db.session.add(TokenBlocklist(jti=payload["jti"], user_id=int(get_jwt_identity())))
    db.session.commit()
    return jsonify(message="Logged out.")


@auth_bp.get("/me")
@roles_required()
def me():
    return jsonify(user=g.current_user.to_dict())
