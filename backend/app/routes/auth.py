"""Registration, login, logout and current-user endpoints."""
from flask import Blueprint, current_app, g, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, verify_jwt_in_request
from flask import jsonify
from sqlalchemy.exc import IntegrityError

from ..extensions import db, limiter
from ..models.user import TokenBlocklist, User
from ..utils.auth import error, roles_required
from ..utils.security import burn_password_check
from ..utils.validation import check_password_policy, validate_new_user, validate_user_update

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


@auth_bp.patch("/me")
@roles_required()
def update_profile():
    """Users may change only their own name and phone here (never role, status or email)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error("validation_error", "Request body must be a JSON object.", 400)
    clean, errors = validate_user_update({k: body[k] for k in ("name", "phone") if k in body})
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)
    for field, value in clean.items():
        setattr(g.current_user, field, value)
    db.session.commit()
    return jsonify(user=g.current_user.to_dict())


@auth_bp.post("/change-password")
@roles_required()
@limiter.limit("5 per minute")
def change_password():
    body = request.get_json(silent=True)
    body = body if isinstance(body, dict) else {}
    current, new = body.get("current_password"), body.get("new_password")
    if not isinstance(current, str) or not current:
        return error("validation_error", "Enter your current password.", 400, {"current_password": "Required."})
    # 400 (not 401) so a mistyped current password does not look like an expired session to the client.
    if not g.current_user.check_password(current):
        return error("incorrect_password", "Your current password is incorrect.", 400, {"current_password": "Incorrect password."})
    problem = check_password_policy(new)
    if problem:
        return error("validation_error", problem, 400, {"new_password": problem})
    if new == current:
        return error("validation_error", "Choose a password different from the current one.", 400,
                     {"new_password": "Must differ from the current password."})
    g.current_user.set_password(new)
    db.session.commit()
    current_app.logger.info("Password changed for user id=%s", g.current_user.id)
    return jsonify(message="Password updated.")
