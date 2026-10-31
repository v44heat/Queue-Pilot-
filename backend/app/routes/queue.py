from flask import Blueprint, g, jsonify, request

from ..extensions import db, limiter
from ..models.queue import ACTIVE_STATUSES, TICKET_STATUSES, QueueTicket
from ..services import queue_service
from ..utils.auth import error, roles_required

queue_bp = Blueprint("queue", __name__)


@queue_bp.post("/join")
@roles_required("CUSTOMER")
@limiter.limit("30 per minute")
def join():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error("validation_error", "Request body must be a JSON object.", 400)
    ticket = queue_service.join_queue(g.current_user, body.get("service_id"))
    return jsonify(ticket=queue_service.serialize_ticket(ticket)), 201


@queue_bp.get("/my-active")
@roles_required("CUSTOMER")
def my_active():
    tickets = (
        QueueTicket.query.filter(QueueTicket.user_id == g.current_user.id, QueueTicket.status.in_(ACTIVE_STATUSES))
        .order_by(QueueTicket.created_at.desc(), QueueTicket.id.desc())
        .all()
    )
    return jsonify(tickets=[queue_service.serialize_ticket(t) for t in tickets])


@queue_bp.get("/history")
@roles_required("CUSTOMER")
def history():
    q = QueueTicket.query.filter(QueueTicket.user_id == g.current_user.id)
    status = (request.args.get("status") or "").upper()
    if status:
        if status not in TICKET_STATUSES:
            return error("validation_error", f"status must be one of {', '.join(TICKET_STATUSES)}.", 400)
        q = q.filter(QueueTicket.status == status)
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 10)), 1), 100)
    except ValueError:
        return error("validation_error", "page and per_page must be integers.", 400)

    total = q.count()
    items = q.order_by(QueueTicket.created_at.desc(), QueueTicket.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        tickets=[queue_service.serialize_ticket(t) for t in items],
        page=page, per_page=per_page, total=total, pages=(total + per_page - 1) // per_page,
    )


@queue_bp.get("/tickets/<int:ticket_id>")
@roles_required()
def get_ticket(ticket_id: int):
    ticket = db.session.get(QueueTicket, ticket_id)
    user = g.current_user
    # Customers may only see their own tickets; a foreign ticket is reported as not found.
    if ticket is None or (user.role == "CUSTOMER" and ticket.user_id != user.id):
        return error("ticket_not_found", "Ticket not found.", 404)
    return jsonify(ticket=queue_service.serialize_ticket(ticket))


@queue_bp.post("/tickets/<int:ticket_id>/cancel")
@roles_required("CUSTOMER")
def cancel(ticket_id: int):
    ticket = queue_service.cancel_ticket(g.current_user, ticket_id)
    return jsonify(ticket=queue_service.serialize_ticket(ticket))
