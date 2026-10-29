"""Health-check endpoints."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..extensions import db, limiter

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
@limiter.exempt
def health():
    """Liveness: the API process is up. Does not touch the database."""
    return jsonify(
        status="ok",
        service="queuepilot-api",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@health_bp.get("/health/db")
@limiter.exempt
def health_db():
    """Readiness: verifies a real round-trip to the configured database."""
    try:
        db.session.execute(text("SELECT 1"))
        dialect = db.engine.dialect.name
        return jsonify(status="ok", database="connected", dialect=dialect)
    except Exception:  # noqa: BLE001 - report failure without leaking details
        current_app.logger.exception("Database health check failed")
        db.session.rollback()
        return jsonify(status="error", database="unavailable"), 503
