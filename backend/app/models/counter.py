"""Service counters and staff-to-counter assignments."""
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from ..extensions import db
from .user import utcnow

# OPEN     - operating; staff can call customers.
# CLOSED   - not operating right now (default). Staff can open it.
# INACTIVE - disabled by an administrator; cannot be opened until re-enabled (set to CLOSED).
# "Busy" is not a stored status: it is derived from the counter having a CALLED/SERVING ticket.
COUNTER_STATUSES = ("OPEN", "CLOSED", "INACTIVE")


class Counter(db.Model):
    __tablename__ = "counters"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    status = db.Column(db.String(20), nullable=False, default="CLOSED")
    # A counter serves one service (null = not yet assigned, so it cannot call customers).
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    service = db.relationship("Service")
    assignments = db.relationship("StaffCounterAssignment", back_populates="counter", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("status IN ('OPEN','CLOSED','INACTIVE')", name="ck_counters_status"),)


class StaffCounterAssignment(db.Model):
    __tablename__ = "staff_counter_assignments"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    counter_id = db.Column(db.Integer, db.ForeignKey("counters.id", ondelete="CASCADE"), nullable=False)
    assigned_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    staff = db.relationship("User")
    counter = db.relationship("Counter", back_populates="assignments")

    __table_args__ = (
        UniqueConstraint("staff_id", "counter_id", name="uq_staff_counter"),
        Index("ix_staff_counter_assignments_counter_id", "counter_id"),
    )
