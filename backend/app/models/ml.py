"""Trained-model registry and prediction audit log."""
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text

from ..extensions import db
from .user import utcnow

PREDICTION_SOURCES = ("machine_learning", "fallback")


class ModelVersion(db.Model):
    """One trained model. mae/rmse/r2 are the HELD-OUT TEST-set metrics measured at training time."""

    __tablename__ = "model_versions"

    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(60), nullable=False)
    version = db.Column(db.String(20), nullable=False)
    run_id = db.Column(db.String(36), nullable=False, index=True)  # models trained together share a run
    mae = db.Column(db.Float)
    rmse = db.Column(db.Float)
    r2 = db.Column(db.Float)
    training_date = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    model_path = db.Column(db.String(255), nullable=False)  # relative to ML_ARTIFACT_DIR
    data_source = db.Column(db.String(20), nullable=False)  # synthetic | historical | mixed
    details = db.Column(db.JSON)  # validation metrics, split, cleaning report, baseline, eligibility

    __table_args__ = (
        UniqueConstraint("model_name", "version", name="uq_model_versions_name_version"),
        # At most one model may be active.
        Index("uq_model_versions_one_active", "is_active", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active = 1")),
    )

    def to_dict(self) -> dict:
        d = self.details or {}
        return {
            "id": self.id, "model_name": self.model_name, "version": self.version, "run_id": self.run_id,
            "mae": self.mae, "rmse": self.rmse, "r2": self.r2,
            "training_date": self.training_date.isoformat() if self.training_date else None,
            "is_active": self.is_active, "data_source": self.data_source,
            "eligible": d.get("eligible"), "selected_in_run": d.get("selected_in_run"),
            "validation": d.get("validation"), "split": d.get("split"),
            "baseline": d.get("baseline"), "cleaning": d.get("cleaning"),
            "rows": d.get("rows"), "seed": d.get("seed"),
        }


class PredictionLog(db.Model):
    """Every ticket-time prediction, with the exact features used and (later) the actual outcome."""

    __tablename__ = "prediction_logs"

    id = db.Column(db.Integer, primary_key=True)
    queue_ticket_id = db.Column(db.Integer, db.ForeignKey("queue_tickets.id", ondelete="CASCADE"), nullable=False)
    model_version_id = db.Column(db.Integer, db.ForeignKey("model_versions.id", ondelete="SET NULL"))  # null for fallback
    source = db.Column(db.String(20), nullable=False)
    prediction = db.Column(db.Float, nullable=False)  # minutes
    actual_value = db.Column(db.Float)  # minutes; set when service starts
    prediction_error = db.Column(db.Float)  # prediction - actual (signed, minutes)
    features = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    ticket = db.relationship("QueueTicket")
    model_version = db.relationship("ModelVersion")

    __table_args__ = (
        CheckConstraint("source IN ('machine_learning','fallback')", name="ck_prediction_logs_source"),
        Index("ix_prediction_logs_ticket", "queue_ticket_id"),
        Index("ix_prediction_logs_model_version", "model_version_id"),
        Index("ix_prediction_logs_created_at", "created_at"),
    )
