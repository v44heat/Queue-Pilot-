"""Administrator dashboard, live queue monitor and service management."""
import re

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.counter import Counter
from ..models.queue import ACTIVE_STATUSES, QueueTicket
from ..models.service import Service
from ..services import admin_service
from ..services.counter_service import capacity_by_service
from ..services.queue_service import waiting_counts
from ..utils.auth import error, roles_required

admin_bp = Blueprint("admin", __name__)

_PREFIX_RE = re.compile(r"^[A-Z0-9]{2,6}$")


@admin_bp.get("/dashboard")
@roles_required("ADMIN")
def dashboard():
    return jsonify(admin_service.dashboard())


@admin_bp.get("/queue")
@roles_required("ADMIN")
def queue_monitor():
    return jsonify(admin_service.queue_monitor(request.args))


# ---- services -------------------------------------------------------------------------------
def _service_dict(s: Service, stats: dict) -> dict:
    d = s.to_dict(waiting_count=stats["waiting"].get(s.id, 0))
    d.update({
        "active_tickets": stats["active"].get(s.id, 0), "total_tickets": stats["total"].get(s.id, 0),
        "counters": stats["counters"].get(s.id, 0), "open_counters": stats["capacity"].get(s.id, {}).get("open", 0),
    })
    return d


def _stats() -> dict:
    def grouped(query):
        return dict(query.group_by(QueueTicket.service_id).all())
    return {
        "waiting": waiting_counts(),
        "active": grouped(db.session.query(QueueTicket.service_id, func.count(QueueTicket.id)).filter(QueueTicket.status.in_(ACTIVE_STATUSES))),
        "total": grouped(db.session.query(QueueTicket.service_id, func.count(QueueTicket.id))),
        "counters": dict(db.session.query(Counter.service_id, func.count(Counter.id)).group_by(Counter.service_id).all()),
        "capacity": capacity_by_service(),
    }


def _validate_service(data, creating: bool):
    if not isinstance(data, dict) or (not creating and not data):
        return {}, {"_": "Provide the fields to set."}
    errors, clean = {}, {}
    if creating or "name" in data:
        name = data.get("name").strip() if isinstance(data.get("name"), str) else ""
        if not 2 <= len(name) <= 100:
            errors["name"] = "Name is required (2-100 characters)."
        else:
            clean["name"] = name
    if creating or "prefix" in data:
        prefix = data.get("prefix").strip().upper() if isinstance(data.get("prefix"), str) else ""
        if not _PREFIX_RE.match(prefix):
            errors["prefix"] = "Prefix must be 2-6 letters or digits (it starts every ticket number)."
        else:
            clean["prefix"] = prefix
    if "description" in data:
        desc = data["description"]
        if desc is not None and (not isinstance(desc, str) or len(desc) > 500):
            errors["description"] = "Description must be text of at most 500 characters."
        else:
            clean["description"] = (desc or "").strip() or None
    if "default_service_duration" in data or creating:
        dur = data.get("default_service_duration", 10)
        if isinstance(dur, bool) or not isinstance(dur, int) or not 1 <= dur <= 240:
            errors["default_service_duration"] = "Typical service time must be a whole number of minutes from 1 to 240."
        else:
            clean["default_service_duration"] = dur
    if "status" in data:
        status = data["status"].upper() if isinstance(data["status"], str) else ""
        if status not in ("ACTIVE", "INACTIVE"):
            errors["status"] = "Status must be ACTIVE or INACTIVE."
        else:
            clean["status"] = status
    return clean, errors


@admin_bp.get("/services")
@roles_required("ADMIN")
def list_services():
    stats = _stats()
    services = Service.query.order_by(Service.status, Service.name).all()
    return jsonify(services=[_service_dict(s, stats) for s in services])


@admin_bp.post("/services")
@roles_required("ADMIN")
def create_service():
    clean, errors = _validate_service(request.get_json(silent=True), creating=True)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)
    service = Service(**clean)
    db.session.add(service)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("duplicate", "A service with this name or prefix already exists.", 409,
                     {"name": "Name or prefix already in use.", "prefix": "Name or prefix already in use."})
    current_app.logger.info("Admin id=%s created service id=%s", g.current_user.id, service.id)
    return jsonify(service=_service_dict(service, _stats())), 201


@admin_bp.patch("/services/<int:service_id>")
@roles_required("ADMIN")
def update_service(service_id: int):
    service = db.session.get(Service, service_id)
    if service is None:
        return error("not_found", "Service not found.", 404)
    clean, errors = _validate_service(request.get_json(silent=True), creating=False)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)

    # Business rules apply to administrators too.
    if "prefix" in clean and clean["prefix"] != service.prefix and QueueTicket.query.filter_by(service_id=service.id).first():
        return error("prefix_locked", "The prefix cannot change once tickets exist for this service (it would break ticket history and model features).", 409)
    if clean.get("status") == "INACTIVE" and service.status == "ACTIVE":
        active = QueueTicket.query.filter(QueueTicket.service_id == service.id, QueueTicket.status.in_(ACTIVE_STATUSES)).count()
        if active:
            return error("service_in_use", f"{active} customer{'s are' if active != 1 else ' is'} still in this queue. "
                                           "Wait until they are served or cancelled before deactivating.", 409)
    for field, value in clean.items():
        setattr(service, field, value)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("duplicate", "A service with this name or prefix already exists.", 409,
                     {"name": "Name or prefix already in use.", "prefix": "Name or prefix already in use."})
    current_app.logger.info("Admin id=%s updated service id=%s fields=%s", g.current_user.id, service.id, sorted(clean))
    return jsonify(service=_service_dict(service, _stats()))
