from flask import Blueprint, g, jsonify, request

from ..extensions import db
from ..models.notification import Notification
from ..utils.auth import error, roles_required

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.get("")
@roles_required()
def list_notifications():
    q = Notification.query.filter_by(user_id=g.current_user.id)
    if request.args.get("unread_only") == "true":
        q = q.filter_by(is_read=False)
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 50)
    except ValueError:
        return error("validation_error", "page and per_page must be integers.", 400)
    total = q.count()
    items = q.order_by(Notification.created_at.desc(), Notification.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        notifications=[n.to_dict() for n in items], page=page, per_page=per_page, total=total,
        pages=(total + per_page - 1) // per_page,
        unread=Notification.query.filter_by(user_id=g.current_user.id, is_read=False).count(),
    )


@notifications_bp.get("/unread-count")
@roles_required()
def unread_count():
    return jsonify(unread=Notification.query.filter_by(user_id=g.current_user.id, is_read=False).count())


@notifications_bp.post("/<int:notification_id>/read")
@roles_required()
def mark_read(notification_id: int):
    n = db.session.get(Notification, notification_id)
    if n is None or n.user_id != g.current_user.id:  # someone else's notification is "not found"
        return error("not_found", "Notification not found.", 404)
    n.is_read = True
    db.session.commit()
    return jsonify(notification=n.to_dict())


@notifications_bp.post("/read-all")
@roles_required()
def mark_all_read():
    changed = Notification.query.filter_by(user_id=g.current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify(updated=changed)
