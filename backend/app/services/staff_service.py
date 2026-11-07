"""Staff workflows: operate a counter and move tickets through the lifecycle.

Safety rules
------------
* Staff act only on counters they are assigned to.
* Calling uses an atomic compare-and-set (UPDATE ... WHERE status='WAITING'), so two staff
  members can never call the same ticket, even without row locks.
* A partial unique index guarantees one CALLED/SERVING ticket per counter.
* Waiting time and service duration are measured from the recorded timestamps, in minutes.
"""
from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models.counter import Counter, CounterSession, StaffCounterAssignment
from ..models.queue import QueueTicket
from . import notification_service, prediction_service
from .counter_service import current_ticket
from .queue_service import QueueError, transition


def _now() -> datetime:  # a function so tests can control the clock
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def minutes_between(start: datetime, end: datetime) -> float:
    return round(max((_aware(end) - _aware(start)).total_seconds(), 0) / 60, 2)


# ---- authorization ---------------------------------------------------------------------------
def _is_assigned(staff_id: int, counter_id: int) -> bool:
    return db.session.query(StaffCounterAssignment.id).filter_by(staff_id=staff_id, counter_id=counter_id).first() is not None


def assigned_counters(staff) -> list[Counter]:
    return (
        Counter.query.join(StaffCounterAssignment, StaffCounterAssignment.counter_id == Counter.id)
        .filter(StaffCounterAssignment.staff_id == staff.id).order_by(Counter.name).all()
    )


def get_assigned_counter(staff, counter_id: int) -> Counter:
    counter = db.session.get(Counter, counter_id)
    if counter is None or not _is_assigned(staff.id, counter.id):
        raise QueueError("counter_not_found", "Counter not found.", 404)
    return counter


