"""Waiting-time prediction for tickets and what-if requests.

Features are derived from trusted database state at prediction time, never from the client.
A prediction is one of:
  machine_learning - from the active trained model,
  fallback         - the documented rule (people ahead / open counters x average duration),
                     used when no model is active or it cannot be loaded,
  unavailable      - no counter is open for the service, so no meaningful estimate exists.
Prediction failures never block queue operations.
"""
from dataclasses import dataclass, field

from flask import current_app
from sqlalchemy import distinct, func

from ..extensions import db
from ..ml.features import fallback_minutes, is_peak_hour, validate_feature_values
from ..ml.training import predict_minutes
from ..models.counter import Counter, StaffCounterAssignment
from ..models.ml import PredictionLog
from ..models.queue import QueueTicket
from ..models.service import Service
from . import ml_service
from .counter_service import EMPTY_CAPACITY, capacity_by_service
from .queue_service import _local_tz, people_ahead

RECENT_DURATIONS = 20  # completed tickets averaged to estimate the current service time


@dataclass
class Prediction:
    minutes: float | None
    source: str
    model_name: str | None = None
    model_version: str | None = None
    model_version_id: int | None = None
    reason: str | None = None
    features: dict = field(default_factory=dict)

    def to_public(self) -> dict:
        return {"minutes": self.minutes, "source": self.source, "model": self.model_name,
                "model_version": self.model_version, "reason": self.reason}


def local_now():
    from datetime import datetime
    return datetime.now(_local_tz())


def waiting_count(service_id: int) -> int:
    return QueueTicket.query.filter(QueueTicket.service_id == service_id, QueueTicket.status == "WAITING").count()


def average_service_duration(service: Service) -> float:
    rows = (
        db.session.query(QueueTicket.service_duration)
        .filter(QueueTicket.service_id == service.id, QueueTicket.status == "COMPLETED", QueueTicket.service_duration.isnot(None))
        .order_by(QueueTicket.service_end_time.desc()).limit(RECENT_DURATIONS).all()
    )
    values = [r[0] for r in rows]
    return round(sum(values) / len(values), 2) if values else float(service.default_service_duration)


def service_state(service: Service) -> dict:
    """The parts of the feature set that depend on the service, not on one ticket's place in line."""
    cap = capacity_by_service().get(service.id, EMPTY_CAPACITY)
    staff = (
        db.session.query(func.count(distinct(StaffCounterAssignment.staff_id)))
        .join(Counter, Counter.id == StaffCounterAssignment.counter_id)
        .filter(Counter.service_id == service.id, Counter.status == "OPEN").scalar()
    )
    return {"cap": cap, "staff": int(staff or 0), "avg": float(average_service_duration(service))}


def build_features(service: Service, people_ahead_n: int, queue_length: int) -> dict:
    return features_from_state(service, service_state(service), people_ahead_n, queue_length)


def features_from_state(service: Service, state: dict, people_ahead_n: int, queue_length: int, now=None) -> dict:
    cap, staff = state["cap"], state["staff"]
    now = now or local_now()
    return {
        "service_type": service.prefix,
        "people_ahead": int(people_ahead_n), "queue_length": int(queue_length),
        "active_counters": int(cap["open"]), "busy_counters": int(cap["busy"]),
        "average_service_duration": state["avg"],
        "staff_count": staff,
        "hour": now.hour, "day_of_week": now.weekday(), "peak_hour": is_peak_hour(now.hour),
    }


def predict(features: dict) -> Prediction:
    """Never raises: degrades to the documented fallback."""
    if features["active_counters"] < 1:
        return Prediction(None, "unavailable", reason="no_open_counters", features=features)
    reason = None
    try:
        mv = ml_service.active_model_version()
        if mv is None:
            reason = "no_active_model"
        else:
            minutes = round(predict_minutes(ml_service.load_pipeline(mv), features), 1)
            return Prediction(minutes, "machine_learning", mv.model_name, mv.version, mv.id, features=features)
    except Exception:  # noqa: BLE001 - a broken model must not break the queue
        current_app.logger.exception("Active model failed; using fallback estimate")
        reason = "model_unavailable"
    minutes = round(float(fallback_minutes(features["people_ahead"], features["average_service_duration"], features["active_counters"])), 1)
    return Prediction(minutes, "fallback", reason=reason, features=features)


def attach_prediction(ticket: QueueTicket) -> Prediction | None:
    """Predict at join time, store it on the ticket and log the exact features. Never raises."""
    try:
        ahead = people_ahead(ticket)
        length = max(waiting_count(ticket.service_id), ahead + 1)
        pred = predict(build_features(ticket.service, ahead, length))
        if pred.minutes is not None:
            ticket.predicted_waiting_time = pred.minutes
            ticket.notified_wait_estimate = pred.minutes
            db.session.add(PredictionLog(
                queue_ticket_id=ticket.id, model_version_id=pred.model_version_id,
                source=pred.source, prediction=pred.minutes, features=pred.features))
            db.session.commit()
        return pred
    except Exception:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Could not attach prediction to ticket id=%s", getattr(ticket, "id", None))
        return None


def live_estimate(ticket: QueueTicket) -> dict | None:
    """Current estimate for a still-waiting ticket (refreshes as the queue changes). Not logged:
    accuracy is always judged against the original prediction made at join time."""
    if ticket.status != "WAITING":
        return None
    try:
        ahead = people_ahead(ticket)
        length = max(waiting_count(ticket.service_id), ahead + 1)
        return predict(build_features(ticket.service, ahead, length)).to_public()
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Live estimate failed for ticket id=%s", ticket.id)
        return None


def record_actual(ticket: QueueTicket) -> None:
    """Called when service starts: store the measured wait next to the original prediction (caller commits)."""
    if ticket.actual_waiting_time is None:
        return
    for log in PredictionLog.query.filter_by(queue_ticket_id=ticket.id, actual_value=None).all():
        log.actual_value = ticket.actual_waiting_time
        log.prediction_error = round(log.prediction - ticket.actual_waiting_time, 2)


def what_if(service: Service, overrides: dict) -> Prediction:
    """Prediction for 'a customer joining now', optionally with scenario values (staff/admin only)."""
    waiting = waiting_count(service.id)
    feats = build_features(service, waiting, waiting + 1)
    feats.update({k: v for k, v in overrides.items() if v is not None})
    validate_feature_values(feats)
    return predict(feats)


def estimates_for(tickets) -> dict:
    """{ticket_id: (people_ahead, estimate)} for the WAITING tickets in `tickets`.

    Computes each service's state and waiting order once, so a screen listing many tickets needs
    a handful of queries instead of several per row. Same numbers as live_estimate()."""
    from collections import defaultdict

    by_service = defaultdict(list)
    for t in tickets:
        if t.status == "WAITING":
            by_service[t.service_id].append(t)
    out, now = {}, local_now()
    for sid, items in by_service.items():
        service = items[0].service
        order = [r[0] for r in db.session.query(QueueTicket.id)
                 .filter(QueueTicket.service_id == sid, QueueTicket.status == "WAITING")
                 .order_by(QueueTicket.queue_date, QueueTicket.sequence).all()]
        position = {tid: i for i, tid in enumerate(order)}
        state = service_state(service)
        for t in items:
            ahead = position[t.id]
            feats = features_from_state(service, state, ahead, max(len(order), ahead + 1), now)
            out[t.id] = (ahead, predict(feats).to_public())
    return out
