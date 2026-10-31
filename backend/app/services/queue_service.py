"""Queue business rules.

Ordering and eligibility (documented rules)
-------------------------------------------
* A ticket's place in line is its (queue_date, sequence) within its service.
* "People ahead" = tickets of the SAME service that are WAITING and sort before it.
* Position = people ahead + 1. Position is only defined while a ticket is WAITING.
* CALLED / SERVING tickets have left the waiting line, so they do not count as "ahead".
* CANCELLED, SKIPPED, ABSENT and COMPLETED are terminal: they leave the line, never return,
  and the customer must join again (receiving a new number) to be served.
* Positions are always computed live from current tickets, never stored.
"""
import random
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.queue import ACTIVE_STATUSES, TICKET_STATUSES, QueueCounter, QueueTicket
from ..models.service import Service

# Allowed status changes. Anything not listed is rejected.
TRANSITIONS: dict[str, frozenset[str]] = {
    "WAITING": frozenset({"CALLED", "CANCELLED", "SKIPPED"}),
    "CALLED": frozenset({"SERVING", "ABSENT", "SKIPPED"}),
    "SERVING": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
    "SKIPPED": frozenset(),
    "ABSENT": frozenset(),
}
assert set(TRANSITIONS) == set(TICKET_STATUSES)

_NO_RESET_DATE = date(1970, 1, 1)


class QueueError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---- numbering scope -------------------------------------------------------------------------
def _local_today() -> date:
    name = current_app.config.get("APP_TIMEZONE", "UTC")
    try:
        tz = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        current_app.logger.warning("Unknown APP_TIMEZONE %r; falling back to UTC", name)
        tz = timezone.utc
    return datetime.now(tz).date()


def numbering_scope_date() -> date:
    """Date that scopes ticket numbers. Daily reset (default) uses the local calendar day;
    QUEUE_RESET_DAILY=false keeps one continuous sequence per service."""
    if current_app.config.get("QUEUE_RESET_DAILY", True):
        return _local_today()
    return _NO_RESET_DATE


# ---- state machine ---------------------------------------------------------------------------
def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


def transition(ticket: QueueTicket, new_status: str) -> None:
    """Validate and apply a status change (caller commits). Phase 4 adds timestamp recording."""
    if not can_transition(ticket.status, new_status):
        raise QueueError(
            "invalid_transition",
            f"A {ticket.status.lower()} ticket cannot be changed to {new_status.lower()}.",
            409,
        )
    ticket.status = new_status


# ---- queries ---------------------------------------------------------------------------------
def active_ticket(user_id: int, service_id: int) -> QueueTicket | None:
    return QueueTicket.query.filter(
        QueueTicket.user_id == user_id,
        QueueTicket.service_id == service_id,
        QueueTicket.status.in_(ACTIVE_STATUSES),
    ).first()


def people_ahead(ticket: QueueTicket) -> int:
    return QueueTicket.query.filter(
        QueueTicket.service_id == ticket.service_id,
        QueueTicket.status == "WAITING",
        or_(
            QueueTicket.queue_date < ticket.queue_date,
            and_(QueueTicket.queue_date == ticket.queue_date, QueueTicket.sequence < ticket.sequence),
        ),
    ).count()


def waiting_counts() -> dict[int, int]:
    rows = (
        db.session.query(QueueTicket.service_id, func.count(QueueTicket.id))
        .filter(QueueTicket.status == "WAITING")
        .group_by(QueueTicket.service_id)
        .all()
    )
    return {sid: n for sid, n in rows}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite returns naive values; everything is stored as UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def serialize_ticket(ticket: QueueTicket) -> dict:
    ahead = people_ahead(ticket) if ticket.status == "WAITING" else None
    return {
        "id": ticket.id,
        "queue_number": ticket.queue_number,
        "service": {"id": ticket.service.id, "name": ticket.service.name, "prefix": ticket.service.prefix},
        "status": ticket.status,
        "people_ahead": ahead,
        "position": None if ahead is None else ahead + 1,
        "predicted_waiting_time": ticket.predicted_waiting_time,  # None until Phase 5 prediction
        "actual_waiting_time": ticket.actual_waiting_time,
        "service_duration": ticket.service_duration,
        "join_time": _iso(ticket.join_time),
        "called_time": _iso(ticket.called_time),
        "service_start_time": _iso(ticket.service_start_time),
        "service_end_time": _iso(ticket.service_end_time),
    }


