"""Administrator counter configuration. Admins configure counters and assignments but
cannot open counters or call/serve customers; those are staff workflows."""
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.counter import Counter, StaffCounterAssignment
from ..models.service import Service
from ..models.user import User
from ..services import counter_service as cs
from ..utils.auth import error, roles_required

counters_bp = Blueprint("counters", __name__)

ADMIN_SETTABLE = ("CLOSED", "INACTIVE")


def _validate(data, creating: bool):
    errors, clean = {}, {}
    if not isinstance(data, dict) or (not creating and not data):
        return {}, {"_": "Provide the fields to set."}
    if creating or "name" in data:
        name = data.get("name").strip() if isinstance(data.get("name"), str) else ""
        if not (2 <= len(name) <= 100):
            errors["name"] = "Name is required (2-100 characters)."
        else:
            clean["name"] = name
    if "service_id" in data:
        sid = data["service_id"]
        if sid is None:
            clean["service_id"] = None
        elif isinstance(sid, int) and not isinstance(sid, bool) and db.session.get(Service, sid):
            clean["service_id"] = sid
        else:
            errors["service_id"] = "Unknown service."
    if "status" in data:
        status = data["status"].upper() if isinstance(data["status"], str) else ""
        if status not in ADMIN_SETTABLE:
            errors["status"] = "Administrators may set CLOSED or INACTIVE; staff open counters."
        else:
            clean["status"] = status
    return clean, errors


@counters_bp.get("")
@roles_required("ADMIN")
def list_counters():
    counters = Counter.query.order_by(Counter.name).all()
    return jsonify(counters=[cs.serialize_counter(c, include_staff=True) for c in counters])


@counters_bp.post("")
@roles_required("ADMIN")
def create_counter():
    clean, errors = _validate(request.get_json(silent=True), creating=True)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)
    counter = Counter(name=clean["name"], service_id=clean.get("service_id"), status=clean.get("status", "CLOSED"))
    db.session.add(counter)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("name_taken", "A counter with this name already exists.", 409, {"name": "Name already in use."})
    current_app.logger.info("Admin id=%s created counter id=%s", g.current_user.id, counter.id)
    return jsonify(counter=cs.serialize_counter(counter, include_staff=True)), 201


@counters_bp.patch("/<int:counter_id>")
@roles_required("ADMIN")
def update_counter(counter_id: int):
    counter = db.session.get(Counter, counter_id)
    if counter is None:
        return error("not_found", "Counter not found.", 404)
    clean, errors = _validate(request.get_json(silent=True), creating=False)
    if errors:
        return error("validation_error", "Please correct the highlighted fields.", 400, errors)
    if ({"service_id", "status"} & clean.keys()) and cs.current_ticket(counter.id) is not None:
        return error("counter_busy", "This counter is serving a customer. Try again when it is free.", 409)
    for k, v in clean.items():
        setattr(counter, k, v)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("name_taken", "A counter with this name already exists.", 409, {"name": "Name already in use."})
    return jsonify(counter=cs.serialize_counter(counter, include_staff=True))


@counters_bp.post("/<int:counter_id>/staff")
@roles_required("ADMIN")
def assign_staff(counter_id: int):
    counter = db.session.get(Counter, counter_id)
    if counter is None:
        return error("not_found", "Counter not found.", 404)
    body = request.get_json(silent=True) or {}
    staff = db.session.get(User, body.get("staff_id")) if isinstance(body.get("staff_id"), int) else None
    if staff is None or staff.role != "STAFF" or staff.status != "ACTIVE":
        return error("validation_error", "staff_id must be an active STAFF account.", 400)
    db.session.add(StaffCounterAssignment(staff_id=staff.id, counter_id=counter.id))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return error("already_assigned", "This staff member is already assigned to the counter.", 409)
    return jsonify(counter=cs.serialize_counter(counter, include_staff=True)), 201


@counters_bp.delete("/<int:counter_id>/staff/<int:staff_id>")
@roles_required("ADMIN")
def unassign_staff(counter_id: int, staff_id: int):
    counter = db.session.get(Counter, counter_id)
    if counter is None:
        return error("not_found", "Counter not found.", 404)
    link = StaffCounterAssignment.query.filter_by(counter_id=counter_id, staff_id=staff_id).first()
    if link is None:
        return error("not_found", "That staff member is not assigned to this counter.", 404)
    if len(counter.assignments) == 1 and cs.current_ticket(counter.id) is not None:
        return error("counter_busy", "Cannot remove the only staff member while a customer is being served.", 409)
    db.session.delete(link)
    db.session.commit()
    return jsonify(counter=cs.serialize_counter(counter, include_staff=True))