def _locked_ticket_for(staff, ticket_id: int) -> QueueTicket:
    ticket = db.session.execute(
        select(QueueTicket).where(QueueTicket.id == ticket_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if ticket is None:
        raise QueueError("ticket_not_found", "Ticket not found.", 404)
    if ticket.counter_id is not None:
        allowed = _is_assigned(staff.id, ticket.counter_id)
    else:  # not yet at a counter: staff of any counter serving this service may act on it
        allowed = db.session.query(Counter.id).join(
            StaffCounterAssignment, StaffCounterAssignment.counter_id == Counter.id
        ).filter(StaffCounterAssignment.staff_id == staff.id, Counter.service_id == ticket.service_id).first() is not None
    if not allowed:
        db.session.rollback()
        raise QueueError("ticket_not_found", "Ticket not found.", 404)
    return ticket


# ---- counter open / close --------------------------------------------------------------------
def open_counter(staff, counter_id: int) -> Counter:
    counter = get_assigned_counter(staff, counter_id)
    if counter.status == "OPEN":
        raise QueueError("already_open", "This counter is already open.", 409)
    if counter.status == "INACTIVE":
        raise QueueError("counter_inactive", "This counter has been deactivated by an administrator.", 409)
    if counter.service_id is None:
        raise QueueError("no_service", "This counter has no service assigned yet.", 409)
    if counter.service.status != "ACTIVE":
        raise QueueError("service_inactive", "This counter's service has been deactivated.", 409)
    counter.status = "OPEN"
    db.session.add(CounterSession(counter_id=counter.id, opened_at=_now(), opened_by=staff.id))
    db.session.commit()
    return counter


def close_counter(staff, counter_id: int) -> Counter:
    counter = get_assigned_counter(staff, counter_id)
    if counter.status != "OPEN":
        raise QueueError("not_open", "This counter is not open.", 409)
    if current_ticket(counter.id) is not None:
        raise QueueError("counter_busy", "Finish, skip or mark absent the current customer before closing.", 409)
    counter.status = "CLOSED"
    CounterSession.query.filter_by(counter_id=counter.id, closed_at=None).update({"closed_at": _now()})
    db.session.commit()
    return counter


# ---- calling ---------------------------------------------------------------------------------
def _waiting_candidates(service_id: int) -> list[int]:
    """Id of the first waiting ticket in line. On PostgreSQL the row is locked and rows locked by
    another staff member are skipped, so concurrent callers receive different tickets."""
    stmt = (
        select(QueueTicket.id)
        .where(QueueTicket.service_id == service_id, QueueTicket.status == "WAITING")
        .order_by(QueueTicket.queue_date, QueueTicket.sequence)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return list(db.session.execute(stmt).scalars())


def call_next(staff, counter_id: int) -> QueueTicket:
    counter = get_assigned_counter(staff, counter_id)
    if counter.status != "OPEN":
        raise QueueError("counter_not_open", "Open the counter before calling customers.", 409)
    if counter.service_id is None:
        raise QueueError("no_service", "This counter has no service assigned.", 409)
    if current_ticket(counter.id) is not None:
        raise QueueError("counter_busy", "This counter already has a customer. Complete or release them first.", 409)

    service_id, cid, now = counter.service_id, counter.id, _now()
    for _ in range(5):
        ids = _waiting_candidates(service_id)
        if not ids:
            db.session.rollback()
            raise QueueError("queue_empty", "No customers are waiting for this service.", 404)
        # Atomic compare-and-set: succeeds only if the ticket is still WAITING. The database's
        # one-held-ticket-per-counter index may reject the UPDATE or the COMMIT; both mean "busy".
        try:
            result = db.session.execute(
                update(QueueTicket)
                .where(QueueTicket.id == ids[0], QueueTicket.status == "WAITING")
                .values(status="CALLED", counter_id=cid, called_time=now, wait_ended_time=now)
            )
            if result.rowcount == 1:
                db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise QueueError("counter_busy", "This counter already has a customer.", 409)
        if result.rowcount == 1:
            current_app.logger.info("Counter id=%s called ticket id=%s (staff id=%s)", cid, ids[0], staff.id)
            ticket = db.session.get(QueueTicket, ids[0], populate_existing=True)
            notification_service.notify_called(ticket)  # never blocks calling
            notification_service.check_service_queue(service_id)  # people behind moved up
            return db.session.get(QueueTicket, ids[0], populate_existing=True)
        db.session.rollback()  # someone else took it first; look at the next in line
    raise QueueError("queue_busy", "The queue is busy. Please try again.", 503)


# ---- ticket actions --------------------------------------------------------------------------
def _apply(staff, ticket_id: int, new_status: str, stamp) -> QueueTicket:
    ticket = _locked_ticket_for(staff, ticket_id)
    was_waiting = ticket.status == "WAITING"
    now = _now()
    try:
        transition(ticket, new_status, now)
    except QueueError:
        db.session.rollback()
        raise
    stamp(ticket, now)
    db.session.commit()
    notification_service.after_transition(ticket, new_status, was_waiting)  # never blocks the action
    return ticket


def start_service(staff, ticket_id: int) -> QueueTicket:
    def stamp(t, now):
        t.service_start_time = now
        t.actual_waiting_time = minutes_between(t.join_time, now)  # service_start_time - join_time
        prediction_service.record_actual(t)  # store the measured wait next to the original prediction
    return _apply(staff, ticket_id, "SERVING", stamp)


def complete_service(staff, ticket_id: int) -> QueueTicket:
    def stamp(t, now):
        t.service_end_time = now
        t.service_duration = minutes_between(t.service_start_time, now)  # service_end_time - service_start_time
    return _apply(staff, ticket_id, "COMPLETED", stamp)


def skip_ticket(staff, ticket_id: int) -> QueueTicket:
    return _apply(staff, ticket_id, "SKIPPED", lambda t, now: None)


def mark_absent(staff, ticket_id: int) -> QueueTicket:
    return _apply(staff, ticket_id, "ABSENT", lambda t, now: None)


def waiting_list(counter: Counter, limit: int = 50) -> list[QueueTicket]:
    if counter.service_id is None:
        return []
    return (
        QueueTicket.query.filter(QueueTicket.service_id == counter.service_id, QueueTicket.status == "WAITING")
        .order_by(QueueTicket.queue_date, QueueTicket.sequence).limit(limit).all()
    )
