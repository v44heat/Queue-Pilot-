"""Administrator ML management."""
from flask import Blueprint, jsonify, request

from ..extensions import db, limiter
from ..models.ml import PredictionLog
from ..services import ml_service
from ..models.ml import ModelVersion
from ..utils.auth import error, roles_required

ml_bp = Blueprint("ml", __name__)


@ml_bp.get("/models")
@roles_required("ADMIN")
def list_models():
    models = ModelVersion.query.order_by(ModelVersion.training_date.desc(), ModelVersion.id.desc()).all()
    return jsonify(models=[m.to_dict() for m in models])


@ml_bp.post("/train")
@roles_required("ADMIN")
@limiter.limit("6 per hour")
def train():
    body = request.get_json(silent=True) or {}
    source = str(body.get("source", "synthetic")).lower()
    rows, seed = body.get("rows", 6000), body.get("seed", 42)
    for name, v, lo, hi in (("rows", rows, 500, 50_000), ("seed", seed, 0, 2**31 - 1)):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            return error("validation_error", f"{name} must be an integer between {lo} and {hi}.", 400)
    versions = ml_service.train_run(source, rows, seed, activate_best=bool(body.get("activate_best", False)))
    return jsonify(models=[v.to_dict() for v in versions]), 201


@ml_bp.post("/models/<int:model_id>/activate")
@roles_required("ADMIN")
def activate(model_id: int):
    return jsonify(model=ml_service.activate(model_id).to_dict())


@ml_bp.get("/performance")
@roles_required("ADMIN")
def performance():
    return jsonify(ml_service.live_performance())


@ml_bp.get("/prediction-logs")
@roles_required("ADMIN")
def prediction_logs():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        per_page = min(max(int(request.args.get("per_page", 20)), 1), 100)
    except ValueError:
        return error("validation_error", "page and per_page must be integers.", 400)
    q = PredictionLog.query
    if request.args.get("with_actual") == "true":
        q = q.filter(PredictionLog.actual_value.isnot(None))
    total = q.count()
    items = q.order_by(PredictionLog.created_at.desc(), PredictionLog.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify(
        logs=[{
            "id": l.id, "queue_ticket_id": l.queue_ticket_id, "queue_number": l.ticket.queue_number if l.ticket else None,
            "source": l.source, "model": None if l.model_version is None else f"{l.model_version.model_name} {l.model_version.version}",
            "prediction": l.prediction, "actual_value": l.actual_value, "prediction_error": l.prediction_error,
            "features": l.features, "created_at": l.created_at.isoformat(),
        } for l in items],
        page=page, per_page=per_page, total=total, pages=(total + per_page - 1) // per_page,
    )
