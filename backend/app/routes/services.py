from flask import Blueprint, jsonify

from ..extensions import db
from ..models.service import Service
from ..services.queue_service import waiting_counts
from ..utils.auth import error, roles_required

services_bp = Blueprint("services", __name__)


@services_bp.get("")
@roles_required()
def list_services():
    counts = waiting_counts()
    services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    return jsonify(services=[s.to_dict(waiting_count=counts.get(s.id, 0)) for s in services])


@services_bp.get("/<int:service_id>")
@roles_required()
def get_service(service_id: int):
    service = db.session.get(Service, service_id)
    if service is None or service.status != "ACTIVE":
        return error("service_not_found", "Service not found.", 404)
    return jsonify(service=service.to_dict(waiting_count=waiting_counts().get(service.id, 0)))
