"""Administrator dashboard and live queue monitor. Every figure comes from database queries."""
from sqlalchemy import func, or_

from ..extensions import db
from ..models.counter import Counter
from ..models.queue import ACTIVE_STATUSES, TICKET_STATUSES, QueueTicket
from ..models.service import Service
from ..models.user import User
from . import congestion_service, prediction_service
from .counter_service import EMPTY_CAPACITY, capacity_by_service, serialize_counter
from .queue_service import QueueError, _iso, local_day_start_utc, waiting_counts


def _count_by_service(*statuses: str) -> dict[int, int]:
    rows = (
        db.session.query(QueueTicket.service_id, func.count(QueueTicket.id))
        .filter(QueueTicket.status.in_(statuses)).group_by(QueueTicket.service_id).all()
    )
    return dict(rows)


def _round(value):
    return None if value is None else round(float(value), 2)


def dashboard() -> dict:
    """Summary cards, a per-service breakdown and the counter overview. 'Today' is the local calendar day."""
    start = local_day_start_utc()
    served_today = QueueTicket.query.filter(QueueTicket.status == "COMPLETED", QueueTicket.service_end_time >= start).count()
    avg_wait = db.session.query(func.avg(QueueTicket.actual_waiting_time)).filter(
        QueueTicket.service_start_time >= start, QueueTicket.actual_waiting_time.isnot(None)).scalar()
    avg_duration = db.session.query(func.avg(QueueTicket.service_duration)).filter(
        QueueTicket.status == "COMPLETED", QueueTicket.service_end_time >= start, QueueTicket.service_duration.isnot(None)).scalar()

    waiting, called, serving = waiting_counts(), _count_by_service("CALLED"), _count_by_service("SERVING")
    capacity, limits = capacity_by_service(), congestion_service.thresholds()
    services, levels = [], []
    for s in Service.query.filter_by(status="ACTIVE").order_by(Service.name).all():
        w = waiting.get(s.id, 0)
        level = congestion_service.level_for(w, limits)
        levels.append(level)
        services.append({
            "id": s.id, "name": s.name, "prefix": s.prefix, "waiting": w,
            "called": called.get(s.id, 0), "serving": serving.get(s.id, 0),
            "counters": capacity.get(s.id, EMPTY_CAPACITY), "congestion": level,
        })

    counters = Counter.query.order_by(Counter.name).all()
    return {
        "summary": {
            "served_today": served_today,
            "waiting": sum(waiting.values()),
            "called": sum(called.values()),
            "being_served": sum(serving.values()),
            "avg_waiting_time": _round(avg_wait),
            "avg_service_duration": _round(avg_duration),
            "active_counters": sum(1 for c in counters if c.status == "OPEN"),
            "busy_counters": sum(v["busy"] for v in capacity.values()),
            "total_counters": len(counters),
            "congestion": {"level": congestion_service.worst(levels), "thresholds": limits},
        },
        "services": services,
        "counters": [serialize_counter(c, include_staff=True) for c in counters],
    }


SORTS = {
    "number": QueueTicket.queue_number, "service": Service.name, "customer": User.name,
    "status": QueueTicket.status, "joined": QueueTicket.join_time,
}


def queue_monitor(args) -> dict:
    """Filterable, sortable, paginated list of tickets. Default: everyone currently in a queue."""
    status = (args.get("status") or "ACTIVE").upper()
    if status not in ("ACTIVE", "ALL") and status not in TICKET_STATUSES:
        raise QueueError("validation_error", f"status must be ACTIVE, ALL or one of {', '.join(TICKET_STATUSES)}.", 400)
    sort = args.get("sort") or ""
    if sort and sort not in SORTS:
        raise QueueError("validation_error", f"sort must be one of {', '.join(SORTS)}.", 400)
    order = (args.get("order") or "asc").lower()
    if order not in ("asc", "desc"):
        raise QueueError("validation_error", "order must be asc or desc.", 400)
    try:
        page = max(int(args.get("page", 1)), 1)
        per_page = min(max(int(args.get("per_page", 20)), 1), 100)
        service_id = int(args["service_id"]) if args.get("service_id") else None
    except ValueError:
        raise QueueError("validation_error", "page, per_page and service_id must be integers.", 400)

    q = QueueTicket.query.join(Service, QueueTicket.service_id == Service.id).join(User, QueueTicket.user_id == User.id)
    if status == "ACTIVE":
        q = q.filter(QueueTicket.status.in_(ACTIVE_STATUSES))
    elif status != "ALL":
        q = q.filter(QueueTicket.status == status)
    if service_id:
        q = q.filter(QueueTicket.service_id == service_id)
    search = (args.get("search") or "").strip().lower()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(func.lower(QueueTicket.queue_number).like(like), func.lower(User.name).like(like), func.lower(User.email).like(like)))

    if sort:
        col = SORTS[sort]
        q = q.order_by(col.asc() if order == "asc" else col.desc(), QueueTicket.id.desc())
    else:  # natural queue order within each service
        q = q.order_by(Service.name, QueueTicket.queue_date, QueueTicket.sequence)

    total = q.count()
    items = q.offset((page - 1) * per_page).limit(per_page).all()
    estimates = prediction_service.estimates_for(items)
    rows = []
    for t in items:
        ahead, est = estimates.get(t.id, (None, None))
        rows.append({
            "id": t.id, "queue_number": t.queue_number,
            "service": {"id": t.service.id, "name": t.service.name, "prefix": t.service.prefix},
            "customer": {"id": t.user.id, "name": t.user.name, "email": t.user.email},
            "status": t.status,
            "position": None if ahead is None else ahead + 1,
            "people_ahead": ahead,
            "estimated_wait": est,
            "counter": None if t.counter is None else {"id": t.counter.id, "name": t.counter.name},
            "join_time": _iso(t.join_time), "called_time": _iso(t.called_time),
        })
    return {"tickets": rows, "page": page, "per_page": per_page, "total": total, "pages": (total + per_page - 1) // per_page}
