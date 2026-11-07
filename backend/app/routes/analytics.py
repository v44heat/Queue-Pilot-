"""Administrator analytics and counter recommendations (read-only)."""
from flask import Blueprint, jsonify, request

from ..services import analytics_service as an
from ..services import recommendation_service
from ..services.queue_service import QueueError
from ..utils.auth import roles_required

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/queue-length")
@roles_required("ADMIN")
def queue_length():
    try:
        hours = int(request.args.get("hours", 24))
    except ValueError:
        raise QueueError("validation_error", "hours must be an integer.", 400)
    return jsonify(an.queue_length_series(hours, an.parse_service_id(request.args)))


@analytics_bp.get("/waiting-by-hour")
@roles_required("ADMIN")
def waiting_by_hour():
    start, end = an.parse_range(request.args)
    return jsonify(an.waiting_by_hour(start, end, an.parse_service_id(request.args)))


@analytics_bp.get("/daily-volume")
@roles_required("ADMIN")
def daily_volume():
    start, end = an.parse_range(request.args)
    return jsonify(an.daily_volume(start, end, an.parse_service_id(request.args)))


@analytics_bp.get("/service-performance")
@roles_required("ADMIN")
def service_performance():
    start, end = an.parse_range(request.args)
    return jsonify(an.service_performance(start, end, an.parse_service_id(request.args)))


@analytics_bp.get("/counter-utilization")
@roles_required("ADMIN")
def counter_utilization():
    start, end = an.parse_range(request.args)
    return jsonify(an.counter_utilization(start, end))


@analytics_bp.get("/prediction-accuracy")
@roles_required("ADMIN")
def prediction_accuracy():
    start, end = an.parse_range(request.args)
    return jsonify(an.prediction_accuracy(start, end, an.parse_service_id(request.args)))


@analytics_bp.get("/recommendations")
@roles_required("ADMIN")
def recommendations():
    """Advisory only: nothing is opened or changed by calling this."""
    return jsonify(recommendations=recommendation_service.recommend())
