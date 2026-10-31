"""Queue tickets and per-service numbering counters."""
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text

from ..extensions import db
from .user import utcnow

TICKET_STATUSES = ("WAITING", "CALLED", "SERVING", "COMPLETED", "CANCELLED", "SKIPPED", "ABSENT")
ACTIVE_STATUSES = ("WAITING", "CALLED", "SERVING")
TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "SKIPPED", "ABSENT")

_ACTIVE_SQL = "status IN ('WAITING','CALLED','SERVING')"


class QueueCounter(db.Model):
    """Last issued sequence number for a service within a numbering scope (a day by default).

    The row is locked (SELECT ... FOR UPDATE) while a number is issued, which serialises
    concurrent joins on PostgreSQL and guarantees gap-free, duplicate-free numbers."""

    __tablename__ = "queue_counters"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    queue_date = db.Column(db.Date, nullable=False)
    last_number = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("service_id", "queue_date", name="uq_queue_counters_service_date"),)


class QueueTicket(db.Model):
    __tablename__ = "queue_tickets"

    id = db.Column(db.Integer, primary_key=True)
    queue_number = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    # FK to counters is added in Phase 4, when the counters table is introduced.
    counter_id = db.Column(db.Integer)

    # Ordering key within a service: (queue_date, sequence). queue_date is the numbering scope.
    queue_date = db.Column(db.Date, nullable=False)
    sequence = db.Column(db.Integer, nullable=False)

    join_time = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    called_time = db.Column(db.DateTime(timezone=True))
    service_start_time = db.Column(db.DateTime(timezone=True))
    service_end_time = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20), nullable=False, default="WAITING")

    # Minutes. predicted_* is filled by the ML pipeline (Phase 5); actual_* / duration by staff workflow (Phase 4).
    predicted_waiting_time = db.Column(db.Float)
    actual_waiting_time = db.Column(db.Float)
    service_duration = db.Column(db.Float)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    service = db.relationship("Service")
    user = db.relationship("User")

    __table_args__ = (
        CheckConstraint(
            "status IN ('WAITING','CALLED','SERVING','COMPLETED','CANCELLED','SKIPPED','ABSENT')",
            name="ck_queue_tickets_status",
        ),
        # No two tickets can share a sequence number for a service in the same scope.
        UniqueConstraint("service_id", "queue_date", "sequence", name="uq_queue_tickets_service_date_seq"),
        # A customer may hold only one active ticket per service. Enforced by the database,
        # so it holds even when two requests race past the application-level check.
        Index(
            "uq_queue_tickets_one_active_per_user_service",
            "user_id", "service_id", unique=True,
            postgresql_where=text(_ACTIVE_SQL), sqlite_where=text(_ACTIVE_SQL),
        ),
        Index("ix_queue_tickets_service_status_order", "service_id", "status", "queue_date", "sequence"),
        Index("ix_queue_tickets_user_created", "user_id", "created_at"),
        Index("ix_queue_tickets_status", "status"),
        Index("ix_queue_tickets_join_time", "join_time"),
        Index("ix_queue_tickets_counter_id", "counter_id"),
    )
