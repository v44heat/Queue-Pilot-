"""Customer notifications.

Rules (all thresholds can be overridden in app config):
* QUEUE_JOINED       - once, when a ticket is issued.
* CALLED             - once, when staff call the ticket; names the counter (this is also the counter assignment).
* TURN_APPROACHING   - once per ticket, when at most NOTIFY_APPROACHING_AHEAD (default 2) people are ahead.
                       Checked whenever someone ahead leaves the line (called, cancelled, skipped).
* WAIT_TIME_CHANGED  - when the live estimate differs from the last one the customer was told by at least
                       10 minutes AND at least 25% (of the previous estimate, minimum base 1 minute). Checked when
                       the customer's ticket is refreshed, so it follows the same polling the app already does.
* CANCELLED / SKIPPED / ABSENT - once, when the ticket leaves the line without being served.

Sending a notification never blocks or fails a queue operation: every function here swallows and logs errors.
"""
from flask import current_app
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.notification import Notification
from ..models.queue import QueueTicket
from .queue_service import people_ahead

APPROACHING_AHEAD = 2
WAIT_CHANGE_MIN_MINUTES = 10.0
WAIT_CHANGE_MIN_RATIO = 0.25


def _send(user_id: int, ticket: QueueTicket | None, type_: str, title: str, message: str, once: bool = True) -> bool:
    """Store a notification. Returns False if it was a duplicate or failed (never raises)."""
    try:
        key = f"{ticket.id}:{type_}" if (once and ticket is not None) else None
        if key and db.session.query(Notification.id).filter_by(dedupe_key=key).first():
            return False
        db.session.add(Notification(user_id=user_id, queue_ticket_id=ticket.id if ticket else None, type=type_,
                                    title=title, message=message, dedupe_key=key))
        db.session.commit()
        return True
    except IntegrityError:  # a concurrent request stored the same once-only notification first
        db.session.rollback()
        return False
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Could not store %s notification", type_)
        return False


def _ahead_text(ahead: int) -> str:
    if ahead == 0:
        return "Nobody is ahead of you."
    return "1 person is ahead of you." if ahead == 1 else f"{ahead} people are ahead of you."


def notify_joined(ticket: QueueTicket, prediction=None) -> None:
    try:
        text = f"Ticket {ticket.queue_number} for {ticket.service.name}. {_ahead_text(people_ahead(ticket))}"
        if prediction is not None and prediction.minutes:
            text += f" Estimated wait: about {round(prediction.minutes)} minutes."
        _send(ticket.user_id, ticket, "QUEUE_JOINED", "You're in the queue", text)
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("notify_joined failed")


def notify_called(ticket: QueueTicket) -> None:
    try:
        counter = ticket.counter.name if ticket.counter else "the counter"
        _send(ticket.user_id, ticket, "CALLED", "It's your turn",
              f"Ticket {ticket.queue_number}: please go to {counter}.")
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("notify_called failed")


def notify_cancelled(ticket: QueueTicket) -> None:
    _send(ticket.user_id, ticket, "CANCELLED", "Ticket cancelled",
          f"Ticket {ticket.queue_number} was cancelled. You can join the queue again at any time.")


def after_transition(ticket: QueueTicket, new_status: str, was_waiting: bool) -> None:
    """Called after staff change a ticket. Never raises."""
    try:
        if new_status == "SKIPPED":
            _send(ticket.user_id, ticket, "SKIPPED", "Your ticket was skipped",
                  f"Ticket {ticket.queue_number} was skipped by staff. Join the queue again if you still need service.")
        elif new_status == "ABSENT":
            _send(ticket.user_id, ticket, "ABSENT", "Marked as absent",
                  f"You were not at the counter when ticket {ticket.queue_number} was called. "
                  "Join the queue again if you still need service.")
        if was_waiting:  # a waiting customer left the line, so people behind moved up
            check_service_queue(ticket.service_id)
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("after_transition notifications failed")


def check_service_queue(service_id: int) -> None:
    """Tell customers near the front that their turn is approaching (once each)."""
    try:
        limit = int(current_app.config.get("NOTIFY_APPROACHING_AHEAD", APPROACHING_AHEAD))
        front = (
            QueueTicket.query.filter(QueueTicket.service_id == service_id, QueueTicket.status == "WAITING")
            .order_by(QueueTicket.queue_date, QueueTicket.sequence).limit(limit + 1).all()
        )
        for ahead, t in enumerate(front):
            text = (f"Ticket {t.queue_number}: you're next. Please be ready." if ahead == 0
                    else f"Ticket {t.queue_number}: {_ahead_text(ahead)} Please be ready.")
            _send(t.user_id, t, "TURN_APPROACHING", "Your turn is coming up", text)
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("check_service_queue failed")


def is_significant_change(old: float, new: float) -> bool:
    diff = abs(new - old)
    return diff >= WAIT_CHANGE_MIN_MINUTES and diff / max(old, 1.0) >= WAIT_CHANGE_MIN_RATIO


def maybe_notify_wait_change(ticket: QueueTicket, estimate: dict | None) -> None:
    """Compare the fresh estimate with the last one the customer was told; notify on a significant change."""
    try:
        if ticket.status != "WAITING" or not estimate or estimate.get("minutes") is None:
            return
        new, old = float(estimate["minutes"]), ticket.notified_wait_estimate
        if old is None:  # first usable estimate (e.g. a counter opened after joining): record it silently
            ticket.notified_wait_estimate = new
            db.session.commit()
            return
        if is_significant_change(old, new):
            sent = _send(ticket.user_id, ticket, "WAIT_TIME_CHANGED", "Waiting time updated",
                         f"Ticket {ticket.queue_number}: your estimated wait changed from about {round(old)} "
                         f"to about {round(new)} minutes.", once=False)
            if sent:
                ticket.notified_wait_estimate = new
                db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("maybe_notify_wait_change failed")
