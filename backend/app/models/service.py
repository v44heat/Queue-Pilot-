"""Service catalogue (what customers queue for)."""
from sqlalchemy import CheckConstraint

from ..extensions import db
from .user import utcnow

SERVICE_STATUSES = ("ACTIVE", "INACTIVE")


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    # Short prefix used in ticket numbers, e.g. GEN -> GEN-047.
    prefix = db.Column(db.String(6), nullable=False, unique=True)
    description = db.Column(db.Text)
    # Typical service time in minutes (a starting estimate; real durations are recorded in Phase 4).
    default_service_duration = db.Column(db.Integer, nullable=False, default=10)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("default_service_duration > 0", name="ck_services_duration_positive"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_services_status"),
    )

    def to_dict(self, waiting_count: int | None = None) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "prefix": self.prefix,
            "description": self.description,
            "default_service_duration": self.default_service_duration,
            "status": self.status,
        }
        if waiting_count is not None:
            d["waiting_count"] = waiting_count
        return d
