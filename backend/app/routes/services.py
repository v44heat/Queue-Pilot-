from flask import Blueprint, jsonify

from ..extensions import db
from ..models.service import Service
from ..services.counter_service import EMPTY_CAPACITY, capacity_by_service
from ..services.queue_service import waiting_counts
from ..utils.auth import error, roles_required

services_bp = Blueprint("services", __name__)


def _payload(service, counts, capacity):
    d = service.to_dict(waiting_count=counts.get(service.id, 0))
    d["counters"] = capacity.get(service.id, EMPTY_CAPACITY)  # open / busy / available counters
    return d


@services_bp.get("")
@roles_required()
def list_services():
    counts, capacity = waiting_counts(), capacity_by_service()
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    return jsonify(services=[_payload(s, counts, capacity) for s in services])


@services_bp.get("/<int:service_id>")
@roles_required()
def get_service(service_id: int):
    service = db.session.get(Service, service_id)
    if service is None or service.status != "ACTIVE":
        return error("service_not_found", "Service not found.", 404)
    return jsonify(service=_payload(service, waiting_counts(), capacity_by_service()))
