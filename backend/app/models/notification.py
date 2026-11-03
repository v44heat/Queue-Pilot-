"""In-app notifications (persistent; the core app needs no email/SMS provider)."""
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from ..extensions import db
from .user import utcnow

NOTIFICATION_TYPES = (
    "QUEUE_JOINED", "TURN_APPROACHING", "CALLED", "WAIT_TIME_CHANGED", "CANCELLED", "SKIPPED", "ABSENT",
)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    queue_ticket_id = db.Column(db.Integer, db.ForeignKey("queue_tickets.id", ondelete="SET NULL"))
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(30), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    # "<ticket id>:<type>" for notifications that may be sent only once per ticket; NULL when repeatable.
    # The unique constraint makes "only once" hold even when two requests race.
    dedupe_key = db.Column(db.String(80))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "type IN ('QUEUE_JOINED','TURN_APPROACHING','CALLED','WAIT_TIME_CHANGED','CANCELLED','SKIPPED','ABSENT')",
            name="ck_notifications_type",
        ),
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
        Index("ix_notifications_ticket", "queue_ticket_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "message": self.message, "type": self.type,
            "is_read": self.is_read, "queue_ticket_id": self.queue_ticket_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