# ---- commands --------------------------------------------------------------------------------
def _next_sequence(service_id: int, scope: date) -> int:
    """Issue the next number for (service, scope) while holding a row lock on the counter."""
    for _ in range(3):
        counter = db.session.execute(
            select(QueueCounter)
            .where(QueueCounter.service_id == service_id, QueueCounter.queue_date == scope)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if counter is None:
            counter = QueueCounter(service_id=service_id, queue_date=scope, last_number=0)
            db.session.add(counter)
            try:
                db.session.flush()
            except IntegrityError:  # another request created it first; retry and lock it
                db.session.rollback()
                continue
        counter.last_number += 1
        db.session.flush()
        return counter.last_number
    raise QueueError("queue_busy", "The queue is busy. Please try again.", 503)


def join_queue(user, service_id) -> QueueTicket:
    if not isinstance(service_id, int) or isinstance(service_id, bool):
        raise QueueError("validation_error", "service_id must be an integer.", 400)

    service = db.session.get(Service, service_id)
    if service is None:
        raise QueueError("service_not_found", "Service not found.", 404)
    if service.status != "ACTIVE":
        raise QueueError("service_unavailable", "This service is not currently accepting customers.", 409)

    user_id = user.id
    if active_ticket(user_id, service.id):
        raise QueueError("already_in_queue", "You already have an active ticket for this service.", 409)

    service_pk, prefix = service.id, service.prefix
    scope = numbering_scope_date()
    ticket = None
    for _attempt in range(10):
        try:
            sequence = _next_sequence(service_pk, scope)
            ticket = QueueTicket(
                queue_number=f"{prefix}-{sequence:03d}",
                user_id=user_id,
                service_id=service_pk,
                queue_date=scope,
                sequence=sequence,
                join_time=datetime.now(timezone.utc),
                status="WAITING",
            )
            db.session.add(ticket)
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
            # The database's partial unique index caught a concurrent duplicate.
            if active_ticket(user_id, service_pk):
                raise QueueError("already_in_queue", "You already have an active ticket for this service.", 409)
            # Otherwise two requests raced for the same number (databases without row
            # locking, e.g. SQLite). Nothing was committed, so back off briefly and try again.
            ticket = None
            time.sleep(random.uniform(0, 0.03))
        except QueueError:
            db.session.rollback()
            raise
    if ticket is None:
        current_app.logger.error("Could not issue a ticket after repeated collisions (service id=%s)", service_pk)
        raise QueueError("queue_busy", "The queue is busy. Please try again.", 503)

    current_app.logger.info("Ticket %s issued (ticket id=%s, user id=%s)", ticket.queue_number, ticket.id, user_id)
    return ticket


def cancel_ticket(user, ticket_id: int) -> QueueTicket:
    """Customers may cancel only their own WAITING ticket."""
    ticket = db.session.execute(
        select(QueueTicket).where(QueueTicket.id == ticket_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if ticket is None or ticket.user_id != user.id:
        db.session.rollback()
        raise QueueError("ticket_not_found", "Ticket not found.", 404)
    try:
        transition(ticket, "CANCELLED")
    except QueueError:
        db.session.rollback()
        raise QueueError("cannot_cancel", f"Only waiting tickets can be cancelled (this one is {ticket.status.lower()}).", 409)
    db.session.commit()
    return ticket
