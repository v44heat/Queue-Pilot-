"""Counter availability, capacity and serialization."""
from sqlalchemy import distinct, func

from ..extensions import db
from ..models.counter import Counter
from ..models.queue import QueueTicket
from .queue_service import local_day_start_utc, serialize_ticket_for_staff

HELD_STATUSES = ("CALLED", "SERVING")


def current_ticket(counter_id: int) -> QueueTicket | None:
    """The customer currently called to / being served at this counter (at most one)."""
    return QueueTicket.query.filter(
        QueueTicket.counter_id == counter_id, QueueTicket.status.in_(HELD_STATUSES)
    ).first()


def availability(counter: Counter, current: QueueTicket | None) -> str:
    if counter.status != "OPEN":
        return "UNAVAILABLE"
    return "BUSY" if current is not None else "AVAILABLE"


def capacity_by_service() -> dict[int, dict[str, int]]:
    """Per service: counters that are open, busy (holding a customer) and available."""
    open_rows = (
        db.session.query(Counter.service_id, func.count(Counter.id))
        .filter(Counter.status == "OPEN", Counter.service_id.isnot(None))
        .group_by(Counter.service_id).all()
    )
    busy_rows = (
        db.session.query(Counter.service_id, func.count(distinct(Counter.id)))
        .join(QueueTicket, QueueTicket.counter_id == Counter.id)
        .filter(Counter.status == "OPEN", QueueTicket.status.in_(HELD_STATUSES))
        .group_by(Counter.service_id).all()
    )
    busy = dict(busy_rows)
    return {
        sid: {"open": n, "busy": busy.get(sid, 0), "available": n - busy.get(sid, 0)}
        for sid, n in open_rows
    }


EMPTY_CAPACITY = {"open": 0, "busy": 0, "available": 0}


def serialize_counter(counter: Counter, include_staff: bool = False) -> dict:
    current = current_ticket(counter.id)
    d = {
        "id": counter.id,
        "name": counter.name,
        "status": counter.status,
        "availability": availability(counter, current),
        "service": None if counter.service is None else {
            "id": counter.service.id, "name": counter.service.name, "prefix": counter.service.prefix},
        "current_ticket": None if current is None else serialize_ticket_for_staff(current),
    }
    if include_staff:
        d["staff"] = [{"id": a.staff.id, "name": a.staff.name, "email": a.staff.email} for a in counter.assignments]
    return d


def counter_stats(counter: Counter) -> dict:
    """Real figures from the database for today (local day)."""
    start = local_day_start_utc()
    served = QueueTicket.query.filter(
        QueueTicket.counter_id == counter.id, QueueTicket.status == "COMPLETED", QueueTicket.service_end_time >= start
    )
    avg = (
        db.session.query(func.avg(QueueTicket.service_duration))
        .filter(QueueTicket.counter_id == counter.id, QueueTicket.status == "COMPLETED",
                QueueTicket.service_end_time >= start)
        .scalar()
    )
    waiting = 0
    if counter.service_id:
        waiting = QueueTicket.query.filter(
            QueueTicket.service_id == counter.service_id, QueueTicket.status == "WAITING").count()
    return {
        "served_today": served.count(),
        "avg_service_duration_today": None if avg is None else round(float(avg), 2),
        "waiting_for_service": waiting,
    }
