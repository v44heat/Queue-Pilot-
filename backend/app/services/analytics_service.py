"""Analytics computed from tickets, counter sessions and prediction logs (no stored aggregates).

Dates are local calendar days (APP_TIMEZONE); timestamps are stored in UTC. A day's figures describe tickets
that JOINED that day, in their current state. Ranges are limited to 90 days because aggregation happens in
Python (fine for a single-site deployment; move to SQL grouping if volumes grow)."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_

from ..extensions import db
from ..ml.training import reporting_metrics
from ..models.counter import Counter, CounterSession
from ..models.ml import PredictionLog
from ..models.queue import QueueTicket
from ..models.service import Service
from .queue_service import QueueError, _local_today, _local_tz

MAX_DAYS = 90
MAX_POINTS = 500


# ---- helpers ---------------------------------------------------------------------------------
def to_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def local_date(dt: datetime) -> date:
    return to_utc(dt).astimezone(_local_tz()).date()


def day_start_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=_local_tz()).astimezone(timezone.utc)


def parse_range(args, default_days: int = 7) -> tuple[date, date]:
    """?days=N (ending today) or ?from=YYYY-MM-DD&to=YYYY-MM-DD, inclusive local dates."""
    try:
        if args.get("from") or args.get("to"):
            end = date.fromisoformat(args["to"]) if args.get("to") else _local_today()
            start = date.fromisoformat(args["from"]) if args.get("from") else end - timedelta(days=default_days - 1)
        else:
            n = int(args.get("days") or default_days)
            if n < 1:
                raise ValueError
            end = _local_today()
            start = end - timedelta(days=n - 1)
    except ValueError:
        raise QueueError("validation_error", "Dates must look like 2026-03-02 and days must be a positive whole number.", 400)
    if start > end:
        raise QueueError("validation_error", "'from' must not be after 'to'.", 400)
    if (end - start).days + 1 > MAX_DAYS:
        raise QueueError("validation_error", f"The range can span at most {MAX_DAYS} days.", 400)
    return start, end


def parse_service_id(args) -> int | None:
    try:
        return int(args["service_id"]) if args.get("service_id") else None
    except ValueError:
        raise QueueError("validation_error", "service_id must be an integer.", 400)


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return day_start_utc(start), day_start_utc(end + timedelta(days=1))


def _joined(start: date, end: date, service_id: int | None = None) -> list[QueueTicket]:
    r0, r1 = _bounds(start, end)
    q = QueueTicket.query.filter(QueueTicket.join_time >= r0, QueueTicket.join_time < r1)
    if service_id:
        q = q.filter(QueueTicket.service_id == service_id)
    return q.all()


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def _days(start: date, end: date):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---- queue length over time --------------------------------------------------------------------
def queue_length_series(hours: int = 24, service_id: int | None = None, now: datetime | None = None) -> dict:
    """Queue length reconstructed from join time and the moment each ticket left the waiting line.

    Each point holds `waiting` (customers waiting at that instant) and `peak` (the highest number waiting at any
    moment in the hour that ends there), so a spike between two boundaries is not missed. At the same instant a
    departure is counted before an arrival. Tickets that left the line before `wait_ended_time` was recorded
    (cancelled or skipped tickets from older versions) cannot be placed in time and are left out."""
    if not 1 <= hours <= 168:
        raise QueueError("validation_error", "hours must be between 1 and 168.", 400)
    now = to_utc(now) if now else datetime.now(timezone.utc)
    points = [now - timedelta(hours=i) for i in range(hours, -1, -1)]
    left = func.coalesce(QueueTicket.wait_ended_time, QueueTicket.called_time, QueueTicket.service_start_time)
    q = QueueTicket.query.filter(QueueTicket.join_time <= now, or_(QueueTicket.status == "WAITING", left > points[0]))
    if service_id:
        q = q.filter(QueueTicket.service_id == service_id)
    spans = [(to_utc(t.join_time), None if t.status == "WAITING" else to_utc(t.wait_ended_time or t.called_time or t.service_start_time))
             for t in q.all()]
    tz, fmt = _local_tz(), ("%a %H:%M" if hours > 24 else "%H:%M")
    waiting_at = lambda p: sum(1 for j, e in spans if j <= p and (e is None or e > p))  # noqa: E731
    events = sorted([(j, 1) for j, _ in spans] + [(e, -1) for _, e in spans if e is not None])  # leaves sort before joins
    series, prev, k = [], None, 0
    for p in points:
        level = waiting_at(p)
        peak = level
        if prev is not None:
            running = waiting_at(prev)
            peak = max(peak, running)
            while k < len(events) and events[k][0] <= prev:
                k += 1
            while k < len(events) and events[k][0] <= p:
                running += events[k][1]
                peak = max(peak, running)
                k += 1
        series.append({"time": p.isoformat(), "label": p.astimezone(tz).strftime(fmt), "waiting": level, "peak": peak})
        prev = p
    return {"hours": hours, "points": series, "peak": max(s["peak"] for s in series)}


# ---- waiting time by hour ----------------------------------------------------------------------
def waiting_by_hour(start: date, end: date, service_id: int | None = None) -> dict:
    """Average measured wait for customers who JOINED in each local hour of the day."""
    buckets = defaultdict(list)
    for t in _joined(start, end, service_id):
        if t.actual_waiting_time is not None:
            buckets[to_utc(t.join_time).astimezone(_local_tz()).hour].append(t.actual_waiting_time)
    hours = [{"hour": h, "label": f"{h:02d}:00", "avg_waiting": _avg(buckets[h]), "n": len(buckets[h])} for h in range(24)]
    return {"from": start.isoformat(), "to": end.isoformat(), "hours": hours, "measured": sum(h["n"] for h in hours)}


# ---- daily volume and outcomes -------------------------------------------------------------------
_OUTCOME_KEYS = {"COMPLETED": "completed", "CANCELLED": "cancelled", "SKIPPED": "skipped", "ABSENT": "absent",
                 "WAITING": "in_progress", "CALLED": "in_progress", "SERVING": "in_progress"}


def daily_volume(start: date, end: date, service_id: int | None = None) -> dict:
    days = {d: {"date": d.isoformat(), "label": d.strftime("%a %d %b"), "joined": 0, "completed": 0, "cancelled": 0,
                "skipped": 0, "absent": 0, "in_progress": 0} for d in _days(start, end)}
    for t in _joined(start, end, service_id):
        row = days[local_date(t.join_time)]
        row["joined"] += 1
        row[_OUTCOME_KEYS[t.status]] += 1
    rows = list(days.values())
    totals = {k: sum(r[k] for r in rows) for k in ("joined", "completed", "cancelled", "skipped", "absent", "in_progress")}
    return {"from": start.isoformat(), "to": end.isoformat(), "days": rows, "totals": totals}


# ---- service performance -------------------------------------------------------------------------
def service_performance(start: date, end: date, service_id: int | None = None) -> dict:
    by_service = defaultdict(list)
    for t in _joined(start, end, service_id):
        by_service[t.service_id].append(t)
    q = Service.query.order_by(Service.name)
    if service_id:
        q = q.filter(Service.id == service_id)
    rows = []
    for s in q.all():
        ts = by_service.get(s.id, [])
        if not ts and s.status != "ACTIVE":
            continue
        count = lambda status: sum(1 for t in ts if t.status == status)  # noqa: E731
        waits = [t.actual_waiting_time for t in ts if t.actual_waiting_time is not None]
        done = count("COMPLETED")
        rows.append({
            "service_id": s.id, "service": s.name, "prefix": s.prefix, "joined": len(ts), "completed": done,
            "completion_rate": round(done / len(ts), 4) if ts else None,
            "cancelled": count("CANCELLED"), "skipped": count("SKIPPED"), "absent": count("ABSENT"),
            "in_progress": sum(1 for t in ts if t.status in ("WAITING", "CALLED", "SERVING")),
            "avg_waiting": _avg(waits), "max_waiting": round(max(waits), 2) if waits else None,
            "avg_service_duration": _avg([t.service_duration for t in ts if t.status == "COMPLETED"]),
        })
    return {"from": start.isoformat(), "to": end.isoformat(), "services": rows}


# ---- counter utilization ---------------------------------------------------------------------------
def _overlap_minutes(a0, a1, b0, b1) -> float:
    return max((min(a1, b1) - max(a0, b0)).total_seconds(), 0) / 60


def counter_utilization(start: date, end: date, now: datetime | None = None) -> dict:
    """Utilization = minutes spent SERVING customers / minutes the counter was OPEN (both within the range).
    Time between calling a customer and starting service is not counted as serving. Counters with no recorded
    open time in the range report null: opening history is recorded from the moment this feature was introduced."""
    r0, r1 = _bounds(start, end)
    now = to_utc(now) if now else datetime.now(timezone.utc)
    sessions = defaultdict(list)
    for s in CounterSession.query.filter(CounterSession.opened_at < r1, or_(CounterSession.closed_at.is_(None), CounterSession.closed_at > r0)).all():
        sessions[s.counter_id].append((max(to_utc(s.opened_at), r0), min(to_utc(s.closed_at) if s.closed_at else now, r1)))
    tickets = defaultdict(list)
    for t in QueueTicket.query.filter(QueueTicket.status == "COMPLETED", QueueTicket.counter_id.isnot(None),
                                      QueueTicket.service_end_time >= r0, QueueTicket.service_start_time < r1).all():
        tickets[t.counter_id].append(t)

    rows = []
    for c in Counter.query.order_by(Counter.name).all():
        spans = [(a, b) for a, b in sessions.get(c.id, []) if b > a]
        open_min = sum((b - a).total_seconds() for a, b in spans) / 60
        done = tickets.get(c.id, [])
        busy = sum(_overlap_minutes(to_utc(t.service_start_time), to_utc(t.service_end_time), a, b) for t in done for a, b in spans)
        served = [t for t in done if r0 <= to_utc(t.service_end_time) < r1]
        rows.append({
            "counter_id": c.id, "counter": c.name, "service": c.service.name if c.service else None,
            "open_minutes": round(open_min, 1), "serving_minutes": round(busy, 1),
            "utilization": round(busy / open_min, 4) if open_min > 0 else None,
            "customers_served": len(served), "avg_service_duration": _avg([t.service_duration for t in served]),
        })
    return {"from": start.isoformat(), "to": end.isoformat(), "counters": rows}


# ---- prediction accuracy ---------------------------------------------------------------------------
def prediction_accuracy(start: date, end: date, service_id: int | None = None) -> dict:
    """Predicted vs actual waiting time for predictions made in the range whose outcome is known."""
    r0, r1 = _bounds(start, end)
    q = PredictionLog.query.filter(PredictionLog.created_at >= r0, PredictionLog.created_at < r1)
    if service_id:
        q = q.join(QueueTicket, QueueTicket.id == PredictionLog.queue_ticket_id).filter(QueueTicket.service_id == service_id)
    logs = q.order_by(PredictionLog.created_at).all()
    known = [l for l in logs if l.actual_value is not None]

    def block(items):
        n = len(items)
        m = reporting_metrics([l.actual_value for l in items], [l.prediction for l in items]) if n >= 1 else {"mae": None, "rmse": None, "r2": None}
        return {"n": n, **m}

    groups = defaultdict(list)
    for l in known:
        groups[(l.source, l.model_version_id)].append(l)
    group_rows = []
    for (source, mv_id), items in groups.items():
        mv = items[0].model_version
        group_rows.append({"source": source, "model": f"{mv.model_name} {mv.version}" if mv else None, **block(items)})
    daily = defaultdict(list)
    for l in known:
        daily[local_date(l.created_at)].append(l)
    trend = [{"date": d.isoformat(), "label": d.strftime("%d %b"), "n": len(v),
              "mae": round(sum(abs(l.prediction_error) for l in v) / len(v), 2),
              "bias": round(sum(l.prediction_error for l in v) / len(v), 2)} for d, v in sorted(daily.items())]
    recent = known[-MAX_POINTS:]
    return {
        "from": start.isoformat(), "to": end.isoformat(), "overall": block(known), "groups": group_rows, "trend": trend,
        "points": [{"predicted": l.prediction, "actual": l.actual_value, "source": l.source} for l in recent],
        "awaiting_outcome": len(logs) - len(known),
        "note": "Bias is the average of (predicted - actual); positive means customers were told longer than they waited.",
    }


# ---- per-day, per-service breakdown (basis of the daily/weekly/monthly reports) ----------------------
def daily_service_breakdown(start: date, end: date) -> list[dict]:
    names = {s.id: s for s in Service.query.all()}
    buckets: dict = defaultdict(list)
    for t in _joined(start, end):
        buckets[(local_date(t.join_time), t.service_id)].append(t)
    rows = []
    for (d, sid), ts in sorted(buckets.items(), key=lambda kv: (kv[0][0], names[kv[0][1]].name)):
        waits = [t.actual_waiting_time for t in ts if t.actual_waiting_time is not None]
        count = lambda status: sum(1 for t in ts if t.status == status)  # noqa: E731
        rows.append({
            "date": d.isoformat(), "service": names[sid].name, "prefix": names[sid].prefix, "joined": len(ts),
            "completed": count("COMPLETED"), "cancelled": count("CANCELLED"), "skipped": count("SKIPPED"), "absent": count("ABSENT"),
            "in_progress": sum(1 for t in ts if t.status in ("WAITING", "CALLED", "SERVING")),
            "avg_waiting": _avg(waits), "max_waiting": round(max(waits), 2) if waits else None,
            "avg_service_duration": _avg([t.service_duration for t in ts if t.status == "COMPLETED"]),
        })
    return rows
