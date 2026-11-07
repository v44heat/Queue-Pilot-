"""Explainable, advisory counter recommendations.

The engine never opens anything; it reads the live state of each active service and applies documented rules.
A recommendation to OPEN_COUNTER is made when ANY of these holds (thresholds are system settings):
  R1  no counter is open while customers are waiting;
  R2  congestion is HIGH or CRITICAL (waiting customers at or above the configured bounds);
  R3  a new customer's estimated wait is at least `recommendations.wait_threshold_minutes`;
  R4  customers arrive faster than the open counters can serve them: offered load per open counter
      = arrivals/hour x recent average service minutes / 60 / open counters is at least 1, with people waiting.
Suggested additional counters: 1, or 2 when congestion is CRITICAL; never more than the number of CLOSED counters
that have an active staff member assigned. With no such counter the advice is to assign staff instead.
Priority: URGENT (R1, or CRITICAL), HIGH (HIGH congestion or estimate >= 2x the threshold), otherwise MEDIUM.
Every recommendation lists the data behind it and makes no promise about how much waiting would fall.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from ..extensions import db
from ..models.counter import Counter, StaffCounterAssignment
from ..models.queue import QueueTicket
from ..models.service import Service
from ..models.user import User
from . import congestion_service, prediction_service, settings_service
from .queue_service import waiting_counts

PRIORITY_RANK = {"URGENT": 3, "HIGH": 2, "MEDIUM": 1, "NONE": 0}


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def recommend(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    limits = congestion_service.thresholds()
    wait_threshold = settings_service.get("recommendations.wait_threshold_minutes")
    window = settings_service.get("recommendations.arrival_window_minutes")
    since = now - timedelta(minutes=window)
    arrivals = dict(
        db.session.query(QueueTicket.service_id, func.count(QueueTicket.id))
        .filter(QueueTicket.join_time >= since).group_by(QueueTicket.service_id).all()
    )
    waiting = waiting_counts()
    results = [
        _for_service(s, waiting.get(s.id, 0), arrivals.get(s.id, 0), window, limits, wait_threshold)
        for s in Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
    ]
    results.sort(key=lambda r: (-PRIORITY_RANK[r["priority"]], -r["data"]["waiting"], r["service"]["name"]))
    return results


def _staffed_closed_counters(service: Service) -> list[Counter]:
    return (
        Counter.query.filter(Counter.service_id == service.id, Counter.status == "CLOSED")
        .filter(Counter.assignments.any(StaffCounterAssignment.staff.has(User.status == "ACTIVE")))
        .order_by(Counter.name).all()
    )


def _for_service(service: Service, waiting_n: int, joined_in_window: int, window: int, limits: dict, wait_threshold: float) -> dict:
    state = prediction_service.service_state(service)
    cap, avg = state["cap"], state["avg"]
    opened, busy = cap["open"], cap["busy"]
    level = congestion_service.level_for(waiting_n, limits)
    pred = prediction_service.predict(prediction_service.features_from_state(service, state, waiting_n, waiting_n + 1)) if opened else None
    wait_min = pred.minutes if pred is not None else None
    arrival_rate = joined_in_window * 60 / window
    load = (arrival_rate * avg / 60 / opened) if opened else None
    candidates = _staffed_closed_counters(service)

    reasons, urgent = [], False
    if opened == 0 and waiting_n > 0:
        urgent = True
        reasons.append(f"No counter is open for this service while {waiting_n} {_plural(waiting_n, 'customer is', 'customers are')} waiting.")
    if level in ("HIGH", "CRITICAL"):
        reasons.append(f"{waiting_n} customers are waiting, which is {level} congestion "
                       f"({level} starts at {limits[level.lower()]} waiting).")
    if wait_min is not None and wait_min >= wait_threshold:
        reasons.append(f"A new customer would wait about {_num(wait_min)} minutes "
                       f"(the alert threshold is {_num(wait_threshold)} minutes).")
    overloaded = load is not None and waiting_n > 0 and load >= 1
    if overloaded:
        reasons.append(f"Customers are arriving at about {_num(arrival_rate)} per hour (last {window} minutes) but the "
                       f"{opened} open {_plural(opened, 'counter', 'counters')} can serve about {_num(opened * 60 / avg)} per hour "
                       f"at the recent {_num(avg)}-minute average.")
    triggered = bool(reasons)

    data = {
        "waiting": waiting_n, "congestion": level, "estimated_wait": wait_min, "estimate_source": pred.source if pred else "unavailable",
        "arrival_rate_per_hour": round(arrival_rate, 1), "arrival_window_minutes": window, "avg_service_minutes": avg,
        "offered_load": None if load is None else round(load, 2),
        "counters": {"open": opened, "busy": busy, "available": cap["available"]}, "staff_on_open_counters": state["staff"],
    }
    base = {"service": {"id": service.id, "name": service.name, "prefix": service.prefix}, "data": data,
            "candidate_counters": [{"id": c.id, "name": c.name} for c in candidates]}

    if not triggered:
        return {**base, "action": "NONE", "priority": "NONE", "suggested_additional_counters": 0,
                "headline": f"No action needed for {service.name}.",
                "reasons": [f"{waiting_n} {_plural(waiting_n, 'customer is', 'customers are')} waiting ({level.lower()} congestion; "
                            f"HIGH starts at {limits['high']}).",
                            *([f"The estimated wait for a new customer is about {_num(wait_min)} minutes, below the {_num(wait_threshold)}-minute threshold."]
                              if wait_min is not None else []),
                            *(["Open counters are keeping up with recent arrivals."] if load is not None and load < 1 and joined_in_window else [])]}

    if opened and cap["available"] == 0:
        reasons.append(f"All {opened} open {_plural(opened, 'counter is', 'counters are')} busy.")
    suggested = min(2 if level == "CRITICAL" else 1, len(candidates))
    if candidates:
        names = ", ".join(c.name for c in candidates[:3])
        reasons.append(f"{_plural(len(candidates), 'Closed counter', 'Closed counters')} with assigned staff: {names}.")
        action_text = f"Consider opening {suggested} additional {_plural(suggested, 'counter', 'counters')}."
    else:
        reasons.append("No closed counter with an active assigned staff member is available for this service.")
        action_text = "Consider assigning staff to another counter for this service."

    priority = "URGENT" if (urgent or level == "CRITICAL") else "HIGH" if (level == "HIGH" or (wait_min is not None and wait_min >= 2 * wait_threshold)) else "MEDIUM"
    lead = f"{level.title()} congestion detected. " if level in ("HIGH", "CRITICAL") else ""
    if opened == 0:
        facts = f"{waiting_n} {_plural(waiting_n, 'customer is', 'customers are')} waiting and no counter is open."
    else:
        est = f" the estimated waiting time is {_num(wait_min)} minutes," if wait_min is not None else ""
        facts = f"{waiting_n} {_plural(waiting_n, 'customer is', 'customers are')} waiting,{est} and {opened} {_plural(opened, 'counter is', 'counters are')} active."
    return {**base, "action": "OPEN_COUNTER", "priority": priority, "suggested_additional_counters": suggested,
            "headline": f"{lead}{facts} {action_text}", "reasons": reasons}
