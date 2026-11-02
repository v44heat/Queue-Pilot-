from flask import Blueprint, g, jsonify, request

from ..extensions import db, limiter
from ..models.service import Service
from ..services import prediction_service
from ..utils.auth import error, roles_required

predictions_bp = Blueprint("predictions", __name__)

OVERRIDABLE = ("people_ahead", "queue_length", "active_counters", "busy_counters")


@predictions_bp.post("/waiting-time")
@roles_required()
@limiter.limit("60 per minute")
def waiting_time():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error("validation_error", "Request body must be a JSON object.", 400)
    service_id = body.get("service_id")
    if isinstance(service_id, bool) or not isinstance(service_id, int):
        return error("validation_error", "service_id must be an integer.", 400)
    service = db.session.get(Service, service_id)
    if service is None or service.status != "ACTIVE":
        return error("service_not_found", "Service not found.", 404)

    overrides = {k: body[k] for k in OVERRIDABLE if k in body}
    # Scenario values are a staff/admin analysis tool. Everyone else always gets the trusted current state.
    if overrides and g.current_user.role == "CUSTOMER":
        return error("forbidden", "Only staff can supply scenario values; omit them to use the current queue state.", 403)
    try:
        pred = prediction_service.what_if(service, overrides)
    except ValueError as e:
        return error("validation_error", str(e), 400)

    return jsonify(
        predicted_waiting_time=pred.minutes, model=pred.model_name, model_version=pred.model_version,
        source=pred.source, reason=pred.reason, scenario=bool(overrides), features=pred.features,
    )
