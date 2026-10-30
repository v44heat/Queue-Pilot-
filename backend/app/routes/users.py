"""Admin user management."""
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.user import ROLES, STATUSES, User
from ..utils.auth import error, roles_required
from ..utils.validation import validate_new_user, validate_user_update

users_bp = Blueprint("users", __name__)


@users_bp.get("")
@roles_required("ADMIN")
def list_users():
    q = User.query
    search = (request.args.get("search") or "").strip()
    if search:
        like = f"%{search.lower()}%"
        q = q.filter(or_(db.func.lower(User.name).like(like), db.func.lower(User.email).like(like)))
    role = (request.args.get("role") or "").upper()
    if role in ROLES:
        q = q.filter(User.role == role)
    status = (request.args.get("status") or "").upper()
    if status in STATUSES:
        q = q.filter(User.status == status)

    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 10)), 1), 100)
    except ValueError:
        return error("validation_error", "page and per_page must be integers.", 400)

    total = q.count()
    items = q.order_by(User.created_at.desc(), User.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        users=[u.to_dict() for u in items],
        page=page,
        per_page=per_page,
        total=total,
        pages=(total + per_page - 1) // per_page,
    )


@users_bp.get("/<int:user_id>")
@roles_required("ADMIN")
def get_user(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        return error("not_found", "User not found.", 404)
    return jsonify(user=user.to_dict())


@users_bp.post("")
@roles_required("ADMIN")
def create_user():
    clean, errors = validate_new_user(request.get_json(silent=True), allow_role=True)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)
    if User.query.filter_by(email=clean["email"]).first():
        return error("email_taken", "An account with this email already exists.", 409, {"email": "Email already registered."})

    user = User(name=clean["name"], email=clean["email"], phone=clean["phone"], role=clean["role"])
    user.set_password(clean["password"])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("email_taken", "An account with this email already exists.", 409)
    current_app.logger.info("Admin id=%s created user id=%s role=%s", g.current_user.id, user.id, user.role)
    return jsonify(user=user.to_dict()), 201


@users_bp.patch("/<int:user_id>")
@roles_required("ADMIN")
def update_user(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        return error("not_found", "User not found.", 404)

    clean, errors = validate_user_update(request.get_json(silent=True))
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)

    # An admin may not change their own role or status. This also guarantees the
    # system can never be left without an active admin through this endpoint,
    # because the acting admin is itself an active admin.
    if user.id == g.current_user.id and ({"role", "status"} & clean.keys()):
        if clean.get("role", user.role) != user.role or clean.get("status", user.status) != user.status:
            return error("forbidden", "You cannot change your own role or status.", 403)

    for field, value in clean.items():
        setattr(user, field, value)
    db.session.commit()
    current_app.logger.info("Admin id=%s updated user id=%s fields=%s", g.current_user.id, user.id, sorted(clean))
    return jsonify(user=user.to_dict())
